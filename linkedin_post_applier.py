"""
linkedin_post_applier.py — Main orchestrator for the LinkedIn Post Email Applier.

Scans LinkedIn post feed for cybersecurity/VAPT hiring opportunities where
recruiters invite candidates to email their resumes, then:
  1. Parses each post for email address, subject line, role, and experience filter
  2. Composes a tailored cover email (HTML + plain text) using Ollama / template
  3. Sends the email via Gmail SMTP with resume attached
  4. Tracks every attempt in jobs.db (linkedin_post_emails table)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CONFIGURATION FLAGS (edit before running)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import logging
import random
import subprocess
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
DRY_RUN = True          # Set to False to actually send emails
MAX_PAGES_PER_QUERY = 10 # Number of search result pages to check per query (up to page 10)
MAX_POSTS_PER_QUERY = 10 # Number of LinkedIn posts to inspect per page
SCROLL_TIMES = 3         # How many times to scroll each search results page
DELAY_BETWEEN_QUERIES = 8.0  # Seconds to wait between each query (anti-detection with jitter)
HEADLESS = True          # Set to False to watch the browser
# ─────────────────────────────────────────────────────────────────────────────

# CLI flag overrides
if "--live" in sys.argv:
    DRY_RUN = False
if "--headful" in sys.argv or "--login" in sys.argv:
    HEADLESS = False
if "--pages" in sys.argv:
    try:
        p_idx = sys.argv.index("--pages")
        MAX_PAGES_PER_QUERY = max(1, int(sys.argv[p_idx + 1]))
    except (IndexError, ValueError):
        MAX_PAGES_PER_QUERY = 10

from dotenv import load_dotenv
import os
load_dotenv(PROJECT_ROOT / ".env", override=True)

# Prioritize environment variables / .env for session tokens (prevents CLI process argument snooping)
COOKIE_TOKEN = os.environ.get("LINKEDIN_LI_AT", "").strip() or None
if "--cookie" in sys.argv:
    print("[SECURITY WARNING] Passing session tokens via CLI arguments exposes cookies in OS process tables. Prefer LINKEDIN_LI_AT in .env.")
    try:
        c_idx = sys.argv.index("--cookie")
        COOKIE_TOKEN = sys.argv[c_idx + 1].strip() or COOKIE_TOKEN
    except (IndexError, ValueError):
        pass

JSESSIONID_TOKEN = os.environ.get("LINKEDIN_JSESSIONID", "").strip() or None
if "--jsessionid" in sys.argv:
    print("[SECURITY WARNING] Passing session tokens via CLI arguments exposes cookies in OS process tables. Prefer LINKEDIN_JSESSIONID in .env.")
    try:
        j_idx = sys.argv.index("--jsessionid")
        JSESSIONID_TOKEN = sys.argv[j_idx + 1].strip() or JSESSIONID_TOKEN
    except (IndexError, ValueError):
        pass

BCOOKIE_TOKEN = os.environ.get("LINKEDIN_BCOOKIE", "").strip() or None
if "--bcookie" in sys.argv:
    try:
        b_idx = sys.argv.index("--bcookie")
        BCOOKIE_TOKEN = sys.argv[b_idx + 1].strip() or BCOOKIE_TOKEN
    except (IndexError, ValueError):
        pass

BSCOOKIE_TOKEN = os.environ.get("LINKEDIN_BSCOOKIE", "").strip() or None
if "--bscookie" in sys.argv:
    try:
        bs_idx = sys.argv.index("--bscookie")
        BSCOOKIE_TOKEN = sys.argv[bs_idx + 1].strip() or BSCOOKIE_TOKEN
    except (IndexError, ValueError):
        pass

from app.config import load_config
from app.browser import BrowserSession
from app.ollama_client import OllamaClient
from app.profile_loader import load_profile
from app.linkedin_post_scanner import LinkedInPostScanner, LinkedInPostLead
from app.email_sender import EmailSender
from app.cover_email_composer import CoverEmailComposer
from app.post_email_tracker import PostEmailTracker

# ── Logging setup ──────────────────────────────────────────────────────────────
log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/linkedin_post_applier.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("linkedin_post_applier")


def print_separator(char: str = "─", width: int = 72) -> None:
    print(char * width)


def print_lead_summary(lead: LinkedInPostLead, index: int, total: int) -> None:
    print_separator()
    print(f"  [{index}/{total}] 📌 {lead.role} @ {lead.company}")
    print(f"  Poster      : {lead.poster_name}")
    print(f"  Email(s)    : {', '.join(lead.email_addresses)}")
    print(f"  Subject     : {lead.subject_line}")
    print(f"  Exp. Hint   : {lead.experience_hint}")
    print(f"  Post Age    : {lead.post_age} (Max 3 weeks)")
    print(f"  Skills      : {', '.join(lead.skills_mentioned) or '(not specified)'}")
    print(f"  Fresher OK  : {'✅' if lead.is_fresher_eligible else '⚠️ (check manually)'}")
    print(f"  Relevance   : 🎯 Score {lead.relevance_score}/100 (sorted priority)")
    print(f"  Post URL    : {lead.post_url[:80]}")
    if DRY_RUN:
        print(f"  ▶ DRY RUN — email would be sent to: {', '.join(lead.email_addresses)}")
    print_separator()


def is_linkedin_authenticated(context) -> bool:
    """Checks if the browser context has the active LinkedIn li_at session cookie."""
    try:
        for cookie in context.cookies():
            if cookie.get("name") == "li_at" and "linkedin.com" in cookie.get("domain", ""):
                return True
    except Exception:
        pass
    return False


def main() -> None:
    config = load_config()
    profile = load_profile(config.profile_path)

    # Initialize tracker
    tracker = PostEmailTracker(config.db_path, logger)
    tracker.init_table()
    existing_stats = tracker.get_stats()
    logger.info("Existing linkedin_post_emails stats: %s", existing_stats)

    # Initialize email sender
    smtp_pw = config.smtp_sender_password or config.otp_email_app_password
    email_sender = EmailSender(
        sender_email=config.otp_email_address or profile.email,
        app_password=smtp_pw,
        sender_name=profile.name,
    )

    # Test SMTP connection (skip in dry run to save time, but log a warning)
    if not DRY_RUN:
        ok, msg = email_sender.test_connection()
        if not ok:
            logger.error("SMTP connection test FAILED: %s", msg)
            logger.error("Please verify OTP_EMAIL_APP_PASSWORD in .env and Gmail 2FA app password settings.")
            sys.exit(1)
        logger.info("SMTP connection test: %s", msg)
    else:
        logger.info("[DRY RUN MODE] Skipping SMTP connection test.")

    # Initialize LLM (optional, falls back to template if unavailable)
    ollama_client = None
    try:
        ollama_client = OllamaClient(
            base_url=config.ollama_base_url,
            model=config.ollama_model,
            logger=logger,
            timeout=max(30, config.default_timeout_ms // 1000),
            api_style=config.ai_api_style,
            fallback_models=config.fallback_models,
            api_key=config.ai_api_key,
        )
        if ollama_client.is_available():
            logger.info("Ollama LLM available — will use AI-generated cover emails.")
        else:
            logger.info("Ollama LLM not running — will use template-based cover emails.")
            ollama_client = None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not initialize Ollama client: %s — using template fallback.", exc)
        ollama_client = None

    composer = CoverEmailComposer(ollama_client=ollama_client)
    resume_path = config.resume_path

    print_separator("═")
    print("  🔍 LinkedIn Post Email Applier — Cybersecurity / VAPT Fresher Sweep")
    print(f"  Mode   : {'🧪 DRY RUN (emails will NOT be sent)' if DRY_RUN else '🚀 LIVE MODE — emails WILL be sent'}")
    print(f"  Resume : {resume_path}")
    print(f"  Sender : {profile.email}")
    print_separator("═")

    # ─── BROWSER SCAN OR DIRECT TEST ──────────────────────────────────────────
    all_leads: list[LinkedInPostLead] = []

    # Check for direct text input mode (--test-post "text...")
    test_post_text = None
    if "--test-post" in sys.argv:
        idx = sys.argv.index("--test-post")
        if idx + 1 < len(sys.argv):
            test_post_text = sys.argv[idx + 1]

    if test_post_text:
        logger.info("Direct test-post mode: parsing provided text...")
        scanner = LinkedInPostScanner(page=None, logger_inst=logger)
        card = {"text": test_post_text, "url": "https://www.linkedin.com/posts/manual-input", "time_text": "today"}
        lead = scanner._parse_post_card(card)
        if lead:
            all_leads.append(lead)
        else:
            print("\n⚠️ Provided post text did not qualify (no email invite or senior role requirements detected).")
            return
    else:
        # Check for direct single URL mode (--post <url>)
        single_post_url = None
        if "--post" in sys.argv:
            idx = sys.argv.index("--post")
            if idx + 1 < len(sys.argv):
                single_post_url = sys.argv[idx + 1]

        # ── Launch or connect to Chrome session ───────────────────────────────
        cdp_pw = None
        cdp_browser = None
        session_context = None

        from playwright.sync_api import sync_playwright
        cdp_pw = sync_playwright().start()

        # 1. Try connecting to an existing port 9222 session first
        try:
            cdp_browser = cdp_pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
            session_context = cdp_browser.contexts[0]
            logger.info("⚡ CONNECTED TO EXISTING CHROME SESSION OVER CDP (PORT 9222)!")
        except Exception:
            cdp_browser = None

        # 2. Launch browser context
        browser_inst = None
        if not session_context:
            chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            if COOKIE_TOKEN:
                logger.info("Launching isolated high-stealth Chrome session with authenticated tokens (headless=%s)", HEADLESS)
                try:
                    browser_inst = cdp_pw.chromium.launch(
                        executable_path=chrome_path if Path(chrome_path).exists() else None,
                        channel="chrome" if not Path(chrome_path).exists() else None,
                        headless=HEADLESS,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    session_context = browser_inst.new_context(
                        user_agent=config.user_agent,
                        viewport={"width": 1280, "height": 800},
                    )
                    try:
                        from playwright_stealth import Stealth
                        Stealth().apply_stealth_sync(session_context)
                    except Exception:
                        pass
                    logger.info("⚡ LAUNCHED ISOLATED BROWSER CONTEXT WITH SAVED TOKENS SUCCESSFULLY!")
                except Exception as e:
                    logger.error("Could not launch isolated Chrome context: %s", e)
            
            if not session_context:
                import os
                profile_dir_env = os.environ.get("JOB_AGENT_PROFILE_DIR")
                if profile_dir_env:
                    profile_dir = str(PROJECT_ROOT / profile_dir_env if not Path(profile_dir_env).is_absolute() else profile_dir_env)
                else:
                    profile_dir = str(config.browser_profile_dir)
                profile_path = Path(profile_dir)
                if profile_path.is_dir():
                    for lock_pattern in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                        lock_file = profile_path / lock_pattern
                        if lock_file.exists():
                            try:
                                lock_file.unlink()
                                logger.debug("Removed stale browser lock: %s", lock_file)
                            except Exception:
                                pass
                logger.info("Launching Chrome persistent context on profile: %s (headless=%s)", profile_dir, HEADLESS)
                try:
                    session_context = cdp_pw.chromium.launch_persistent_context(
                        user_data_dir=profile_dir,
                        executable_path=chrome_path if Path(chrome_path).exists() else None,
                        channel="chrome" if not Path(chrome_path).exists() else None,
                        headless=HEADLESS,
                        user_agent=config.user_agent,
                        args=["--disable-blink-features=AutomationControlled"],
                        ignore_default_args=["--enable-automation"],
                        viewport={"width": 1280, "height": 800},
                    )
                    try:
                        from playwright_stealth import Stealth
                        Stealth().apply_stealth_sync(session_context)
                    except Exception:
                        pass
                    logger.info("⚡ LAUNCHED BROWSER CONTEXT WITH SAVED PROFILE SUCCESSFULLY!")
                except Exception as e:
                    logger.error("Could not launch Chrome context: %s", e)
                    print(f"\n❌ Failed to launch Chrome context: {e}")
                    if cdp_pw:
                        try:
                            cdp_pw.stop()
                        except Exception:
                            pass
                    return

        # Inject fresh li_at and JSESSIONID cookie tokens if provided via CLI or .env
        if COOKIE_TOKEN and session_context:
            try:
                cookies_to_add = [{
                    "name": "li_at",
                    "value": COOKIE_TOKEN,
                    "domain": ".linkedin.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                }]
                if JSESSIONID_TOKEN:
                    cookies_to_add.append({
                        "name": "JSESSIONID",
                        "value": JSESSIONID_TOKEN.strip('"'),
                        "domain": ".linkedin.com",
                        "path": "/",
                        "httpOnly": False,
                        "secure": True,
                    })
                if BCOOKIE_TOKEN:
                    cookies_to_add.append({
                        "name": "bcookie",
                        "value": BCOOKIE_TOKEN.strip('"'),
                        "domain": ".linkedin.com",
                        "path": "/",
                        "httpOnly": False,
                        "secure": True,
                    })
                if BSCOOKIE_TOKEN:
                    cookies_to_add.append({
                        "name": "bscookie",
                        "value": BSCOOKIE_TOKEN.strip('"'),
                        "domain": ".linkedin.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                    })
                session_context.add_cookies(cookies_to_add)
                cookie_names = [c["name"] for c in cookies_to_add]
                logger.info("Injected synchronized LinkedIn session cookies (%s) into browser context.", " + ".join(cookie_names))
            except Exception as ce:
                logger.warning("Could not inject cookie token: %s", ce)

        # Ensure we have an active tab on LinkedIn feed
        page = session_context.pages[0] if session_context.pages else session_context.new_page()
        if "linkedin.com/feed" not in page.url.lower():
            logger.info("Navigating to https://www.linkedin.com/feed/ to verify session...")
            try:
                page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning("Feed load notice: %s", e)
        page.bring_to_front()

        # Check authentication across open tabs
        def is_authenticated() -> bool:
            try:
                for p in session_context.pages:
                    url = p.url.lower()
                    if "feed" in url and "login" not in url and "authwall" not in url:
                        return True
                    if p.locator("#global-nav, .global-nav").count() > 0:
                        return True
            except Exception:
                pass
            return False

        if not is_authenticated():
            print_separator("═")
            print("  🔐 LINKEDIN LOGIN REQUIRED")
            print("  Please complete sign-in in the open Chrome browser window.")
            print("  (Click 'Sign in with Google' or enter your LinkedIn credentials)")
            print("  Waiting up to 600 seconds (detecting login in real time)...")
            print_separator("═")
            logger.info("🔐 LINKEDIN LOGIN REQUIRED: Waiting up to 600s for sign-in...")
            try:
                page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                logger.warning("Login navigation note: %s", e)

            logged_in = False
            for sec in range(600):
                if is_authenticated():
                    logged_in = True
                    print(f"\n✅ LinkedIn login confirmed after {sec}s! Proceeding with scan...", flush=True)
                    # Pick the feed tab
                    for p in session_context.pages:
                        if "feed" in p.url.lower():
                            page = p
                            break
                    page.wait_for_timeout(2000)
                    break
                if sec > 0 and sec % 30 == 0:
                    logger.info("Waiting for login... (%ds elapsed, %ds remaining)", sec, 600 - sec)
                time.sleep(1)

            if not logged_in:
                logger.error("Authentication wait timed out after 600 seconds.")
                print("\n❌ Login wait timed out. Please run again when ready.")
                try:
                    if session_context:
                        session_context.close()
                    cdp_pw.stop()
                except Exception:
                    pass
                return

        logger.info("Session verified. Beginning sweep...")
        if single_post_url:
            logger.info("Direct single-post mode: navigating to %s", single_post_url)
            page.goto(single_post_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(3000)
            text = (page.inner_text("body") or "").strip()
            scanner = LinkedInPostScanner(page=page, logger_inst=logger)
            card = {"text": text, "url": single_post_url, "time_text": "today"}
            lead = scanner._parse_post_card(card)
            if lead:
                all_leads.append(lead)
            else:
                print(f"\n⚠️ Post at {single_post_url} did not qualify or is older than 3 weeks.")
                try:
                    cdp_pw.stop()
                except Exception:
                    pass
                return
        else:
            scanner = LinkedInPostScanner(page=page, logger_inst=logger)
            all_leads = scanner.scan_all_queries(
                max_pages_per_query=MAX_PAGES_PER_QUERY,
                max_posts_per_page=MAX_POSTS_PER_QUERY,
                scroll_times=SCROLL_TIMES,
                delay_between_queries=DELAY_BETWEEN_QUERIES,
            )

        try:
            if cdp_browser:
                cdp_browser.close()
            elif browser_inst:
                browser_inst.close()
            elif session_context:
                session_context.close()
            if cdp_pw:
                cdp_pw.stop()
        except Exception:
            pass

    # Kill Ollama if it was started (conserve RAM)
    if ollama_client:
        try:
            ollama_client.stop_server()
        except Exception:
            pass

    # ─── RESULTS SUMMARY ──────────────────────────────────────────────────────
    print_separator("═")
    print(f"  📊 Scan Complete — Found {len(all_leads)} qualifying LinkedIn posts with email instructions")
    print_separator("═")

    if not all_leads:
        logger.info("No qualifying posts found in this sweep. Try again later or adjust queries.")
        print("\nNo qualifying posts found. Possible reasons:")
        print("  • LinkedIn feed doesn't have fresh posts for these queries today")
        print("  • LinkedIn session may need refreshing")
        print("  • Selectors may need updating if LinkedIn changed UI")
        return

    # ─── EMAIL SEND LOOP ──────────────────────────────────────────────────────
    sent_count = 0
    skipped_dup = 0
    skipped_no_email = 0
    failed_count = 0

    for index, lead in enumerate(all_leads, start=1):
        print_lead_summary(lead, index, len(all_leads))

        if not lead.email_addresses:
            logger.warning("No email address found for lead: %s", lead.post_url[:60])
            skipped_no_email += 1
            continue

        for to_email in lead.email_addresses:
            # Deduplication check
            if tracker.is_already_sent(lead.post_url, to_email):
                logger.info("SKIP (already sent): %s → %s", to_email, lead.post_url[:60])
                skipped_dup += 1
                continue

            # Compose cover email
            try:
                html_body, plain_body = composer.compose(
                    role=lead.role,
                    company=lead.company,
                    poster_name=lead.poster_name,
                    skills_mentioned=lead.skills_mentioned,
                    job_context=lead.raw_snippet,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to compose email for %s: %s", to_email, exc)
                tracker.record_attempt(
                    post_url=lead.post_url,
                    poster_name=lead.poster_name,
                    company=lead.company,
                    role=lead.role,
                    email_to=to_email,
                    email_subject=lead.subject_line,
                    email_body="",
                    status="failed",
                    reason=f"Compose error: {exc}",
                    post_age=lead.post_age,
                )
                failed_count += 1
                continue

            if DRY_RUN:
                print(f"\n  📧 [DRY RUN] Email composition preview:")
                print(f"  To      : {to_email}")
                print(f"  Subject : {lead.subject_line}")
                print(f"  Age     : {lead.post_age}")
                print(f"  Body preview:")
                print(f"  {plain_body[:400]}...")
                print()
                tracker.record_attempt(
                    post_url=lead.post_url,
                    poster_name=lead.poster_name,
                    company=lead.company,
                    role=lead.role,
                    email_to=to_email,
                    email_subject=lead.subject_line,
                    email_body=plain_body,
                    status="dry_run",
                    reason="DRY RUN — not sent",
                    post_age=lead.post_age,
                )
                sent_count += 1
                continue

            # LIVE send
            ok, message = email_sender.send_application_email(
                to_email=to_email,
                subject=lead.subject_line,
                body_html=html_body,
                resume_path=resume_path,
                cc_email=None,
                bcc_email=profile.email,  # BCC copy sent directly to candidate
                plain_body=plain_body,
                dry_run=False,
            )

            status = "sent" if ok else "failed"
            tracker.record_attempt(
                post_url=lead.post_url,
                poster_name=lead.poster_name,
                company=lead.company,
                role=lead.role,
                email_to=to_email,
                email_subject=lead.subject_line,
                email_body=plain_body,
                status=status,
                reason=message,
                post_age=lead.post_age,
            )

            if ok:
                sent_count += 1
                logger.info("[SENT] %s → %s | Subject: %s", to_email, lead.role, lead.subject_line)
            else:
                failed_count += 1
                logger.error("[FAILED] %s → %s | Reason: %s", to_email, lead.role, message)

            # Throttle sends to be respectful (avoid Gmail rate limits)
            if not DRY_RUN:
                time.sleep(random.uniform(3.0, 5.0))

    # ─── FINAL REPORT ─────────────────────────────────────────────────────────
    print_separator("═")
    print("  🏁 LinkedIn Post Email Applier — Sweep Complete")
    print_separator()
    print(f"  Total leads found          : {len(all_leads)}")
    print(f"  Emails {'composed (dry run)' if DRY_RUN else 'sent successfully'} : {sent_count}")
    print(f"  Skipped (already sent)     : {skipped_dup}")
    print(f"  Skipped (no email found)   : {skipped_no_email}")
    print(f"  Failed                     : {failed_count}")
    if DRY_RUN:
        print()
        print("  ⚠️  DRY RUN complete. Set DRY_RUN = False at the top of this script to send actual emails.")
    print_separator("═")

    final_stats = tracker.get_stats()
    logger.info("Final linkedin_post_emails DB stats: %s", final_stats)


if __name__ == "__main__":
    main()
