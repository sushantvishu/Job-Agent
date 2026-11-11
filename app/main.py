from __future__ import annotations

import csv
import random
import re
import shutil
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote_plus, urlparse

import typer
from rich.console import Console
from rich.table import Table

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.browser import BrowserSession
from app.config import load_config
from app.email_followup import EmailFollowupMonitor
from app.exporter import Exporter
from app.form_filler import FormFiller
from app.job_collector import JobCollector
from app.matcher import JobMatcher, TECHNICAL_SUPPORT_FALLBACK_DECISION, is_india_location
from app.notifier import write_autorun_summary
from app.ollama_client import OllamaClient
from app.profile_loader import load_answer_templates, load_profile, load_resume_text
from app.tracker import JobTracker
from app.utils import (
    FillResult,
    JobPosting,
    MatchResult,
    compact_whitespace,
    detect_source_from_url,
    extract_skills_from_text,
    load_json,
    normalize_key,
    setup_logger,
    unique_list,
)

app = typer.Typer(help="Semi-automatic cybersecurity job application agent.")
console = Console(legacy_windows=False)

from app.apply_path import (
    apply_path_group,
    detect_apply_path,
    duplicate_note_for_job,
    find_contact_methods,
    has_actionable_apply_or_contact,
    is_browser_closed_error,
    review_group_for_row,
    skip_linkedin_non_job_content_url,
    skip_reason_for_match,
)
from app.reporting import (
    note_noise_link_once,
    save_live_shortlist,
    write_review_shortlist_report,
    write_shortlist_report,
)
from app.search_helpers import (
    BASE_SEARCH_KEYWORDS,
    alert_name_for_keyword,
    build_search_keywords,
    build_search_urls,
    create_linkedin_alert,
    create_naukri_alert,
    linkedin_search_url,
    naukri_search_url,
    open_alert_page,
    prioritize_unsearched_keywords,
    search_key_from_url,
    suggest_profile_headline,
    write_profile_audit,
    write_search_alert_inputs,
    write_search_alert_report,
)

def close_blocked_application_pages(page, collector: JobCollector) -> int:
    closed = 0
    try:
        pages = list(page.context.pages)
    except Exception:  # noqa: BLE001
        return 0
    for candidate_page in pages:
        try:
            if candidate_page.is_closed():
                continue
            if not (
                collector.is_blocked_application_url(candidate_page.url)
                or collector.is_non_job_content_url(candidate_page.url)
            ):
                continue
            collector.logger.info("Closing blocked social/application/report tab: %s", candidate_page.url)
            candidate_page.close()
            closed += 1
        except Exception as exc:  # noqa: BLE001
            collector.logger.debug("Unable to close blocked application/report tab: %s", exc)
    try:
        if page.is_closed() and pages:
            for candidate_page in reversed(pages):
                if not candidate_page.is_closed():
                    candidate_page.bring_to_front()
                    break
    except Exception:  # noqa: BLE001
        pass
    return closed


def current_unblocked_context_page(page, collector: JobCollector):
    close_blocked_application_pages(page, collector)
    try:
        pages = [
            candidate_page
            for candidate_page in page.context.pages
            if not candidate_page.is_closed()
            and not collector.is_blocked_application_url(candidate_page.url)
            and not collector.is_non_job_content_url(candidate_page.url)
        ]
    except Exception:  # noqa: BLE001
        return page
    return pages[-1] if pages else page


GOOGLE_OAUTH_LABEL_PATTERN = re.compile(r"sign in with google|continue with google", re.IGNORECASE)
LOGIN_SUBMIT_PATTERN = re.compile(r"log ?in|sign ?in|continue|sign ?up|create account|register", re.IGNORECASE)
VERIFICATION_CODE_KEYWORDS = ("otp", "verification code", "email verification", "phone verification")
CAPTCHA_ONLY_KEYWORDS = ("captcha", "security check")


def _click_google_account_matching(page, email: str) -> bool:
    if email:
        entry = page.get_by_text(email, exact=False)
        if entry.count():
            entry.first.click()
            return True
    entries = page.locator("[data-identifier], div[role='link']")
    if entries.count() == 1:
        entries.first.click()
        return True
    return False


def _resolve_verification_code_prompt(page, logger) -> tuple[Any, bool]:
    try:
        body = compact_whitespace(page.locator("body").inner_text(timeout=5000)).lower()
    except Exception:  # noqa: BLE001
        return page, True

    has_captcha = any(keyword in body for keyword in CAPTCHA_ONLY_KEYWORDS)
    has_code_prompt = any(keyword in body for keyword in VERIFICATION_CODE_KEYWORDS)
    if not has_code_prompt:
        if has_captcha:
            return page, False  # real CAPTCHA / generic security check -> hard stop, unchanged
        return page, True  # no verification step present

    code_field = page.locator(
        "input[name*='otp' i], input[name*='code' i], input[id*='otp' i], input[id*='code' i], "
        "input[autocomplete='one-time-code']"
    ).first
    if not code_field.count():
        return page, False

    print("\nThis site is asking for a verification code (sent to your email/phone).")
    try:
        code = input("Enter the verification code you received: ").strip()
    except EOFError:
        logger.warning("No interactive input available for verification code prompt.")
        return page, False
    if not code:
        return page, False

    try:
        code_field.fill(code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to fill verification code field: %s", exc)
        return page, False

    confirm = page.get_by_role("button", name=re.compile(r"verify|confirm|continue|submit", re.IGNORECASE))
    if confirm.count():
        confirm.first.click()
        page.wait_for_timeout(2000)

    try:
        body = compact_whitespace(page.locator("body").inner_text(timeout=5000)).lower()
    except Exception:  # noqa: BLE001
        body = ""
    if any(keyword in body for keyword in CAPTCHA_ONLY_KEYWORDS):
        return page, False
    return page, True


def handle_company_site_login(page, collector: JobCollector, config, logger) -> tuple[Any, bool, str]:
    """Resolve a login/signup wall on a company career site. Never touches LinkedIn/Naukri
    (callers only invoke this on job.source == "company" pages) and never types anything
    into accounts.google.com -- if Google isn't already authenticated in this browser
    profile, this aborts safely instead of entering credentials there."""
    if not collector.page_needs_manual_login(page):
        return page, True, "no login required"

    google_target = page.get_by_role("button", name=GOOGLE_OAUTH_LABEL_PATTERN)
    if not google_target.count():
        google_target = page.get_by_role("link", name=GOOGLE_OAUTH_LABEL_PATTERN)
    if google_target.count():
        pages_before = list(page.context.pages)
        try:
            google_target.first.click()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to click Google OAuth button: %s", exc)
        else:
            page.wait_for_timeout(2500)
            oauth_page = (
                current_unblocked_context_page(page, collector)
                if len(page.context.pages) > len(pages_before)
                else page
            )
            if "accounts.google.com" in oauth_page.url:
                if oauth_page.locator("input[type='password']").count():
                    logger.warning("Google OAuth requires password entry; aborting login for %s", page.url)
                    return page, False, "google oauth requires manual login (password prompt detected)"
                clicked = _click_google_account_matching(oauth_page, config.company_site_login_email if config else "")
                if not clicked:
                    return page, False, "google account chooser is ambiguous; manual login required"
                oauth_page.wait_for_timeout(2000)
                if oauth_page.locator("input[type='password']").count():
                    return page, False, "google oauth requested password after account selection"
                consent = oauth_page.get_by_role("button", name=re.compile(r"continue|allow", re.IGNORECASE))
                if consent.count():
                    consent.first.click()
                    oauth_page.wait_for_timeout(2000)
                if oauth_page.locator("input[type='password']").count():
                    return page, False, "unexpected verification step after google oauth"
                final_page = current_unblocked_context_page(page, collector)
                return final_page, True, "google oauth completed via existing session"
            if oauth_page.url != page.url:
                return oauth_page, True, "google oauth completed (silent redirect)"

    if not config or not config.company_site_login_email or not config.company_site_login_password:
        return page, False, "no google oauth available and no company-site credential configured"

    email_field = page.locator("input[type='email'], input[name*='email' i], input[id*='email' i]").first
    password_field = page.locator("input[type='password']").first
    if not email_field.count() or not password_field.count():
        return page, False, "login page detected but no recognizable email/password fields found"

    try:
        email_field.fill(config.company_site_login_email)
        password_field.fill(config.company_site_login_password)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to fill company-site login fields: %s", exc)
        return page, False, "failed to fill company-site login fields"

    submit = page.get_by_role("button", name=LOGIN_SUBMIT_PATTERN)
    if submit.count():
        submit.first.click()
        page.wait_for_timeout(2500)

    page, resolved = _resolve_verification_code_prompt(page, logger)
    if not resolved:
        return page, False, "verification step could not be completed"

    if page.locator("input[type='password']").count() and collector.page_needs_manual_login(page):
        return page, False, "login attempt did not clear the login/signup page"
    return page, True, "logged in with shared company-site credential"


def append_company_site_context(
    page,
    collector: JobCollector,
    job: JobPosting,
    apply_path: str,
    noise_output_dir: Path | None = None,
    filler: FormFiller | None = None,
    config=None,
    profile=None,
    match: MatchResult | None = None,
    auto_submit_safe: bool = False,
) -> tuple[JobPosting, FillResult | None, Any]:
    if apply_path != "company website":
        return job, None, None
    try:
        close_blocked_application_pages(page, collector)
        original_pages = list(page.context.pages)
        blocked_click_counts: dict[str, int] = {}
        for pattern in ("apply on company website", "apply on company site", "company website", "apply now", "apply"):
            button = page.get_by_role("button", name=pattern, exact=False)
            link = page.get_by_role("link", name=pattern, exact=False)
            target = button if button.count() else link
            if not target.count():
                continue
            try:
                href = target.first.get_attribute("href", timeout=1000) or ""
                if href and (collector.is_blocked_application_url(href) or collector.is_non_job_content_url(href)):
                    collector.logger.info("Skipping blocked application/report link before click: %s", href)
                    if noise_output_dir:
                        note_noise_link_once(noise_output_dir, href, job.source, "blocked/social/report link before click", job.url)
                    continue
            except Exception:  # noqa: BLE001
                pass
            target.first.click()
            page.wait_for_timeout(2500)
            close_blocked_application_pages(page, collector)
            active_page = current_unblocked_context_page(page, collector) if len(page.context.pages) > len(original_pages) else page
            if active_page.url == job.url:
                continue
            if collector.is_blocked_application_url(active_page.url) or collector.is_non_job_content_url(active_page.url):
                collector.logger.info("Closing blocked social/application/report page after click: %s", active_page.url)
                blocked_key = BrowserSession.normalized_url_key(active_page.url)
                blocked_click_counts[blocked_key] = blocked_click_counts.get(blocked_key, 0) + 1
                if noise_output_dir:
                    note_noise_link_once(
                        noise_output_dir,
                        active_page.url,
                        job.source,
                        "blocked/social/report page opened from apply flow",
                        job.url,
                    )
                if active_page is not page:
                    try:
                        active_page.close()
                        page.bring_to_front()
                    except Exception:  # noqa: BLE001
                        pass
                if blocked_click_counts[blocked_key] >= 2:
                    collector.logger.info("Dropping repeated blocked/social/application URL for this job: %s", active_page.url)
                    if noise_output_dir:
                        note_noise_link_once(
                            noise_output_dir,
                            active_page.url,
                            job.source,
                            "repeated blocked/social/report page dropped for this job",
                            job.url,
                        )
                    return job, None, None
                continue

            if filler is None:
                company_context = collector.collect_company_context(active_page, active_page.url)
                if company_context:
                    job.application_url = active_page.url
                    job.criteria_text = compact_whitespace(f"{job.criteria_text}\n{company_context}")[:16000]
                    job.description = compact_whitespace(f"{job.description}\n{company_context}")[:20000]
                if active_page is not page:
                    try:
                        active_page.close()
                        page.bring_to_front()
                    except Exception:  # noqa: BLE001
                        pass
                return job, None, None

            job.application_url = active_page.url
            login_page, handled_ok, detail = handle_company_site_login(active_page, collector, config, collector.logger)
            if not handled_ok:
                collector.logger.warning("Company-site login not resolved for %s: %s", job.url, detail)
                return job, FillResult(status="needs_manual_input", submit_blockers=[detail]), login_page
            # Forward auto_submit_safe to enable autonomous submission across external ATS and company portals
            fill_result, application_page = filler.fill(
                page=login_page,
                job=job,
                match=match,
                profile=profile,
                auto_submit_safe=auto_submit_safe,
            )
            return job, fill_result, application_page
    except Exception as exc:  # noqa: BLE001
        collector.logger.warning("Unable to append company-site context for %s: %s", job.url, exc)
    return job, None, None


from app.runtime import build_runtime, ensure_runtime_layout


def print_match_summary(job: JobPosting, match: MatchResult, tracker: JobTracker | None = None) -> None:
    console.print(f"[bold]Job:[/bold] {job.title or 'Unknown title'}")
    console.print(f"[bold]Company:[/bold] {job.company or 'Unknown company'}")
    console.print(f"[bold]Source:[/bold] {job.source}")
    console.print(f"[bold]Location:[/bold] {job.location or 'Unknown'}")
    console.print(f"[bold]Score:[/bold] {match.score} / 100")
    console.print(f"[bold]Decision:[/bold] {match.decision}")
    if match.reasons:
        console.print(f"[bold]Reasons:[/bold] {' | '.join(match.reasons[:4])}")
    if match.red_flags:
        console.print(f"[bold]Red flags:[/bold] {' | '.join(match.red_flags[:4])}")
    console.print(f"[bold]Expansion:[/bold] {job.expansion_audit or 'not recorded'}")
    if job.criteria_text:
        console.print(f"[bold]Criteria excerpt:[/bold] {job.criteria_text[:700]}")
    if tracker is not None:
        note = duplicate_note_for_job(tracker, job)
        if note:
            console.print(f"[yellow]Possible duplicate:[/yellow] {note}")


def process_job_url(
    page,
    url: str,
    tracker: JobTracker,
    profile,
    collector: JobCollector,
    matcher: JobMatcher,
    filler: FormFiller,
    auto_submit_safe: bool,
    force_fill: bool = False,
    config=None,
    non_interactive: bool = False,
) -> None:
    job = collector.collect(page, url)
    existing_applied = tracker.is_already_applied(job)
    if existing_applied:
        console.print(
            f"[green]Already applied:[/green] {existing_applied['title'] or job.title or job.url} "
            f"({existing_applied['applied_at'] or 'date not recorded'})"
        )
        return

    match = matcher.score(job)
    print_match_summary(job, match, tracker)

    if not force_fill and (match.score < 50 or match.decision == "skip"):
        tracker.upsert_job(job, match, status="skipped", reason=match.decision)
        return

    fill_and_review(page, job, match, tracker, profile, collector, matcher, filler, auto_submit_safe, config=config, non_interactive=non_interactive)


def fill_and_review(
    page,
    job: JobPosting,
    match: MatchResult,
    tracker: JobTracker,
    profile,
    collector: JobCollector,
    matcher: JobMatcher,
    filler: FormFiller,
    auto_submit_safe: bool,
    config=None,
    non_interactive: bool = False,
) -> None:
    """Fill a job's application (following a company-website click-through/login if that's the
    apply path) and prompt for the apply/skip/edit/save decision. Never auto-submits company-site
    applications regardless of auto_submit_safe (enforced inside append_company_site_context).

    When non_interactive=True the prompt is skipped and the job is saved as
    filled_pending_submit automatically so the pipeline can continue unattended.
    """
    if not is_india_location(job.location, job.url, job.source):
        logger.info("fill_and_review: skipping non-India job | %s | %s", job.company, job.location)
        tracker.upsert_job(job, match, status="skipped", reason="Location outside India (Mandate: India only)")
        return

    apply_path = detect_apply_path(page)
    fill_result = None
    application_page = page
    if apply_path == "company website":
        job, fill_result, application_page = append_company_site_context(
            page,
            collector,
            job,
            apply_path,
            noise_output_dir=config.exports_dir if config else None,
            filler=filler,
            config=config,
            profile=profile,
            match=match,
            auto_submit_safe=auto_submit_safe,
        )
    if fill_result is None:
        fill_result, application_page = filler.fill(
            page=page,
            job=job,
            match=match,
            profile=profile,
            auto_submit_safe=auto_submit_safe,
        )

    if fill_result.status == "applied":
        reason = "auto-submit-safe" if fill_result.auto_submitted else "already applied on job board"
        tracker.upsert_job(job, match, status="applied", reason=reason)
        console.print(f"[green]Job recorded as applied: {reason}[/green]")
        return

    if fill_result.status == "failed":
        reason = ", ".join(fill_result.errors) or "Application failed"
        tracker.upsert_job(job, match, status="failed", reason=reason)
        console.print(f"[red]Application failed:[/red] {reason}")
        return

    if fill_result.status == "needs_manual_input":
        tracker.upsert_job(
            job,
            match,
            status="needs_manual_input",
            reason=", ".join(fill_result.submit_blockers or fill_result.unknown_questions),
            notes="Manual review required.",
        )
        console.print("[yellow]Manual input is required before continuing.[/yellow]")
        return

    # ── Non-interactive path: save silently and continue the pipeline ────────
    if non_interactive:
        tracker.upsert_job(
            job,
            match,
            status="filled_pending_submit",
            reason="autorun: filled and saved for manual review before submit.",
        )
        console.print(
            f"[cyan]autorun:[/cyan] saved [bold]{job.title or job.url}[/bold] "
            f"as filled_pending_submit — open browser to review and submit."
        )
        if application_page is not page:
            try:
                if not application_page.is_closed():
                    application_page.close()
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
        return

    try:
        while True:
            choice = typer.prompt("Decision [apply/skip/edit/save]", default="save").strip().lower()
            if choice not in {"apply", "skip", "edit", "save"}:
                console.print("Choose one of: apply, skip, edit, save")
                continue

            if choice == "edit":
                console.print("Make any manual edits in the browser, then return here.")
                input("Press Enter when ready...")
                continue

            if choice == "skip":
                tracker.upsert_job(job, match, status="skipped", reason="User skipped after review.")
                return

            if choice == "save":
                tracker.upsert_job(job, match, status="filled_pending_submit", reason="Saved before final submit.")
                return

            submitted, message = filler.submit_final(application_page, explicit_confirmation=True)
            if submitted:
                tracker.upsert_job(job, match, status="applied", reason=message)
            else:
                tracker.upsert_job(job, match, status="failed", reason=message)
            console.print(message)
            return
    finally:
        # Close the company-site tab once the decision is final (not during "edit",
        # since that loops back for more manual interaction on it). Keeps tabs from
        # piling up across a multi-job queue/apply-shortlist run.
        if application_page is not page:
            try:
                if not application_page.is_closed():
                    application_page.close()
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass


def expand_queue_urls(browser: BrowserSession, collector: JobCollector, profile, seed_urls: list[str]) -> list[str]:
    discovered_urls: list[str] = []
    for seed_url in seed_urls:
        if skip_linkedin_non_job_content_url(collector, seed_url):
            continue
        page = browser.goto(seed_url)
        if skip_linkedin_non_job_content_url(collector, page.url):
            continue
        if collector.is_listing_seed_url(page.url) and collector.page_needs_manual_login(page):
            console.print(f"Manual login required for {page.url}")
            console.print("Complete the login in the browser, including any Google sign-in flow, then return here.")
            browser.wait_for_manual_step("Queue discovery is paused for manual login.")
            page = browser.goto(seed_url)
            if skip_linkedin_non_job_content_url(collector, page.url):
                continue

        if collector.is_listing_seed_url(page.url):
            batch = collector.discover_job_urls(page, profile.target_roles)
            if batch:
                console.print(f"Discovered {len(batch)} job URLs from {page.url}")
                discovered_urls.extend(batch)
            else:
                console.print(f"No matching job URLs were discovered from {page.url}")
            continue

        discovered_urls.append(page.url)

    return unique_list(discovered_urls)


@app.command()
def init() -> None:
    """Prepare directories, .env, and the SQLite tracker."""
    config = load_config()
    ensure_runtime_layout(config)
    logger = setup_logger(config.log_path, config.log_level)
    tracker = JobTracker(config.db_path, logger)
    tracker.init_db()
    console.print(f"Initialized project at {config.project_root}")
    console.print(f"SQLite database: {config.db_path}")
    console.print(f"Log file: {config.log_path}")


@app.command()
def open(
    url: list[str] = typer.Option(
        None,
        "--url",
        help="URL to open. Repeat the option to open multiple tabs.",
    ),
    clear_session: bool = typer.Option(
        False,
        "--clear-session",
        help="Delete the persistent Playwright browser profile before opening tabs.",
    ),
) -> None:
    """Open the persistent browser profile for manual login."""
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    targets = url or ["https://www.linkedin.com/jobs/", "https://www.naukri.com/"]

    if clear_session:
        BrowserSession.clear_profile_dir(config.browser_profile_dir, logger)
        console.print(f"Cleared browser session at {config.browser_profile_dir}")

    with BrowserSession(config, logger, headless=False) as browser:
        browser.open_tabs(targets)
        console.print("Browser opened with the persistent profile.")
        console.print("Log in manually to Naukri, LinkedIn, and company portals as needed.")
        console.print("Close the browser window when you are done.")
        browser.wait_until_browser_closed()


@app.command()
def workbench(
    keyword_count: int = typer.Option(4, min=1, help="Number of keyword groups to open."),
    linkedin_jobs: bool = typer.Option(
        True,
        "--linkedin-jobs/--no-linkedin-jobs",
        help="Include LinkedIn Jobs-tab search URLs.",
    ),
    fresh_only: bool = typer.Option(
        False,
        "--fresh-only/--all-dates",
        help="Add recent-job filters where supported by the source.",
    ),
    fresh_days: int = typer.Option(15, min=1, max=30, help="Freshness window in days for --fresh-only."),
) -> None:
    """Open the job-search workbench for Naukri, LinkedIn Jobs, and LinkedIn posts/content search."""
    config, logger, tracker, profile, _, _, filler, _ = build_runtime()
    pending = tracker.list_jobs(limit=10, status="filled_pending_submit")
    search_keywords = build_search_keywords(profile)
    search_urls = build_search_urls(
        search_keywords[:keyword_count],
        include_linkedin_jobs=linkedin_jobs,
        fresh_only=fresh_only,
        fresh_days=fresh_days,
    )
    urls = ["https://www.naukri.com/"]
    if linkedin_jobs:
        urls.append("https://www.linkedin.com/jobs/")
    urls += search_urls[:8]
    urls.extend(row["url"] for row in pending[:3] if row.get("url", "").startswith("http"))

    console.print(f"Browser: {config.browser_engine} | Profile: {config.browser_profile_dir}")
    console.print(
        f"Local AI: {filler.ollama_client.model}"
        + (f" -> {', '.join(filler.ollama_client.fallback_models)}" if filler.ollama_client.fallback_models else "")
    )
    if pending:
        console.print(f"Pending review jobs opened: {len(pending[:3])}")

    with BrowserSession(config, logger, headless=False) as browser:
        browser.open_tabs(urls)
        console.print("Workbench opened. Review/login/search in Firefox, then close the browser when finished.")
        browser.wait_until_browser_closed()


@app.command(name="generate-searches")
def generate_searches(
    output: Path = typer.Option(Path("jobs/generated_search_urls.txt"), help="Output file for generated search URLs."),
    keyword_count: int = typer.Option(len(BASE_SEARCH_KEYWORDS), min=1, help="Number of keyword groups."),
    linkedin_jobs: bool = typer.Option(
        True,
        "--linkedin-jobs/--no-linkedin-jobs",
        help="Include LinkedIn Jobs-tab search URLs.",
    ),
    fresh_only: bool = typer.Option(
        False,
        "--fresh-only/--all-dates",
        help="Add recent-job filters where supported by the source.",
    ),
    fresh_days: int = typer.Option(15, min=1, max=30, help="Freshness window in days for --fresh-only."),
) -> None:
    """Write broad Naukri, LinkedIn Jobs, and LinkedIn posts/content search URLs."""
    config = load_config()
    profile = load_profile(config.profile_path)
    keywords = build_search_keywords(profile)
    urls = build_search_urls(
        keywords[:keyword_count],
        include_linkedin_jobs=linkedin_jobs,
        fresh_only=fresh_only,
        fresh_days=fresh_days,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(urls) + "\n", encoding="utf-8")
    console.print(f"Wrote {len(urls)} search URLs to {output}")


@app.command(name="profile-audit")
def profile_audit() -> None:
    """Write a resume-to-profile alignment report with stronger search keywords."""
    config = load_config()
    profile = load_profile(config.profile_path)
    output = write_profile_audit(profile, config.profile_path, config.exports_dir)
    console.print(f"[green]Profile audit written:[/green] {output}")


@app.command(name="create-search-alerts")
def create_search_alerts(
    query_count: int = typer.Option(15, min=1, max=25, help="Number of top profile-driven queries to use."),
    linkedin: bool = typer.Option(True, "--linkedin/--no-linkedin", help="Attempt LinkedIn job alerts."),
    naukri: bool = typer.Option(True, "--naukri/--no-naukri", help="Attempt Naukri job alerts."),
) -> None:
    """Prepare search-alert inputs and try to create job alerts in saved browser sessions."""
    config, logger, _, profile, collector, _, _, _ = build_runtime()
    keywords = build_search_keywords(profile)[:query_count]
    queries_path, urls_path = write_search_alert_inputs(keywords, config.jobs_dir)
    rows: list[dict] = []

    with BrowserSession(config, logger, headless=False) as browser:
        for keyword in keywords:
            if naukri:
                url = naukri_search_url(keyword)
                page, error = open_alert_page(browser, url)
                if not page:
                    status = f"open failed: {error}"
                    rows.append({"keyword": keyword, "source": "naukri", "status": status, "url": url})
                    console.print(f"Naukri alert | {keyword} | {status}")
                else:
                    if collector.page_needs_manual_login(page):
                        console.print(f"[yellow]Naukri login required:[/yellow] {page.url}")
                        browser.wait_for_manual_step("Complete Naukri login in Firefox, then press Enter to continue.")
                        page, error = open_alert_page(browser, url)
                        if not page:
                            status = f"open failed after login: {error}"
                            rows.append({"keyword": keyword, "source": "naukri", "status": status, "url": url})
                            console.print(f"Naukri alert | {keyword} | {status}")
                            page = None
                    if page:
                        status = create_naukri_alert(page, keyword)
                        rows.append({"keyword": keyword, "source": "naukri", "status": status, "url": page.url})
                        console.print(f"Naukri alert | {keyword} | {status}")

            if linkedin:
                url = linkedin_search_url(keyword)
                page, error = open_alert_page(browser, url)
                if not page:
                    status = f"open failed: {error}"
                    rows.append({"keyword": keyword, "source": "linkedin", "status": status, "url": url})
                    console.print(f"LinkedIn alert | {keyword} | {status}")
                else:
                    if collector.page_needs_manual_login(page):
                        console.print(f"[yellow]LinkedIn login required:[/yellow] {page.url}")
                        browser.wait_for_manual_step("Complete LinkedIn login in Firefox, then press Enter to continue.")
                        page, error = open_alert_page(browser, url)
                        if not page:
                            status = f"open failed after login: {error}"
                            rows.append({"keyword": keyword, "source": "linkedin", "status": status, "url": url})
                            console.print(f"LinkedIn alert | {keyword} | {status}")
                            page = None
                    if page:
                        status = create_linkedin_alert(page)
                        rows.append({"keyword": keyword, "source": "linkedin", "status": status, "url": page.url})
                        console.print(f"LinkedIn alert | {keyword} | {status}")

    report = write_search_alert_report(rows, config.exports_dir)
    console.print(f"[green]Alert queries written:[/green] {queries_path}")
    console.print(f"[green]Alert URLs written:[/green] {urls_path}")
    console.print(f"[green]Alert report written:[/green] {report}")


@app.command()
def scout(
    keyword_count: int = typer.Option(6, min=1, help="Number of keyword groups to search."),
    max_per_search: int = typer.Option(8, min=1, max=25, help="Maximum job detail URLs to collect from each search page."),
    limit: int = typer.Option(25, min=1, max=100, help="Maximum discovered jobs to inspect in detail."),
    min_score: int = typer.Option(50, min=0, max=100, help="Minimum score to shortlist."),
    open_top: int = typer.Option(0, min=0, max=15, help="Open this many shortlisted jobs for review after scouting."),
    linkedin_posts: bool = typer.Option(
        True,
        "--linkedin-posts/--no-linkedin-posts",
        help="Also scan LinkedIn content search for recent hiring posts and application links.",
    ),
    linkedin_jobs: bool = typer.Option(
        True,
        "--linkedin-jobs/--no-linkedin-jobs",
        help="Also search the LinkedIn Jobs tab.",
    ),
    fresh_only: bool = typer.Option(
        False,
        "--fresh-only/--all-dates",
        help="Add recent-job filters to Naukri and LinkedIn Jobs searches where supported.",
    ),
    fresh_days: int = typer.Option(15, min=1, max=30, help="Freshness window in days for --fresh-only."),
    skip_seen_companies: bool = typer.Option(
        True,
        "--skip-seen-companies/--no-skip-seen-companies",
        help="Skip companies already reviewed for the same source and search keyword.",
    ),
    skip_checked_pages: bool = typer.Option(
        True,
        "--skip-checked-pages/--no-skip-checked-pages",
        help="Skip result pages already fully processed for the same source and search keyword.",
    ),
    max_pages_per_search: int = typer.Option(
        1,
        min=1,
        max=5,
        help="Number of unchecked result pages to process for each source/search keyword.",
    ),
    auto_fill: bool = typer.Option(
        False,
        "--auto-fill/--no-auto-fill",
        help="Immediately fill (and pause for apply/skip/edit/save) each job that clears the shortlist "
        "threshold, instead of only recording it for a later apply-shortlist run. Never auto-submits.",
    ),
    keyword_offset: int = typer.Option(0, min=0, help="Starting index in the search keyword list."),
    prioritize_unsearched: bool = typer.Option(
        True,
        "--prioritize-unsearched/--no-prioritize-unsearched",
        help="Place unsearched keywords first to ensure complete coverage.",
    ),
) -> None:
    """Search, read job details, score, and write a shortlist before applying."""
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    search_keywords = build_search_keywords(profile)
    if prioritize_unsearched:
        search_keywords = prioritize_unsearched_keywords(search_keywords, tracker)
    selected_keywords = search_keywords[keyword_offset : keyword_offset + keyword_count]
    search_urls = build_search_urls(
        selected_keywords,
        include_posts=linkedin_posts,
        include_jobs=True,
        include_linkedin_jobs=linkedin_jobs,
        fresh_only=fresh_only,
        fresh_days=fresh_days,
    )
    discovered: list[str] = []
    discovered_meta: dict[str, dict[str, str]] = {}
    page_progress: dict[str, dict[str, int | str]] = {}
    rows: list[dict] = []

    with BrowserSession(config, logger, headless=config.headless) as browser:
        for seed_url in search_urls:
            try:
                page = browser.goto(seed_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping search seed after navigation failure | url=%s | error=%s", seed_url, exc)
                console.print(f"[yellow]Skipped search seed after navigation failure:[/yellow] {seed_url}")
                continue
            scanned_pages = 0
            page_hops = 0
            while scanned_pages < max_pages_per_search and len(discovered) < limit:
                if collector.page_needs_manual_login(page):
                    console.print(f"[yellow]Login required:[/yellow] {page.url}")
                    browser.wait_for_manual_step("Complete login in Firefox, then press Enter here to continue scouting.")
                    try:
                        page = browser.goto(page.url or seed_url)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Skipping search seed after post-login navigation failure | url=%s | error=%s", seed_url, exc)
                        console.print(f"[yellow]Skipped search seed after login/navigation failure:[/yellow] {seed_url}")
                        break

                page_url = page.url or seed_url
                search_source = detect_source_from_url(page_url)
                search_key = search_key_from_url(page_url)

                if skip_checked_pages and tracker.has_checked_search_page(search_source, search_key, page_url):
                    console.print(f"Skipping checked result page: {page_url}")
                    page_hops += 1
                    if page_hops > max_pages_per_search + 8 or not collector.advance_listing_page(page):
                        break
                    continue

                scan_limit = max_per_search * 3
                candidates = collector.discover_job_candidates(page, profile.target_roles, max_results=scan_limit)
                selected: list[dict[str, str]] = []
                skipped_seen = 0
                skipped_handled = 0
                skipped_noise = 0
                for candidate in candidates:
                    company = candidate.get("company", "")
                    candidate_url = candidate.get("url", "")
                    if collector.is_blocked_application_url(candidate_url) or collector.is_non_job_content_url(candidate_url):
                        skipped_noise += 1
                        logger.info("Dropping blocked/social/non-job candidate URL: %s", candidate_url)
                        note_noise_link_once(
                            config.exports_dir,
                            candidate_url,
                            search_source,
                            "blocked/social/non-job candidate from search results",
                            page_url,
                        )
                        continue
                    handled = tracker.find_handled_job(
                        JobPosting(
                            source=detect_source_from_url(candidate_url),
                            company=company,
                            title=candidate.get("title", ""),
                            url=candidate_url,
                        )
                    )
                    if handled:
                        skipped_handled += 1
                        rows.append(
                            {
                                "score": handled.get("score") or 0,
                                "decision": "already handled",
                                "status": handled.get("status") or "skipped",
                                "apply_path": "already handled",
                                "source": handled.get("source") or search_source,
                                "company": handled.get("company") or company,
                                "title": handled.get("title") or candidate.get("title", ""),
                                "location": "",
                                "experience": "",
                                "matched_skills": "",
                                "red_flags": "",
                                "skip_reason": f"already {handled.get('status') or 'saved'} in tracker",
                                "contact_methods": "",
                                "expansion_audit": "",
                                "criteria_excerpt": "",
                                "url": handled.get("url") or candidate_url,
                            }
                        )
                        save_live_shortlist(rows, config.exports_dir)
                        continue
                    already_seen_company = (
                        skip_seen_companies
                        and company
                        and (
                            tracker.has_seen_company_for_search(search_source, search_key, company)
                            or tracker.has_seen_company_for_source(search_source, company)
                        )
                    )
                    if already_seen_company:
                        skipped_seen += 1
                        rows.append(
                            {
                                "score": 0,
                                "decision": "skip",
                                "status": "skipped_seen_company",
                                "apply_path": "not opened",
                                "source": search_source,
                                "company": company,
                                "title": candidate.get("title", ""),
                                "location": "",
                                "experience": "",
                                "matched_skills": "",
                                "red_flags": "",
                                "skip_reason": f"already reviewed company on {search_source}",
                                "contact_methods": "",
                                "expansion_audit": "",
                                "criteria_excerpt": "",
                                "url": candidate.get("url", ""),
                            }
                        )
                        save_live_shortlist(rows, config.exports_dir)
                        continue
                    selected.append(candidate)
                    if len(selected) >= max_per_search:
                        break

                batch: list[str] = []
                page_limited_by_run_limit = False
                for candidate in selected:
                    url = candidate.get("url", "")
                    if not url or url in discovered or url in batch:
                        continue
                    if len(discovered) + len(batch) >= limit:
                        page_limited_by_run_limit = True
                        break
                    batch.append(url)
                    discovered_meta[url] = {
                        "search_source": search_source,
                        "search_key": search_key,
                        "search_page_url": page_url,
                        "company": candidate.get("company", ""),
                        "title": candidate.get("title", ""),
                    }
                if len(discovered) + len(batch) >= limit and len(batch) < len(selected):
                    page_limited_by_run_limit = True

                tracker.mark_search_page(
                    search_source,
                    search_key,
                    page_url,
                    status="discovered" if batch else "checked",
                    candidates_found=len(candidates),
                    selected_count=len(batch),
                    skipped_seen_count=skipped_seen + skipped_handled,
                )
                if batch:
                    page_progress[page_url] = {
                        "source": search_source,
                        "search_key": search_key,
                        "expected": len(batch),
                        "processed": 0,
                        "candidates_found": len(candidates),
                        "selected_count": len(batch),
                        "skipped_seen_count": skipped_seen + skipped_handled,
                        "can_mark_checked": not page_limited_by_run_limit,
                    }

                console.print(
                    f"Found {len(batch)} new links from {page_url}"
                    + (f" | skipped {skipped_seen} previously seen companies" if skipped_seen else "")
                    + (f" | skipped {skipped_handled} already handled jobs" if skipped_handled else "")
                    + (f" | dropped {skipped_noise} blocked/social links" if skipped_noise else "")
                )
                discovered.extend(batch)
                discovered = unique_list(discovered)
                scanned_pages += 1
                if len(discovered) >= limit or scanned_pages >= max_pages_per_search:
                    break
                if not collector.advance_listing_page(page):
                    break
            if len(discovered) >= limit:
                break

        shortlisted_urls: list[str] = []
        browser_retry_counts: dict[str, int] = {}
        def mark_candidate_processed(candidate_url: str) -> None:
            meta = discovered_meta.get(candidate_url, {})
            page_url = meta.get("search_page_url", "")
            if not page_url or page_url not in page_progress:
                return
            state = page_progress[page_url]
            state["processed"] = int(state.get("processed", 0)) + 1
            if int(state.get("processed", 0)) >= int(state.get("expected", 0)):
                if not bool(state.get("can_mark_checked", True)):
                    return
                tracker.mark_search_page(
                    str(state.get("source", "")),
                    str(state.get("search_key", "")),
                    page_url,
                    status="checked",
                    candidates_found=int(state.get("candidates_found", 0)),
                    selected_count=int(state.get("selected_count", 0)),
                    skipped_seen_count=int(state.get("skipped_seen_count", 0)),
                )

        for index, url in enumerate(discovered, start=1):
            console.rule(f"Inspecting {index}/{len(discovered)}")
            requeued_after_browser_restart = False
            page = None
            try:
                if collector.is_blocked_application_url(url) or collector.is_non_job_content_url(url):
                    note_noise_link_once(
                        config.exports_dir,
                        url,
                        detect_source_from_url(url),
                        "blocked/social/non-job URL reached inspection queue",
                    )
                    rows.append(
                        {
                            "score": 0,
                            "decision": "skip",
                            "status": "skipped",
                            "apply_path": "blocked/non-job page",
                            "source": detect_source_from_url(url),
                            "company": "",
                            "title": "Blocked social/report/non-job page",
                            "location": "",
                            "experience": "",
                            "matched_skills": "",
                            "red_flags": "blocked social/report/non-job content page",
                            "skip_reason": "not a direct job or application page",
                            "contact_methods": "",
                            "expansion_audit": "",
                            "criteria_excerpt": "",
                            "url": url,
                        }
                    )
                    save_live_shortlist(rows, config.exports_dir)
                    console.print(f"[yellow]Skipped blocked/non-job page:[/yellow] {url}")
                    continue
                page = browser.current_page()
                job = collector.collect(page, url)
                actionability_audit = collector.expand_for_actionability_check(page)
                job = collector.refresh_current_page_job(page, job, actionability_audit)
                meta = discovered_meta.get(url, {})
                search_source = meta.get("search_source") or job.source
                search_key = meta.get("search_key") or "manual"
                company_for_memory = job.company or meta.get("company", "")
                existing_applied = tracker.is_already_applied(job)
                if existing_applied:
                    tracker.mark_company_seen_for_search(
                        search_source,
                        search_key,
                        existing_applied.get("company") or company_for_memory,
                        existing_applied.get("title") or job.title or meta.get("title", ""),
                        existing_applied.get("url") or job.url,
                        "applied",
                    )
                    console.print(f"[green]Already applied, skipping:[/green] {existing_applied['title'] or job.url}")
                    rows.append(
                        {
                            "score": existing_applied.get("score") or "",
                            "decision": "already applied",
                            "status": "applied",
                            "apply_path": "already applied",
                            "source": job.source,
                            "company": existing_applied.get("company") or job.company,
                            "title": existing_applied.get("title") or job.title,
                            "location": job.location,
                            "experience": job.experience,
                            "matched_skills": "",
                            "red_flags": "",
                            "skip_reason": "already applied",
                            "contact_methods": "",
                            "expansion_audit": job.expansion_audit,
                            "criteria_excerpt": (job.criteria_text or job.description or "")[:500],
                            "url": existing_applied.get("url") or job.url,
                        }
                    )
                    save_live_shortlist(rows, config.exports_dir)
                    continue

                apply_path = detect_apply_path(page)
                if apply_path == "already applied":
                    match = MatchResult(score=0, decision="already applied")
                    tracker.upsert_job(job, match, status="applied", reason="Site shows already applied.")
                    tracker.mark_company_seen_for_search(
                        search_source,
                        search_key,
                        job.company or meta.get("company", ""),
                        job.title or meta.get("title", ""),
                        job.url,
                        "applied",
                    )
                    rows.append(
                        {
                            "score": 0,
                            "decision": "already applied",
                            "status": "applied",
                            "apply_path": apply_path,
                            "source": job.source,
                            "company": job.company,
                            "title": job.title,
                            "location": job.location,
                            "experience": job.experience,
                            "matched_skills": "",
                            "red_flags": "",
                            "skip_reason": "site shows already applied",
                            "contact_methods": "",
                            "expansion_audit": job.expansion_audit,
                            "criteria_excerpt": (job.criteria_text or job.description or "")[:500],
                            "url": job.url,
                        }
                    )
                    save_live_shortlist(rows, config.exports_dir)
                    console.print(f"[green]Already applied on site:[/green] {job.title or job.url}")
                    continue
                job, _, _ = append_company_site_context(page, collector, job, apply_path, config.exports_dir)
                contact_methods = find_contact_methods(
                    " ".join([job.raw_text, job.criteria_text, job.description, job.application_url, job.url])
                )
                if not has_actionable_apply_or_contact(apply_path, contact_methods):
                    match = MatchResult(score=0, decision="skip")
                    status = "skipped"
                    skip_reason = "no apply button, company application link, email, or phone found"
                    tracker.upsert_job(job, match, status=status, reason=skip_reason)
                    tracker.mark_company_seen_for_search(
                        search_source,
                        search_key,
                        job.company or meta.get("company", ""),
                        job.title or meta.get("title", ""),
                        job.url,
                        status,
                    )
                    rows.append(
                        {
                            "score": 0,
                            "decision": "skip",
                            "status": status,
                            "apply_path": apply_path,
                            "source": job.source,
                            "company": job.company,
                            "title": job.title,
                            "location": job.location,
                            "experience": job.experience,
                            "matched_skills": "",
                            "red_flags": "",
                            "skip_reason": skip_reason,
                            "contact_methods": "",
                            "expansion_audit": job.expansion_audit,
                            "criteria_excerpt": (job.criteria_text or job.description or "")[:500],
                            "url": job.url,
                        }
                    )
                    save_live_shortlist(rows, config.exports_dir)
                    console.print(f"skipped: {job.title or 'Unknown'} | {skip_reason}")
                    continue

                match = matcher.score(job)
                is_support_fallback = match.decision == TECHNICAL_SUPPORT_FALLBACK_DECISION
                status = "shortlisted" if (
                    is_support_fallback or (match.score >= min_score and match.decision != "skip")
                ) else "skipped"
                skip_reason = skip_reason_for_match(match, status, apply_path)
                reason = skip_reason if status == "skipped" else f"{match.decision}; {apply_path}"
                duplicate_note = duplicate_note_for_job(tracker, job)
                tracker.upsert_job(job, match, status=status, reason=reason)
                tracker.mark_company_seen_for_search(
                    search_source,
                    search_key,
                    job.company or meta.get("company", ""),
                    job.title or meta.get("title", ""),
                    job.url,
                    status,
                )
                if status == "shortlisted":
                    shortlisted_urls.append(job.url)
                rows.append(
                    {
                        "score": match.score,
                        "decision": match.decision,
                        "status": status,
                        "apply_path": apply_path,
                        "source": job.source,
                        "company": job.company,
                        "title": job.title,
                        "location": job.location,
                        "experience": job.experience,
                        "matched_skills": ", ".join(match.matched_skills),
                        "red_flags": ", ".join(match.red_flags),
                        "skip_reason": skip_reason,
                        "contact_methods": ", ".join(contact_methods),
                        "expansion_audit": job.expansion_audit,
                        "criteria_excerpt": (job.criteria_text or job.description or "")[:500],
                        "possible_duplicate": duplicate_note,
                        "url": job.url,
                    }
                )
                save_live_shortlist(rows, config.exports_dir)
                console.print(f"{status}: {job.title or 'Unknown'} | score={match.score} | {apply_path}")
                if duplicate_note:
                    console.print(f"[yellow]Possible duplicate:[/yellow] {duplicate_note}")
                if auto_fill and status == "shortlisted":
                    fill_and_review(page, job, match, tracker, profile, collector, matcher, filler, auto_submit_safe=False, config=config)
            except Exception as exc:  # noqa: BLE001
                if is_browser_closed_error(exc) and browser_retry_counts.get(url, 0) < 1:
                    browser_retry_counts[url] = browser_retry_counts.get(url, 0) + 1
                    logger.warning("Browser closed during inspection; restarting and re-queueing current URL | url=%s", url)
                    console.print(f"[yellow]Browser closed during inspection. Restarting Chrome and retrying once:[/yellow] {url}")
                    try:
                        browser.restart()
                        discovered.append(url)
                        requeued_after_browser_restart = True
                    except Exception as restart_exc:  # noqa: BLE001
                        logger.exception("Browser restart failed after closure.")
                        console.print(f"[red]Browser restart failed:[/red] {restart_exc}")
                    if requeued_after_browser_restart:
                        continue
                logger.exception("Scouting failed for %s", url)
                console.print(f"[red]Failed to inspect:[/red] {url} -> {exc}")
            finally:
                if not requeued_after_browser_restart:
                    mark_candidate_processed(url)
                    try:
                        browser.close_extra_tabs(keep=page)
                    except Exception as cleanup_exc:  # noqa: BLE001
                        logger.debug("Unable to clean up browser tabs after inspecting %s: %s", url, cleanup_exc)

        rows.sort(key=lambda item: int(item["score"] or 0), reverse=True)
        csv_path, md_path = write_shortlist_report(rows, config.exports_dir)
        console.print(f"[green]Shortlist written:[/green] {md_path}")
        console.print(f"[green]Review shortlist written:[/green] {config.exports_dir / 'shortlist_review_latest.md'}")
        console.print(f"[green]CSV written:[/green] {csv_path}")

        if open_top and shortlisted_urls:
            top_urls = [row["url"] for row in rows if row["status"] == "shortlisted"][:open_top]
            browser.open_tabs(top_urls)
            console.print(f"Opened top {len(top_urls)} shortlisted jobs. Close Firefox when finished.")
            browser.wait_until_browser_closed()


@app.command(name="apply-shortlist")
def apply_shortlist(
    limit: int = typer.Option(25, min=1, max=100, help="Maximum shortlisted jobs to process."),
    auto_submit: bool = typer.Option(True, "--auto-submit/--no-auto-submit", help="Auto-submit safe applications."),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser headless."),
    non_interactive: bool = typer.Option(True, "--non-interactive/--interactive", help="Run non-interactively without prompt pauses."),
) -> None:
    """Open shortlisted jobs, fill safe fields, and apply."""
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    rows = tracker.list_jobs(limit=limit, status="shortlisted", order_by_score=True)
    if not rows:
        console.print("No shortlisted jobs found. Run scout first.")
        return

    with BrowserSession(config, logger, headless=headless) as browser:
        for index, row in enumerate(rows, start=1):
            console.rule(f"Applying {index}/{len(rows)}")
            try:
                process_job_url(
                    page=browser.current_page(),
                    url=row["url"],
                    tracker=tracker,
                    profile=profile,
                    collector=collector,
                    matcher=matcher,
                    filler=filler,
                    auto_submit_safe=auto_submit,
                    config=config,
                    non_interactive=non_interactive,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Application failed for %s: %s", row.get("url"), exc)
                console.print(f"[red]Failed to apply to {row.get('url')}:[/red] {exc}")
                tracker.upsert_job(
                    JobPosting(source=row.get("source") or "unknown", url=row["url"], title=row.get("title") or "", company=row.get("company") or ""),
                    MatchResult(score=int(row.get("score") or 0), decision="apply error"),
                    status="error",
                    reason=f"Navigation or apply error: {exc}",
                )
            finally:
                try:
                    browser.close_extra_tabs()
                except Exception:  # noqa: BLE001
                    pass


@app.command(name="submit")
def submit(
    statuses: str = typer.Option("filled_pending_submit,shortlisted", help="Comma-separated job statuses to submit."),
    limit: int = typer.Option(20, min=1, max=500, help="Maximum applications to submit."),
    headless: bool = typer.Option(False, "--headless/--headful", help="Run browser headless or headful."),
    auto_submit: bool = typer.Option(True, "--auto-submit/--no-auto-submit", help="Submit automatically when form is complete."),
    warmup: bool = typer.Option(True, "--warmup/--no-warmup", help="Warm up sessions on LinkedIn and Naukri before submitting."),
    profile_name: str = typer.Option("default", "--profile", "-p", help="Persona profile to use (e.g. vapt, appsec, soc, backend, default)."),
) -> None:
    """Submit queued applications via the unified framework pipeline."""
    from app.pipeline import run_submission_batch
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime(profile_name=profile_name)
    filler.non_interactive = True
    status_list = tuple(s.strip() for s in statuses.split(",") if s.strip())
    stats = run_submission_batch(
        config=config,
        tracker=tracker,
        filler=filler,
        collector=collector,
        profile=profile,
        matcher=matcher,
        statuses=status_list,
        limit=limit,
        headless=headless,
        auto_submit_safe=auto_submit,
        warm_up=warmup,
    )
    console.print(f"[bold green]Batch submission complete:[/bold green] {stats}")


@app.command(name="resume-manual")
def resume_manual(
    limit: int = typer.Option(10, min=1, max=50, help="Maximum manual-input jobs to resume."),
    status: str = typer.Option(
        "needs_manual_input",
        help="Tracker status to resume. Use filled_pending_submit to revisit saved forms.",
    ),
    headless: bool = typer.Option(False, "--headless/--no-headless", help="Run browser in headless mode."),
    auto_submit: bool = typer.Option(False, "--auto-submit/--no-auto-submit", help="Attempt safe auto-submission for eligible forms."),
    non_interactive: bool = typer.Option(False, "--non-interactive/--interactive", help="Run non-interactively without pause prompts."),
) -> None:
    """Resume jobs that previously stopped for CAPTCHA, OTP, or unknown questions."""
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    rows = tracker.list_jobs(limit=limit, status=status, order_by_score=True)
    if not rows:
        console.print(f"No jobs found with status: {status}")
        return

    with BrowserSession(config, logger, headless=headless) as browser:
        for index, row in enumerate(rows, start=1):
            console.rule(f"Resuming manual job {index}/{len(rows)}")
            console.print(f"[bold]Job:[/bold] {row.get('title') or 'Unknown title'}")
            console.print(f"[bold]Company:[/bold] {row.get('company') or 'Unknown company'}")
            console.print(f"[bold]Status:[/bold] {row.get('status') or status}")
            if row.get("reason"):
                console.print(f"[bold]Previous blocker:[/bold] {row['reason']}")
            console.print(f"[bold]URL:[/bold] {row['url']}")
            try:
                process_job_url(
                    page=browser.current_page(),
                    url=row["url"],
                    tracker=tracker,
                    profile=profile,
                    collector=collector,
                    matcher=matcher,
                    filler=filler,
                    auto_submit_safe=auto_submit,
                    force_fill=True,
                    config=config,
                    non_interactive=non_interactive,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Resume manual failed for %s: %s", row.get("url"), exc)
                console.print(f"[red]Failed to resume job {row.get('url')}:[/red] {exc}")
                tracker.upsert_job(
                    JobPosting(
                        source=row.get("source") or "unknown",
                        url=row["url"],
                        title=row.get("title") or "",
                        company=row.get("company") or "",
                    ),
                    MatchResult(score=int(row.get("score") or 0), decision="resume manual error"),
                    status="error",
                    reason=f"Resume manual error: {exc}",
                )
            finally:
                try:
                    browser.close_extra_tabs()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Unable to clean up browser tabs after manual resume: %s", exc)


@app.command(name="recheck-skipped")
def recheck_skipped(
    limit: int = typer.Option(20, min=1, max=100, help="Maximum skipped jobs to re-check with deep expansion."),
    min_score: int = typer.Option(50, min=0, max=100, help="Minimum score to move back to shortlist."),
    open_top: int = typer.Option(0, min=0, max=15, help="Open this many recovered shortlisted jobs after re-check."),
) -> None:
    """Re-open skipped jobs, expand hidden criteria, and recover any good matches."""
    config, logger, tracker, profile, collector, matcher, _, _ = build_runtime()
    skipped = tracker.list_jobs(limit=limit, status="skipped")
    if not skipped:
        console.print("No skipped jobs to re-check.")
        return

    rows: list[dict] = []
    recovered: list[str] = []
    with BrowserSession(config, logger, headless=False) as browser:
        for index, row in enumerate(skipped, start=1):
            console.rule(f"Rechecking {index}/{len(skipped)}")
            url = row["url"]
            try:
                if collector.is_non_job_content_url(url):
                    console.print(f"[yellow]Skipping non-job content page:[/yellow] {url}")
                    continue
                page = browser.current_page()
                job = collector.collect(page, url)
                actionability_audit = collector.expand_for_actionability_check(page)
                job = collector.refresh_current_page_job(page, job, actionability_audit)
                existing_applied = tracker.is_already_applied(job)
                if existing_applied:
                    console.print(f"[green]Already applied, preserving:[/green] {existing_applied['title'] or url}")
                    continue
                apply_path = detect_apply_path(page)
                if apply_path == "already applied":
                    tracker.upsert_job(job, MatchResult(score=0, decision="already applied"), status="applied", reason="Site shows already applied.")
                    console.print(f"[green]Already applied on site:[/green] {job.title or url}")
                    continue
                job, _, _ = append_company_site_context(page, collector, job, apply_path, config.exports_dir)
                contact_methods = find_contact_methods(
                    " ".join([job.raw_text, job.criteria_text, job.description, job.application_url, job.url])
                )
                if not has_actionable_apply_or_contact(apply_path, contact_methods):
                    match = MatchResult(score=0, decision="skip")
                    status = "skipped"
                    skip_reason = "no apply button, company application link, email, or phone found"
                    tracker.upsert_job(job, match, status=status, reason=f"rechecked; {skip_reason}")
                    rows.append(
                        {
                            "score": 0,
                            "decision": "skip",
                            "status": status,
                            "apply_path": apply_path,
                            "source": job.source,
                            "company": job.company,
                            "title": job.title,
                            "location": job.location,
                            "experience": job.experience,
                            "matched_skills": "",
                            "red_flags": "",
                            "skip_reason": skip_reason,
                            "contact_methods": "",
                            "expansion_audit": job.expansion_audit,
                            "criteria_excerpt": (job.criteria_text or job.description or "")[:500],
                            "url": job.url,
                        }
                    )
                    save_live_shortlist(rows, config.exports_dir)
                    console.print(f"skipped: {job.title or 'Unknown'} | {skip_reason}")
                    continue
                match = matcher.score(job)
                is_support_fallback = match.decision == TECHNICAL_SUPPORT_FALLBACK_DECISION
                status = "shortlisted" if (
                    is_support_fallback or (match.score >= min_score and match.decision != "skip")
                ) else "skipped"
                skip_reason = skip_reason_for_match(match, status, apply_path)
                reason = f"rechecked after deep expansion; {skip_reason or match.decision}; {apply_path}"
                tracker.upsert_job(job, match, status=status, reason=reason)
                if status == "shortlisted":
                    recovered.append(job.url)
                rows.append(
                    {
                        "score": match.score,
                        "decision": match.decision,
                        "status": status,
                        "apply_path": apply_path,
                        "source": job.source,
                        "company": job.company,
                        "title": job.title,
                        "location": job.location,
                        "experience": job.experience,
                        "matched_skills": ", ".join(match.matched_skills),
                        "red_flags": ", ".join(match.red_flags),
                        "skip_reason": skip_reason,
                        "contact_methods": ", ".join(contact_methods),
                        "expansion_audit": job.expansion_audit,
                        "criteria_excerpt": (job.criteria_text or job.description or "")[:500],
                        "url": job.url,
                    }
                )
                save_live_shortlist(rows, config.exports_dir)
                console.print(f"{status}: {job.title or 'Unknown'} | score={match.score} | {apply_path}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Recheck failed for %s", url)
                console.print(f"[red]Failed to re-check:[/red] {url} -> {exc}")

        rows.sort(key=lambda item: int(item["score"] or 0), reverse=True)
        csv_path, md_path = write_shortlist_report(rows, config.exports_dir)
        console.print(f"[green]Recheck report written:[/green] {md_path}")
        console.print(f"[green]Review shortlist written:[/green] {config.exports_dir / 'shortlist_review_latest.md'}")
        console.print(f"[green]CSV written:[/green] {csv_path}")

        if open_top and recovered:
            top_urls = recovered[:open_top]
            browser.open_tabs(top_urls)
            console.print(f"Opened {len(top_urls)} recovered jobs. Close Firefox when finished.")
            browser.wait_until_browser_closed()


@app.command(name="mark-applied")
def mark_applied(url: str = typer.Option(..., help="Job URL to mark as applied.")) -> None:
    """Mark a job URL as applied so future runs remember it."""
    _, _, tracker, _, _, _, _, _ = build_runtime()
    job = JobPosting(source=detect_source_from_url(url), url=url)
    existing = tracker.find_existing(job)
    if existing:
        job = JobPosting(
            source=existing["source"] or detect_source_from_url(url),
            company=existing["company"] or "",
            title=existing["title"] or "",
            url=existing["url"] or url,
        )
    tracker.upsert_job(job, MatchResult(score=existing["score"] if existing else 0, decision="manual"), status="applied", reason="Marked applied by user.")
    console.print(f"Marked applied: {(existing or {}).get('title') or url}")


@app.command()
def analyze(url: str = typer.Option(..., help="Direct job posting URL.")) -> None:
    """Open a job page, extract details, score it, and store the result."""
    config, logger, tracker, profile, collector, matcher, _, _ = build_runtime()
    if skip_linkedin_non_job_content_url(collector, url):
        job = JobPosting(
            source=detect_source_from_url(url),
            title="LinkedIn content/article page",
            url=url,
        )
        tracker.upsert_job(job, MatchResult(score=0, decision="skip"), status="skipped", reason="Not a direct job page.")
        return
    with BrowserSession(config, logger, headless=False) as browser:
        page = browser.goto(url)
        if skip_linkedin_non_job_content_url(collector, page.url):
            return
        job = collector.collect(page, url)
        match = matcher.score(job)
        tracker.upsert_job(job, match, status="discovered", reason=match.decision)
        print_match_summary(job, match, tracker)


@app.command(name="inspect-job")
def inspect_job(url: str = typer.Option(..., help="Direct job posting URL to inspect deeply.")) -> None:
    """Open one job, expand details, and show the exact criteria text used for scoring."""
    config, logger, tracker, profile, collector, matcher, _, _ = build_runtime()
    if skip_linkedin_non_job_content_url(collector, url):
        job = JobPosting(
            source=detect_source_from_url(url),
            title="LinkedIn content/article page",
            url=url,
        )
        tracker.upsert_job(job, MatchResult(score=0, decision="skip"), status="skipped", reason="Not a direct job page.")
        return
    with BrowserSession(config, logger, headless=False) as browser:
        page = browser.goto(url)
        if skip_linkedin_non_job_content_url(collector, page.url):
            return
        job = collector.collect(page, url)
        apply_path = detect_apply_path(page)
        job, _, _ = append_company_site_context(page, collector, job, apply_path, config.exports_dir)
        match = matcher.score(job)
        tracker.upsert_job(job, match, status="discovered", reason=f"inspected; {match.decision}; {apply_path}")
        print_match_summary(job, match, tracker)
        output = config.exports_dir / "inspect_job_latest.md"
        output.write_text(
            "\n".join(
                [
                    f"# {job.title or 'Inspected Job'}",
                    "",
                    f"- Company: {job.company or 'Unknown'}",
                    f"- URL: {job.url}",
                    f"- Application URL: {job.application_url or '-'}",
                    f"- Apply path: {apply_path}",
                    f"- Score: {match.score}",
                    f"- Decision: {match.decision}",
                    f"- Expansion audit: {job.expansion_audit or '-'}",
                    "",
                    "## Criteria Text",
                    "",
                    job.criteria_text or job.description or job.raw_text or "No criteria text captured.",
                ]
            ),
            encoding="utf-8",
        )
        console.print(f"[green]Inspection report written:[/green] {output}")


@app.command()
def fill(
    url: str = typer.Option(..., help="Direct job posting URL."),
    force_fill: bool = typer.Option(
        False, "--force-fill", help="Skip the score/decision gate and attempt to fill this job regardless of match score."
    ),
) -> None:
    """Fill a single application and stop before final submit unless you choose apply."""
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    if skip_linkedin_non_job_content_url(collector, url):
        return
    with BrowserSession(config, logger, headless=False) as browser:
        page = browser.goto(url)
        if skip_linkedin_non_job_content_url(collector, page.url):
            return
        process_job_url(
            page, url, tracker, profile, collector, matcher, filler,
            auto_submit_safe=False, force_fill=force_fill, config=config,
        )


@app.command()
def queue(
    input: Path = typer.Option(Path("jobs/urls.txt"), exists=True, dir_okay=False, help="Text file containing job URLs."),
    auto_submit_safe: bool = typer.Option(False, help="Allow controlled safe auto-submit when all rules pass."),
) -> None:
    """Process a batch of job detail URLs or supported search/listing URLs."""
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    seed_urls = collector.read_urls(input)
    if not seed_urls:
        console.print("No job URLs found.")
        raise typer.Exit(code=1)

    with BrowserSession(config, logger, headless=False) as browser:
        urls = expand_queue_urls(browser, collector, profile, seed_urls)
        if not urls:
            console.print("No matching job detail URLs were discovered.")
            raise typer.Exit(code=1)

        for index, url in enumerate(urls, start=1):
            console.rule(f"[{index}/{len(urls)}] {url}")
            try:
                process_job_url(
                    page=browser.current_page(),
                    url=url,
                    tracker=tracker,
                    profile=profile,
                    collector=collector,
                    matcher=matcher,
                    filler=filler,
                    auto_submit_safe=auto_submit_safe,
                    config=config,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Queue processing failed for %s", url)
                tracker.upsert_job(
                    JobPosting(source="unknown", url=url),
                    MatchResult(score=0, decision="skip"),
                    status="failed",
                    reason=str(exc),
                )
                console.print(f"[red]Failed:[/red] {url} -> {exc}")


def extract_query_cluster_key(url: str) -> str:
    """Extracts a normalized query cluster key (domain + keyword + location), stripping volatile time parameters."""
    lowered = (url or "").lower()
    try:
        parsed = urlparse(lowered)
        qs = parse_qs(parsed.query)
        keywords = "".join(qs.get("k", []) or qs.get("keywords", []))
        location = "".join(qs.get("l", []) or qs.get("location", []))
        path = parsed.path.rstrip("/")
        return f"{parsed.netloc}:{path}:{keywords}:{location}"
    except Exception:
        return lowered.split("?")[0]


@app.command(name="stream-queue")
def stream_queue(
    input: Path = typer.Option(Path("jobs/urls.txt"), exists=True, dir_okay=False, help="Text file of search/listing seed URLs."),
    auto_submit_safe: bool = typer.Option(True, help="Allow controlled safe auto-submit when all rules pass."),
    max_per_seed: int = typer.Option(15, min=1, max=50, help="Maximum job detail URLs to collect per seed page."),
    skip_seen: bool = typer.Option(True, "--skip-seen/--no-skip-seen", help="Skip seed URLs already fully processed."),
    headless: bool = typer.Option(False, "--headless/--no-headless", help="Run browser headless."),
    limit: int = typer.Option(50, min=1, max=1000, help="Maximum new jobs to process/apply in this run."),
) -> None:
    """Streaming queue: discover AND apply jobs seed-by-seed without pre-loading all URLs.

    Unlike 'queue', this processes each search/listing page and immediately applies
    found jobs before moving to the next seed. Ideal for large search URL batches
    (thousands of search pages) where pre-loading all URLs is impractical.
    """
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()
    seed_urls = collector.read_urls(input)
    if not seed_urls:
        console.print("No seed URLs found.")
        raise typer.Exit(code=1)

    total_applied = 0
    total_failed = 0
    total_skipped = 0
    total_new_processed = 0
    total_seeds_processed = 0
    seen_job_urls: set[str] = set()
    zero_yield_clusters: set[str] = set()
    last_platform_submit: dict[str, float] = {}
    last_active_channel: str = ""

    console.print(f"[bold]Stream-queue started[/bold] | seeds={len(seed_urls)} | auto_submit_safe={auto_submit_safe} | limit={limit}")
    tracker.warm_cache()

    with BrowserSession(config, logger, headless=headless) as browser:
        for seed_index, seed_url in enumerate(seed_urls, start=1):
            if total_new_processed >= limit:
                console.print(f"[bold green]Reached target limit of {limit} jobs. Stopping queue.[/bold green]")
                break

            if skip_linkedin_non_job_content_url(collector, seed_url):
                continue

            search_source = detect_source_from_url(seed_url)
            search_key = search_key_from_url(seed_url)
            if skip_seen and tracker.has_checked_search_page(search_source, search_key, seed_url):
                logger.debug("Stream-queue: skipping already checked seed | %s", seed_url)
                continue

            # ── Pillar 2: Predictive Zero-Yield Query Pruning ──
            cluster_key = extract_query_cluster_key(seed_url)
            if cluster_key in zero_yield_clusters:
                low_url = seed_url.lower()
                if any(k in low_url for k in ("jobage=1", "jobage=2", "jobage=3", "r86400", "r259200")):
                    logger.debug("Stream-queue: zero-yield pruning skipped redundant seed | %s", seed_url)
                    tracker.mark_search_page(search_source, search_key, seed_url, status="pruned_zero_yield")
                    continue

            console.rule(f"Seed [{seed_index}/{len(seed_urls)}] {seed_url}")

            if seed_index % 25 == 0:
                try:
                    browser.recycle_page()
                except Exception:  # noqa: BLE001
                    pass

            # Solution C: Dynamic Context Pacing for search seed navigation (1.0s - 1.8s)
            time.sleep(round(random.uniform(1.0, 1.8), 2))

            # ── Navigate to seed ───────────────────────────────────────────
            try:
                page = browser.goto(seed_url)
            except Exception as nav_exc:  # noqa: BLE001
                logger.warning("Stream-queue: seed navigation failed | url=%s | error=%s", seed_url, nav_exc)
                console.print(f"[yellow]Seed navigation failed:[/yellow] {seed_url} -> {nav_exc}")
                continue

            if skip_linkedin_non_job_content_url(collector, page.url):
                continue

            # ── Manual login check ─────────────────────────────────────────
            if collector.is_listing_seed_url(page.url) and collector.page_needs_manual_login(page):
                console.print(f"[yellow]Manual login required:[/yellow] {page.url}")
                browser.wait_for_manual_step("Complete login in the browser, then press Enter to continue.")
                try:
                    page = browser.goto(seed_url)
                except Exception as nav_exc:  # noqa: BLE001
                    logger.warning("Post-login navigation failed | url=%s | error=%s", seed_url, nav_exc)
                    continue
                if skip_linkedin_non_job_content_url(collector, page.url):
                    continue

            # ── Discover candidate jobs from this seed ─────────────────────
            candidate_items: list[dict[str, str]] = []
            if collector.is_listing_seed_url(page.url):
                discovered_candidates = collector.discover_job_candidates(page, profile.target_roles, max_results=max_per_seed)
                new_candidates = [
                    cand for cand in discovered_candidates
                    if cand.get("url") and cand["url"] not in seen_job_urls
                ]
                tracker.mark_search_page(
                    search_source,
                    search_key,
                    page.url or seed_url,
                    status="checked",
                    candidates_found=len(discovered_candidates),
                    selected_count=len(new_candidates),
                )
                if not discovered_candidates:
                    low_url = seed_url.lower()
                    if "jobage=7" in low_url or "r604800" in low_url or "jobage=15" in low_url or "jobage=30" in low_url or not any(k in low_url for k in ("jobage=1", "jobage=2", "jobage=3", "r86400")):
                        zero_yield_clusters.add(cluster_key)
                        logger.debug("Stream-queue: cluster %s marked zero-yield", cluster_key)

                if not new_candidates:
                    logger.info("Stream-queue: no new jobs from seed | url=%s", seed_url)
                    continue
                seen_job_urls.update(c["url"] for c in new_candidates)
                logger.info("Stream-queue: discovered %d new candidate jobs from %s", len(new_candidates), seed_url)
                console.print(f"  -> {len(new_candidates)} new candidate jobs discovered")
                candidate_items = new_candidates
            else:
                # Direct job detail URL
                if page.url not in seen_job_urls:
                    seen_job_urls.add(page.url)
                    candidate_items = [{"url": page.url, "company": "", "title": "", "location": ""}]

            # ── Improvement A: Score-First Priority Application Dispatcher ───
            # Pre-evaluate match score for each candidate and sort descending
            unhandled_candidates: list[tuple[int, str, dict[str, str]]] = []
            for cand in candidate_items:
                job_url = cand.get("url", "")
                if not job_url:
                    continue

                c_comp = cand.get("company", "")
                c_title = cand.get("title", "")
                c_loc = cand.get("location", "")

                # URL-based fallback extraction if company/title/location missing
                if not c_loc or not c_title or not c_comp:
                    lowered_url = job_url.lower()
                    if "naukri.com/job-listings-" in lowered_url:
                        slug = lowered_url.split("job-listings-")[-1].split("?")[0]
                        parts = slug.split("-")
                        for city_hint in ("bengaluru", "bangalore", "pune", "hyderabad", "mumbai", "chennai", "gurgaon", "gurugram", "noida", "delhi"):
                            if city_hint in parts:
                                c_loc = c_loc or ("Bengaluru" if "bang" in city_hint or "beng" in city_hint else city_hint.capitalize())
                                break

                pre_job = JobPosting(
                    source=detect_source_from_url(job_url),
                    url=job_url,
                    company=c_comp,
                    title=c_title,
                    location=c_loc,
                )
                handled = tracker.find_handled_job(pre_job)
                if handled:
                    h_status = handled.get("status") or "handled"
                    console.print(f"  [dim]Already {h_status} in DB:[/dim] {handled.get('title') or job_url}")
                    if h_status == "applied":
                        total_applied += 1
                    else:
                        total_skipped += 1
                    continue

                # Pre-score candidate to prioritize highest-scope roles first
                match_eval = matcher.score(pre_job)
                if match_eval.decision == "skip" and any("India only" in flag for flag in match_eval.red_flags):
                    logger.info("Stream-queue: skipping non-India candidate | %s | %s | %s", c_comp, c_title, c_loc)
                    tracker.upsert_job(pre_job, match_eval, status="skipped", reason="Location outside India (Mandate: India only)")
                    total_skipped += 1
                    continue
                pre_score = match_eval.score
                unhandled_candidates.append((pre_score, job_url, cand))

            # ── Option B: Channel-Interleaved Pipeline (Score-First per Channel + Round-Robin Interleaving) ──
            channel_buckets: dict[str, list[tuple[int, str, dict[str, str]]]] = {
                "linkedin": [],
                "naukri": [],
                "direct": [],
            }
            for score, j_url, c_data in unhandled_candidates:
                low_u = j_url.lower()
                if "linkedin.com" in low_u:
                    channel_buckets["linkedin"].append((score, j_url, c_data))
                elif "naukri.com" in low_u:
                    channel_buckets["naukri"].append((score, j_url, c_data))
                else:
                    channel_buckets["direct"].append((score, j_url, c_data))

            # Sort each channel independently in Score-First descending order
            for ch in channel_buckets:
                channel_buckets[ch].sort(key=lambda item: item[0], reverse=True)

            # Interleave channels round-robin: LinkedIn -> Naukri -> Direct -> LinkedIn...
            interleaved_candidates: list[tuple[int, str, dict[str, str], str]] = []
            while any(channel_buckets.values()):
                for ch in ("linkedin", "naukri", "direct"):
                    if channel_buckets[ch]:
                        sc, u, c_info = channel_buckets[ch].pop(0)
                        interleaved_candidates.append((sc, u, c_info, ch))

            if interleaved_candidates:
                top_scores = [f"{ch[:3].upper()}:{score}pts" for score, _, _, ch in interleaved_candidates[:6]]
                console.print(f"  [cyan]Channel-Interleaved dispatch queue ({len(interleaved_candidates)} jobs: {', '.join(top_scores)}):[/cyan]")

            # ── Process discovered jobs in channel-interleaved priority score order ──────────────
            for pre_score, job_url, cand, platform_channel in interleaved_candidates:
                if total_new_processed >= limit:
                    break

                # Asymmetric Platform Pacing:
                now_ts = time.time()
                last_same_plat_ts = last_platform_submit.get(platform_channel, 0.0)
                elapsed_same_plat = now_ts - last_same_plat_ts

                # Minimum spacing required on the SAME platform to prevent bot-detection
                min_same_platform_spacing = 20.0  # 20s guaranteed separation per platform

                if elapsed_same_plat < min_same_platform_spacing:
                    needed_sleep = min_same_platform_spacing - elapsed_same_plat
                    logger.debug("Platform %s rate pacing: sleeping %ss", platform_channel, round(needed_sleep, 2))
                    time.sleep(needed_sleep)
                elif last_active_channel and last_active_channel != platform_channel:
                    # Switching between different platforms (e.g. LinkedIn -> Naukri)
                    # Only need natural human tab-switch delay (1.8s - 3.2s)!
                    time.sleep(random.uniform(1.8, 3.2))

                total_new_processed += 1
                try:
                    process_job_url(
                        page=browser.current_page(),
                        url=job_url,
                        tracker=tracker,
                        profile=profile,
                        collector=collector,
                        matcher=matcher,
                        filler=filler,
                        auto_submit_safe=auto_submit_safe,
                        config=config,
                        non_interactive=True,
                    )
                    # Peek at last tracker entry to tally outcome
                    last = tracker.list_jobs(limit=1, status=None)
                    last_status = last[0]["status"] if last else "unknown"
                    if last_status == "applied":
                        total_applied += 1
                        last_platform_submit[platform_channel] = time.time()
                        last_active_channel = platform_channel
                        console.print(f"  [bold green][APPLIED - {platform_channel.upper()}][/bold green] {job_url}")

                        # ── Pillar 3 & 4: Stealth Jitter & Anti-Ban Cadence Spacing ──
                        # Natural human rest cadence: 60-95s micro-rest every 20 submissions
                        if total_applied % 20 == 0:
                            rest_duration = round(random.uniform(60.0, 95.0), 1)
                            console.print(f"[bold cyan]Stealth Cadence:[/bold cyan] Natural human rest ({rest_duration}s) to reset platform rate-limit heuristics...")
                            logger.info("Stealth Jitter: natural cadence micro-rest for %ss after 20 submissions", rest_duration)
                            time.sleep(rest_duration)
                        else:
                            # Natural human post-submission pause
                            time.sleep(random.uniform(2.5, 4.5))
                    elif last_status in ("failed", "error"):
                        total_failed += 1
                        time.sleep(random.uniform(1.5, 3.0))
                    else:
                        total_skipped += 1
                        time.sleep(max(0.8, min(2.0, random.gauss(1.2, 0.3))))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Stream-queue: job processing failed | url=%s", job_url)
                    tracker.upsert_job(
                        JobPosting(source=detect_source_from_url(job_url), url=job_url),
                        MatchResult(score=0, decision="skip"),
                        status="failed",
                        reason=str(exc),
                    )
                    total_failed += 1
                    console.print(f"[red]Failed:[/red] {job_url} -> {exc}")
                finally:
                    try:
                        browser.close_extra_tabs()
                    except Exception:  # noqa: BLE001
                        pass

            total_seeds_processed += 1

            # ── Progress snapshot & tab recycling every 20 seeds ──────────────────────────
            if total_seeds_processed % 20 == 0:
                console.print(
                    f"[bold cyan]Progress:[/bold cyan] seeds_checked={total_seeds_processed} | "
                    f"new_jobs_processed={total_new_processed}/{limit} | "
                    f"applied={total_applied} | skipped={total_skipped} | failed={total_failed}"
                )
                try:
                    browser.recycle_page()
                except Exception:  # noqa: BLE001
                    pass

    console.print(
        f"\n[bold green]Stream-queue complete:[/bold green] "
        f"seeds_checked={total_seeds_processed} | new_jobs_processed={total_new_processed} | "
        f"applied={total_applied} | skipped={total_skipped} | failed={total_failed}"
    )


@app.command(name="list")
def list_jobs(
    limit: int = typer.Option(25, min=1, max=200, help="Maximum rows to show."),
    status: str = typer.Option("", help="Optional status filter."),
) -> None:
    """List tracked jobs from SQLite."""
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    tracker = JobTracker(config.db_path, logger)
    tracker.init_db()
    rows = tracker.list_jobs(limit=limit, status=status or None)
    table = Table(title="Tracked Jobs")
    for column in ("id", "source", "company", "title", "score", "status", "created_at"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            str(row["id"]),
            row["source"] or "",
            row["company"] or "",
            row["title"] or "",
            str(row["score"] or ""),
            row["status"] or "",
            row["created_at"] or "",
        )
    console.print(table)


@app.command()
def stats() -> None:
    """Show aggregate job tracker statistics."""
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    tracker = JobTracker(config.db_path, logger)
    tracker.init_db()
    data = tracker.stats()
    table = Table(title="Job Stats")
    table.add_column("status")
    table.add_column("count")
    for key, value in sorted(data.items()):
        table.add_row(key, str(value))
    console.print(table)


@app.command(name="platform-stats")
def platform_stats() -> None:
    """Show per-platform application dashboard (Naukri, LinkedIn, External)."""
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    tracker = JobTracker(config.db_path, logger)
    tracker.init_db()
    data = tracker.platform_stats()

    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TextColumn
    from rich.columns import Columns

    PLATFORM_ORDER = ["naukri", "linkedin", "external"]
    PLATFORM_LABELS = {
        "naukri": "[blue]Naukri[/blue]",
        "linkedin": "[cyan]LinkedIn[/cyan]",
        "external": "[green]External / Company Sites[/green]",
    }

    # Avoid double-counting external (which already aggregates company+unknown)
    naukri_total = data.get("naukri", {}).get("total", 0)
    linkedin_total = data.get("linkedin", {}).get("total", 0)
    ext_total = data.get("external", {}).get("total", 0)
    grand_total = naukri_total + linkedin_total + ext_total

    console.print()
    console.rule("[bold cyan]Job Agent -- Application Dashboard")
    console.print()

    summary_table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    summary_table.add_column("Platform", style="bold")
    summary_table.add_column("Applied", justify="right", style="green")
    summary_table.add_column("Pending Submit", justify="right", style="yellow")
    summary_table.add_column("Needs Manual", justify="right", style="orange1")
    summary_table.add_column("Remaining Queue", justify="right", style="cyan")
    summary_table.add_column("Failed/Skipped", justify="right", style="red")
    summary_table.add_column("Total Tracked", justify="right")

    for platform in PLATFORM_ORDER:
        if platform not in data:
            continue
        p = data[platform]
        remaining = p.get("shortlisted", 0) + p.get("needs_manual", 0)
        summary_table.add_row(
            PLATFORM_LABELS.get(platform, platform.title()),
            str(p.get("applied", 0)),
            str(p.get("pending_submit", 0)),
            str(p.get("needs_manual", 0)),
            str(p.get("shortlisted", 0)),
            str(p.get("failed", 0) + p.get("error", 0)),
            str(p.get("total", 0)),
        )

    summary_table.add_section()
    grand_applied = sum(data.get(p, {}).get("applied", 0) for p in PLATFORM_ORDER if p in data)
    grand_pending = sum(data.get(p, {}).get("pending_submit", 0) for p in PLATFORM_ORDER if p in data)
    grand_manual = sum(data.get(p, {}).get("needs_manual", 0) for p in PLATFORM_ORDER if p in data)
    grand_shortlisted = sum(data.get(p, {}).get("shortlisted", 0) for p in PLATFORM_ORDER if p in data)
    grand_failed = sum(data.get(p, {}).get("failed", 0) + data.get(p, {}).get("error", 0) for p in PLATFORM_ORDER if p in data)
    summary_table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold green]{grand_applied}[/bold green]",
        f"[bold yellow]{grand_pending}[/bold yellow]",
        f"[bold orange1]{grand_manual}[/bold orange1]",
        f"[bold cyan]{grand_shortlisted}[/bold cyan]",
        f"[bold red]{grand_failed}[/bold red]",
        f"[bold]{grand_total}[/bold]",
    )

    console.print(summary_table)
    console.print()

    # Progress bars per platform
    if grand_total > 0:
        console.rule("[bold]Application Progress by Platform")
        console.print()
        for platform in PLATFORM_ORDER:
            if platform not in data:
                continue
            p = data[platform]
            label = PLATFORM_LABELS.get(platform, platform.title())
            applied = p.get("applied", 0)
            total = p.get("total", 0)
            pct = int((applied / total) * 100) if total > 0 else 0
            bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
            console.print(f"  {label:<26} \\[{bar}\\] {pct:>3}%  ({applied}/{total} applied)")
        console.print()

    console.rule("[bold]Summary")
    console.print(f"  \\[+]  Total applied across all platforms : [bold green]{grand_applied}[/bold green]")
    console.print(f"  \\[~]  Remaining in queue                 : [bold cyan]{grand_shortlisted}[/bold cyan]")
    console.print(f"  \\[>]  Pending final submit               : [bold yellow]{grand_pending}[/bold yellow]")
    console.print(f"  \\[!]  Needs manual review                : [bold orange1]{grand_manual}[/bold orange1]")
    console.print(f"  \\[x]  Failed / Skipped                   : [bold red]{grand_failed}[/bold red]")
    console.print()

@app.command(name="seen-companies")
def seen_companies(
    source: str = typer.Option("", help="Optional source filter, for example linkedin or naukri."),
    search_key: str = typer.Option("", help="Optional normalized search keyword filter."),
    limit: int = typer.Option(50, min=1, max=300, help="Maximum rows to show."),
) -> None:
    """List companies remembered for repeated search skipping."""
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    tracker = JobTracker(config.db_path, logger)
    tracker.init_db()
    rows = tracker.list_seen_companies(source=source or None, search_key=search_key or None, limit=limit)
    table = Table(title="Seen Companies By Search")
    for column in ("source", "search_key", "company", "status", "seen_count", "last_seen_at"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            row["source"] or "",
            row["search_key"] or "",
            row["company"] or "",
            row["status"] or "",
            str(row["seen_count"] or ""),
            row["last_seen_at"] or "",
        )
    console.print(table)


@app.command(name="seen-pages")
def seen_pages(
    source: str = typer.Option("", help="Optional source filter, for example linkedin or naukri."),
    search_key: str = typer.Option("", help="Optional normalized search keyword filter."),
    limit: int = typer.Option(50, min=1, max=300, help="Maximum rows to show."),
) -> None:
    """List search result pages remembered for repeated search skipping."""
    config = load_config()
    logger = setup_logger(config.log_path, config.log_level)
    tracker = JobTracker(config.db_path, logger)
    tracker.init_db()
    rows = tracker.list_seen_pages(source=source or None, search_key=search_key or None, limit=limit)
    table = Table(title="Seen Search Pages")
    for column in ("source", "search_key", "status", "selected", "skipped", "last_seen_at", "page_url"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            row["source"] or "",
            row["search_key"] or "",
            row["status"] or "",
            str(row["selected_count"] or ""),
            str(row["skipped_seen_count"] or ""),
            row["last_seen_at"] or "",
            row["page_url"] or "",
        )
    console.print(table)


@app.command(name="check-followups")
def check_followups(
    days: int = typer.Option(30, min=1, max=120, help="Look back this many days."),
    max_per_folder: int = typer.Option(50, min=5, max=300, help="Maximum recent messages to inspect per folder."),
    create_template: bool = typer.Option(
        False,
        "--create-template",
        help="Write profile/email_accounts.example.json and exit.",
    ),
) -> None:
    """Report application follow-up emails from configured inbox and spam folders."""
    config, logger, tracker, _, _, _, _, _ = build_runtime()
    from app.ollama_client import OllamaClient
    ollama_client = OllamaClient(
        config.ollama_base_url,
        config.ollama_model,
        logger,
        api_style=config.ai_api_style,
        fallback_models=config.fallback_models,
        api_key=config.ai_api_key,
    )
    monitor = EmailFollowupMonitor(config.email_accounts_path, config.exports_dir, logger, ollama_client=ollama_client)
    if create_template or not config.email_accounts_path.exists():
        template = monitor.write_template()
        console.print(f"[yellow]Email accounts are not configured yet.[/yellow] Template written: {template}")
        console.print(f"Create {config.email_accounts_path} from the template and set the password env vars.")
        if not create_template:
            return
    if create_template:
        return

    tracked_rows = tracker.export_rows()
    output, hits = monitor.scan(tracked_rows, days=days, max_per_folder=max_per_folder)
    console.print(f"[green]Follow-up report written:[/green] {output}")
    console.print(f"Flagged emails: {len(hits)}")


@app.command()
def autorun(
    keyword_count: int = typer.Option(6, min=1, help="Number of keyword groups to scout."),
    max_per_search: int = typer.Option(8, min=1, help="Max job URLs to collect per search page."),
    limit: int = typer.Option(25, min=1, help="Max jobs to inspect during scouting."),
    min_score: int = typer.Option(50, min=0, max=100, help="Minimum score to shortlist a job."),
    apply_limit: int = typer.Option(10, min=1, help="Max shortlisted jobs to fill in this run."),
    fresh_only: bool = typer.Option(
        True,
        "--fresh-only/--all-dates",
        help="Restrict to recently posted jobs where supported.",
    ),
    fresh_days: int = typer.Option(15, min=1, help="Freshness window in days for --fresh-only."),
    linkedin_posts: bool = typer.Option(
        True,
        "--linkedin-posts/--no-linkedin-posts",
        help="Also scan LinkedIn content/post search for hiring posts.",
    ),
    linkedin_jobs: bool = typer.Option(
        True,
        "--linkedin-jobs/--no-linkedin-jobs",
        help="Also search the LinkedIn Jobs tab.",
    ),
    skip_seen_companies: bool = typer.Option(
        True,
        "--skip-seen-companies/--no-skip-seen-companies",
        help="Skip companies already reviewed for the same source and search keyword.",
    ),
    skip_checked_pages: bool = typer.Option(
        True,
        "--skip-checked-pages/--no-skip-checked-pages",
        help="Skip result pages already fully processed for the same source and keyword.",
    ),
    max_pages_per_search: int = typer.Option(
        1,
        min=1,
        help="Number of unchecked result pages to process per source/keyword.",
    ),
    check_email: bool = typer.Option(
        False,
        "--check-email/--no-check-email",
        help="Also run the email follow-up monitor at the end of the run.",
    ),
    email_days: int = typer.Option(30, min=1, help="Days window for email follow-up check."),
    keyword_offset: int = typer.Option(0, min=0, help="Starting index in the search keyword list."),
    prioritize_unsearched: bool = typer.Option(
        True,
        "--prioritize-unsearched/--no-prioritize-unsearched",
        help="Place unsearched keywords first to ensure complete coverage.",
    ),
) -> None:
    """Fully automated pipeline: scout, shortlist, then fill.

    Runs scouting, scores every discovered job, then silently fills and saves
    each shortlisted application as filled_pending_submit.  No interactive
    prompts are shown.  After the run, open Firefox and submit the applications
    you want to proceed with, then call mark-applied.

    Requires a valid browser session (run 'open' and log in manually first).
    """
    config, logger, tracker, profile, collector, matcher, filler, _ = build_runtime()

    # ── Override filler to non-interactive mode ──────────────────────────────
    templates = load_answer_templates(config.answer_templates_path)
    from app.ollama_client import OllamaClient as _OC
    ollama_client = _OC(
        config.ollama_base_url,
        config.ollama_model,
        logger,
        api_style=config.ai_api_style,
        fallback_models=config.fallback_models,
        api_key=config.ai_api_key,
    )
    filler = FormFiller(config, logger, ollama_client, non_interactive=True)
    filler.set_templates(templates)

    console.rule("[bold cyan]autorun: scout phase[/bold cyan]")
    search_keywords = build_search_keywords(profile)
    if prioritize_unsearched:
        search_keywords = prioritize_unsearched_keywords(search_keywords, tracker)
    selected_keywords = search_keywords[keyword_offset : keyword_offset + keyword_count]
    search_urls = build_search_urls(
        selected_keywords,
        include_posts=linkedin_posts,
        include_jobs=True,
        include_linkedin_jobs=linkedin_jobs,
        fresh_only=fresh_only,
        fresh_days=fresh_days,
    )

    discovered: list[str] = []
    discovered_meta: dict[str, dict[str, str]] = {}
    page_progress: dict[str, dict[str, int | str]] = {}
    scout_rows: list[dict] = []

    with BrowserSession(config, logger, headless=config.headless) as browser:
        # ── Phase 1: Scout ───────────────────────────────────────────────────
        for seed_url in search_urls:
            try:
                page = browser.goto(seed_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("autorun: skipping search seed after navigation failure | url=%s | error=%s", seed_url, exc)
                continue
            scanned_pages = 0
            page_hops = 0
            while scanned_pages < max_pages_per_search and len(discovered) < limit:
                if collector.page_needs_manual_login(page):
                    logger.warning(
                        "autorun: login required at %s — skipping this source. "
                        "Run 'python app/main.py open' and log in, then retry.",
                        page.url,
                    )
                    console.print(
                        f"[yellow]autorun: login wall hit at {page.url} — skipping.[/yellow] "
                        "Run [bold]python app/main.py open[/bold] to log in, then retry autorun."
                    )
                    break

                page_url = page.url or seed_url
                search_source = detect_source_from_url(page_url)
                search_key = search_key_from_url(page_url)

                if skip_checked_pages and tracker.has_checked_search_page(search_source, search_key, page_url):
                    page_hops += 1
                    if page_hops > max_pages_per_search + 8 or not collector.advance_listing_page(page):
                        break
                    continue

                scan_limit = max_per_search * 3
                candidates = collector.discover_job_candidates(page, profile.target_roles, max_results=scan_limit)
                selected: list[dict[str, str]] = []
                skipped_seen = 0
                skipped_handled = 0
                for candidate in candidates:
                    company = candidate.get("company", "")
                    candidate_url = candidate.get("url", "")
                    if collector.is_blocked_application_url(candidate_url) or collector.is_non_job_content_url(candidate_url):
                        continue
                    handled = tracker.find_handled_job(
                        JobPosting(
                            source=detect_source_from_url(candidate_url),
                            company=company,
                            title=candidate.get("title", ""),
                            url=candidate_url,
                        )
                    )
                    if handled:
                        skipped_handled += 1
                        continue
                    already_seen = (
                        skip_seen_companies
                        and company
                        and (
                            tracker.has_seen_company_for_search(search_source, search_key, company)
                            or tracker.has_seen_company_for_source(search_source, company)
                        )
                    )
                    if already_seen:
                        skipped_seen += 1
                        continue
                    selected.append(candidate)
                    if len(selected) >= max_per_search:
                        break

                batch: list[str] = []
                page_limited = False
                for candidate in selected:
                    url = candidate.get("url", "")
                    if not url or url in discovered or url in batch:
                        continue
                    if len(discovered) + len(batch) >= limit:
                        page_limited = True
                        break
                    batch.append(url)
                    discovered_meta[url] = {
                        "search_source": search_source,
                        "search_key": search_key,
                        "search_page_url": page_url,
                        "company": candidate.get("company", ""),
                        "title": candidate.get("title", ""),
                    }

                tracker.mark_search_page(
                    search_source,
                    search_key,
                    page_url,
                    status="discovered" if batch else "checked",
                    candidates_found=len(candidates),
                    selected_count=len(batch),
                    skipped_seen_count=skipped_seen + skipped_handled,
                )
                if batch:
                    page_progress[page_url] = {
                        "source": search_source,
                        "search_key": search_key,
                        "expected": len(batch),
                        "processed": 0,
                        "candidates_found": len(candidates),
                        "selected_count": len(batch),
                        "skipped_seen_count": skipped_seen + skipped_handled,
                        "can_mark_checked": not page_limited,
                    }

                console.print(
                    f"autorun scout: {len(batch)} new from {page_url}"
                    + (f" | skipped {skipped_seen} seen companies" if skipped_seen else "")
                    + (f" | skipped {skipped_handled} handled" if skipped_handled else "")
                )
                discovered.extend(batch)
                discovered = unique_list(discovered)
                scanned_pages += 1
                if len(discovered) >= limit or scanned_pages >= max_pages_per_search:
                    break
                if not collector.advance_listing_page(page):
                    break
            if len(discovered) >= limit:
                break

        shortlisted_count = 0
        browser_retry_counts: dict[str, int] = {}

        def _mark_processed(candidate_url: str) -> None:
            meta = discovered_meta.get(candidate_url, {})
            pg_url = meta.get("search_page_url", "")
            if not pg_url or pg_url not in page_progress:
                return
            state = page_progress[pg_url]
            state["processed"] = int(state.get("processed", 0)) + 1
            if int(state.get("processed", 0)) >= int(state.get("expected", 0)):
                if not bool(state.get("can_mark_checked", True)):
                    return
                tracker.mark_search_page(
                    str(state.get("source", "")),
                    str(state.get("search_key", "")),
                    pg_url,
                    status="checked",
                    candidates_found=int(state.get("candidates_found", 0)),
                    selected_count=int(state.get("selected_count", 0)),
                    skipped_seen_count=int(state.get("skipped_seen_count", 0)),
                )

        for index, url in enumerate(discovered, start=1):
            console.rule(f"autorun inspect {index}/{len(discovered)}")
            requeued = False
            page = None
            try:
                if collector.is_blocked_application_url(url) or collector.is_non_job_content_url(url):
                    continue
                page = browser.current_page()
                job = collector.collect(page, url)
                actionability_audit = collector.expand_for_actionability_check(page)
                job = collector.refresh_current_page_job(page, job, actionability_audit)
                meta = discovered_meta.get(url, {})
                search_source = meta.get("search_source") or job.source
                search_key = meta.get("search_key") or "manual"
                if tracker.is_already_applied(job):
                    console.print(f"[green]Already applied, skipping:[/green] {job.title or url}")
                    continue
                apply_path = detect_apply_path(page)
                if apply_path == "already applied":
                    match = MatchResult(score=0, decision="already applied")
                    tracker.upsert_job(job, match, status="applied", reason="Site shows already applied.")
                    continue
                job, _, _ = append_company_site_context(page, collector, job, apply_path, config.exports_dir)
                contact_methods = find_contact_methods(
                    " ".join([job.raw_text, job.criteria_text, job.description, job.application_url, job.url])
                )
                if not has_actionable_apply_or_contact(apply_path, contact_methods):
                    match = MatchResult(score=0, decision="skip")
                    tracker.upsert_job(job, match, status="skipped", reason="no apply button, company application link, email, or phone found")
                    tracker.mark_company_seen_for_search(search_source, search_key, job.company or "", job.title or "", job.url, "skipped")
                    console.print(f"skipped (no apply path): {job.title or url}")
                    continue
                match = matcher.score(job)
                is_support_fallback = match.decision == TECHNICAL_SUPPORT_FALLBACK_DECISION
                status = "shortlisted" if (
                    is_support_fallback or (match.score >= min_score and match.decision != "skip")
                ) else "skipped"
                skip_reason = skip_reason_for_match(match, status, apply_path)
                reason = skip_reason if status == "skipped" else f"{match.decision}; {apply_path}"
                tracker.upsert_job(job, match, status=status, reason=reason)
                tracker.mark_company_seen_for_search(search_source, search_key, job.company or "", job.title or "", job.url, status)
                scout_rows.append({
                    "score": match.score,
                    "decision": match.decision,
                    "status": status,
                    "source": job.source,
                    "company": job.company,
                    "title": job.title,
                    "url": job.url,
                })
                if status == "shortlisted":
                    shortlisted_count += 1
                console.print(f"{status}: {job.title or 'Unknown'} | score={match.score} | {apply_path}")
            except Exception as exc:  # noqa: BLE001
                if is_browser_closed_error(exc) and browser_retry_counts.get(url, 0) < 1:
                    browser_retry_counts[url] = 1
                    try:
                        browser.restart()
                        discovered.append(url)
                        requeued = True
                    except Exception:  # noqa: BLE001
                        logger.exception("autorun: browser restart failed.")
                    if requeued:
                        continue
                logger.exception("autorun: inspection failed for %s", url)
                console.print(f"[red]autorun: failed to inspect:[/red] {url} -> {exc}")
            finally:
                if not requeued:
                    _mark_processed(url)
                    try:
                        browser.close_extra_tabs(keep=page)
                    except Exception:  # noqa: BLE001
                        pass

        # ── Phase 2: Fill shortlisted jobs ───────────────────────────────────
        console.rule("[bold cyan]autorun: fill phase[/bold cyan]")
        shortlisted_rows = tracker.list_jobs(limit=apply_limit, status="shortlisted")
        if not shortlisted_rows:
            console.print("autorun: no shortlisted jobs to fill.")
        else:
            console.print(f"autorun: filling {len(shortlisted_rows)} shortlisted job(s)…")

        fill_results: list[dict] = []
        needs_manual_results: list[dict] = []
        failed_results: list[dict] = []

        for index, row in enumerate(shortlisted_rows, start=1):
            console.rule(f"autorun fill {index}/{len(shortlisted_rows)}")
            
            try:
                page = browser.current_page()
                url = row["url"]
                job = collector.collect(page, url)
                if not job.title and row.get("title"):
                    job.title = row["title"]
                if not job.company and row.get("company"):
                    job.company = row["company"]
                match = matcher.score(job)
                fill_result, application_page = filler.fill(
                    page=page,
                    job=job,
                    match=match,
                    profile=profile,
                    auto_submit_safe=True,
                )
                if fill_result.status == "applied":
                    reason = "auto-submit-safe" if fill_result.auto_submitted else "already applied on job board"
                    tracker.upsert_job(job, match, status="applied", reason=reason)
                    fill_results.append({"title": job.title, "company": job.company, "source": job.source, "score": match.score, "url": url})
                    console.print(f"[green]autorun: recorded applied ({reason}):[/green] {job.title or url}")
                elif fill_result.status == "failed":
                    reason = ", ".join(fill_result.errors) or "Application failed"
                    tracker.upsert_job(job, match, status="failed", reason=reason)
                    failed_results.append({"title": job.title, "company": job.company, "reason": reason, "url": url})
                    console.print(f"[red]autorun: failed:[/red] {job.title or url} — {reason}")
                elif fill_result.status == "needs_manual_input":
                    blocker = ", ".join(fill_result.submit_blockers or fill_result.unknown_questions)
                    tracker.upsert_job(job, match, status="needs_manual_input", reason=blocker, notes="Blocked during autorun.")
                    needs_manual_results.append({"title": job.title, "company": job.company, "reason": blocker, "url": url})
                    console.print(f"[yellow]autorun: needs manual input:[/yellow] {job.title or url} — {blocker}")
                else:
                    tracker.upsert_job(
                        job, match,
                        status="filled_pending_submit",
                        reason="autorun: filled and saved for manual review before submit.",
                    )
                    fill_results.append({"title": job.title, "company": job.company, "source": job.source, "score": match.score, "url": url})
                    console.print(f"[cyan]autorun: filled:[/cyan] {job.title or url}")
                if application_page is not page:
                    try:
                        if not application_page.is_closed():
                            application_page.close()
                        page.bring_to_front()
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                logger.exception("autorun: fill failed for %s", row.get("url"))
                failed_results.append({"title": row.get("title"), "company": row.get("company"), "reason": str(exc), "url": row.get("url")})
                console.print(f"[red]autorun: fill failed:[/red] {row.get('url')} -> {exc}")
            finally:
                try:
                    browser.close_extra_tabs()
                except Exception:  # noqa: BLE001
                    pass

    # ── Phase 3: Optional email check ────────────────────────────────────────
    if check_email:
        console.rule("[bold cyan]autorun: email check phase[/bold cyan]")
        try:
            monitor = EmailFollowupMonitor(config.email_accounts_path, config.exports_dir, logger, ollama_client=ollama_client)
            if config.email_accounts_path.exists():
                tracked_rows = tracker.list_jobs(limit=500, status="applied")
                output, hits = monitor.scan(tracked_rows, days=email_days)
                console.print(f"[green]Follow-up report:[/green] {output} ({len(hits)} flagged)")
            else:
                console.print("[yellow]autorun: email accounts not configured — skipping email check.[/yellow]")
        except Exception as exc:  # noqa: BLE001
            logger.warning("autorun: email check failed: %s", exc)
            console.print(f"[yellow]autorun: email check skipped due to error:[/yellow] {exc}")

    # ── Summary ───────────────────────────────────────────────────────────────
    console.rule("[bold cyan]autorun: summary[/bold cyan]")
    summary_path = write_autorun_summary(
        output_dir=config.exports_dir,
        scouted=len(discovered),
        shortlisted=shortlisted_count,
        filled=fill_results,
        needs_manual=needs_manual_results,
        failed=failed_results,
        logger=logger,
    )
    console.print(f"[green]Autorun complete.[/green] Summary: {summary_path}")
    console.print(
        f"  Scouted: {len(discovered)} | Shortlisted: {shortlisted_count} | "
        f"Filled: {len(fill_results)} | Needs manual: {len(needs_manual_results)} | "
        f"Failed: {len(failed_results)}"
    )
    console.print(
        "Open Firefox ([bold]python app/main.py open[/bold]) to review and submit the filled applications."
    )


@app.command()
def export() -> None:
    """Export tracked jobs to CSV."""
    config, _, tracker, _, _, _, _, exporter = build_runtime()
    rows = tracker.export_rows()
    output_path = exporter.export_jobs(rows)
    console.print(f"Exported CSV: {output_path}")


@app.command(name="stop-ai")
def stop_ai() -> None:
    """Force quit local Ollama process and unload models to free 100% of RAM."""
    config, logger, _, _, _, _, filler, _ = build_runtime()
    filler.ollama_client.stop_server()
    console.print("[green]✓ Local AI (Ollama) has been stopped and RAM released.[/green]")


@app.command(name="apply-posts")
def apply_posts(
    live: bool = typer.Option(False, "--live", help="Send actual emails via Gmail SMTP (default is dry run)."),
    pages: int = typer.Option(5, "--pages", min=1, max=20, help="Max search result pages to scan per query."),
    headful: bool = typer.Option(False, "--headful", help="Run browser in headful mode (visible window)."),
) -> None:
    """Scan recent LinkedIn hiring posts for recruiter email invitations and apply with resume."""
    import subprocess
    config = load_config()
    script_path = str(config.project_root / "linkedin_post_applier.py")
    cmd = [sys.executable, script_path, "--pages", str(pages)]
    if live:
        cmd.append("--live")
    if headful:
        cmd.append("--headful")
    console.print(f"[bold cyan]Launching LinkedIn Post Email Applier...[/bold cyan] (live={live}, pages={pages})")
    subprocess.run(cmd, check=False)


@app.command(name="profiles")
def list_profiles() -> None:
    """List all available candidate persona profiles and their headlines."""
    from app.profile_loader import list_available_profiles, load_profile
    profiles = list_available_profiles()
    table = Table(title="Configured Candidate Persona Profiles")
    table.add_column("Profile Key", style="bold cyan")
    table.add_column("Headline", style="white")
    table.add_column("Experience", justify="right")
    table.add_column("Top Target Roles", style="dim")

    for p_name in profiles:
        try:
            p = load_profile(p_name)
            roles = ", ".join(p.target_roles[:3])
            table.add_row(p_name, p.headline or "—", f"{p.experience_years} yrs", roles)
        except Exception as exc:
            table.add_row(p_name, f"Error: {exc}", "—", "—")
    console.print(table)


@app.command(name="sync-inbox")
def sync_inbox(
    max_messages: int = typer.Option(15, min=1, max=100, help="Max recent messages to inspect from IMAP inbox."),
) -> None:
    """Autonomous inbound recruiter triage & interview invite monitor."""
    from app.inbound_sync import InboundSyncManager
    console.print(f"[bold cyan]Initiating Inbound Recruiter Triage Sync (max={max_messages})...[/bold cyan]")
    mgr = InboundSyncManager()
    results = mgr.sync_imap_inbox(max_messages=max_messages)
    if not results:
        console.print("[yellow]No new recruiter interview invitations or assessments detected in inbox.[/yellow]")
    else:
        console.print(f"[bold green]✓ Succeeded:[/bold green] Triaged {len(results)} recruiter engagements. Alerts logged to exports/interview_alerts.md.")


@app.command(name="interviews")
def list_interviews(
    limit: int = typer.Option(25, min=1, max=200, help="Number of interview records to display."),
    status: str = typer.Option("", help="Optional status filter (e.g. needs_action, scheduled)."),
) -> None:
    """Display tracked inbound recruiter invitations, interview calls, and assessments."""
    config = load_config()
    tracker = JobTracker(config.db_path)
    tracker.init_db()
    items = tracker.list_interviews(status=status or None, limit=limit)
    if not items:
        console.print("[yellow]No interview records found in database. Run 'sync-inbox' to fetch inbound invitations.[/yellow]")
        return

    table = Table(title="Inbound Interviews & Recruiter Engagements")
    table.add_column("ID", style="dim")
    table.add_column("Company", style="bold white")
    table.add_column("Intent", style="bold green")
    table.add_column("Recruiter Email", style="dim")
    table.add_column("Meeting / Assessment Link", style="cyan")
    table.add_column("Date Logged", style="dim")

    for item in items:
        link = item.get("meeting_link") or item.get("assessment_link") or "—"
        table.add_row(
            str(item.get("id")),
            item.get("company") or "Direct",
            item.get("intent") or "INVITE",
            item.get("recruiter_email") or "—",
            link[:50] + ("..." if len(link) > 50 else ""),
            item.get("created_at") or "—",
        )
    console.print(table)


@app.command(name="live")
@app.command(name="monitor")
def live_monitor(
    profile_name: str = typer.Option("default", "--profile", "-p", help="Profile to inspect."),
) -> None:
    """Launch the Mission Control Rich terminal telemetry radar."""
    from app.telemetry_radar import render_radar_dashboard
    config = load_config(profile_name=profile_name)
    tracker = JobTracker(config.db_path)
    tracker.init_db()
    console.print(render_radar_dashboard(config=config, tracker=tracker))


@app.command(name="dashboard")
@app.command(name="ui")
def dashboard(
    port: int = typer.Option(8765, min=1024, max=65535, help="Port to bind the local dashboard web server."),
    profile_name: str = typer.Option("default", "--profile", "-p", help="Active profile name."),
) -> None:
    """Launch the local web-based Mission Control dashboard."""
    from app.web_radar import run_web_dashboard
    run_web_dashboard(port=port, profile_name=profile_name)


@app.command(name="compile-resume")
def compile_resume(
    job_title: str = typer.Option("Cybersecurity Analyst", help="Target job title to tailor the resume for."),
    company: str = typer.Option("Target Company", help="Target company name."),
    profile_name: str = typer.Option("default", "--profile", "-p", help="Persona profile to use."),
    jd: str = typer.Option("", help="Optional snippet of target job description."),
) -> None:
    """Dynamically compile an ATS-compliant tailored PDF resume."""
    from app.resume_compiler import DynamicResumeCompiler
    from app.profile_loader import load_profile
    profile = load_profile(profile_name)
    compiler = DynamicResumeCompiler()
    prefix = f"{profile_name}_{re.sub(r'[^a-zA-Z0-9]', '_', company)}_{re.sub(r'[^a-zA-Z0-9]', '_', job_title)}"
    pdf_path = compiler.compile_tailored_pdf(
        profile=profile,
        job_title=job_title,
        company=company,
        job_description=jd,
        filename_prefix=prefix,
    )
    console.print(f"[bold green]✓ ATS Tailored Resume compiled successfully:[/bold green] {pdf_path} ({pdf_path.stat().st_size} bytes)")


if __name__ == "__main__":
    app()
