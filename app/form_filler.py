from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page

from app.forms.selector_cache import SelectorCache
from app.profile_loader import lookup_saved_answer, lookup_saved_answer_fuzzy, save_answer_templates
from app.utils import (
    CAPTCHA_KEYWORDS,
    FillResult,
    JobPosting,
    MatchResult,
    ProfileData,
    SENSITIVE_DATA_KEYWORDS,
    compact_whitespace,
    normalize_key,
)

# Kept identical on the JS and Python sides so field["index"] always refers to the
# same element in both the scan and the locator used to act on it.
FIELD_SELECTOR = "input, textarea, select, [role='combobox'], [role='listbox'], [aria-haspopup='listbox']"

LLM_REFUSAL_PATTERNS = (
    "cannot answer",
    "cannot create",
    "cannot provide",
    "cannot assist",
    "can't assist",
    "can't help",
    "could not find",
    "couldn't find",
    "don't have access",
    "do not have access",
    "don't provide",
    "do not provide",
    "do not create",
    "will not answer",
    "won't answer",
    "as an ai",
    "i am an ai",
    "ai language model",
    "language model",
    "safety guidelines",
    "against policy",
    "sensitive systems",
    "malicious purposes",
    "malicious activities",
    "derogatory language",
    "hate speech",
    "adult content",
    "fraudulent purposes",
    "is there anything else",
    "can i help you with",
    "is there another question",
    "here's a tailored",
    "here is a tailored",
    "i am unable",
    "im unable",
    "cannot create content",
)


def is_refusal_or_invalid_answer(answer: str, label: str = "", allow_empty: bool = False) -> bool:
    if not answer or not answer.strip():
        return not allow_empty
    norm = normalize_key(answer)
    norm_label = normalize_key(label)
    for pattern in LLM_REFUSAL_PATTERNS:
        norm_p = normalize_key(pattern)
        if norm_p and norm_p in norm:
            if "disability" in norm_label and "have a disability" in norm:
                continue
            if "veteran" in norm_label and ("not a protected veteran" in norm or "decline" in norm):
                continue
            return True
    return False

FIELD_SCAN_JS = """
(elements) => {
  return elements.map((el, index) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const nameOrId = ((el.getAttribute("name") || "") + " " + (el.id || "")).toLowerCase();
    const isCaptchaHoneypot = nameOrId.includes("recaptcha") || nameOrId.includes("turnstile") || nameOrId.includes("cf-chl") || nameOrId.includes("hcaptcha") || nameOrId.includes("bot-field");
    const visible = !isCaptchaHoneypot && !!(rect.width || rect.height) && style.visibility !== "hidden" && style.display !== "none" && parseFloat(style.opacity || "1") > 0;
    const labelTexts = [];
    if (el.labels) {
      labelTexts.push(...Array.from(el.labels).map(item => item.innerText || item.textContent || ""));
    }
    if (el.id) {
      const root = el.getRootNode();
      const byFor = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (byFor) {
        labelTexts.push(byFor.innerText || byFor.textContent || "");
      }
    }
    const parentLabel = el.closest("label");
    if (parentLabel) {
      labelTexts.push(parentLabel.innerText || parentLabel.textContent || "");
    }
    const fieldset = el.closest("fieldset");
    const legend = fieldset?.querySelector("legend")?.innerText || "";
    const tag = el.tagName.toLowerCase();
    const isAriaWidget = tag !== "input" && tag !== "textarea" && tag !== "select";
    const role = el.getAttribute("role") || "";
    const listId = el.getAttribute("aria-controls") || el.getAttribute("aria-owns") || "";
    let ariaOptions = [];
    if (isAriaWidget && listId) {
      const root = el.getRootNode();
      const listEl = root.getElementById ? root.getElementById(listId) : root.querySelector(`#${CSS.escape(listId)}`);
      if (listEl) {
        ariaOptions = Array.from(listEl.querySelectorAll("[role='option']")).map(opt => ({
          text: (opt.innerText || opt.textContent || "").trim(),
        }));
      }
    }
    return {
      index,
      tag,
      type: isAriaWidget ? "aria-" + (role || "combobox") : (el.getAttribute("type") || el.tagName).toLowerCase(),
      isAriaWidget,
      ariaOptionsFound: ariaOptions.length,
      ariaOptions,
      name: el.getAttribute("name") || "",
      id: el.id || "",
      placeholder: el.getAttribute("placeholder") || "",
      ariaLabel: el.getAttribute("aria-label") || "",
      accept: el.getAttribute("accept") || "",
      required: el.required || el.getAttribute("aria-required") === "true",
      disabled: !!el.disabled || el.getAttribute("readonly") !== null || el.getAttribute("aria-disabled") === "true",
      visible,
      legend,
      labelTexts,
      options: tag === "select"
        ? Array.from(el.options).map(option => ({ text: option.textContent || "", value: option.value || "" }))
        : []
    };
  });
}
"""

# ── Fresher Experience Option Priority Tiers ──────────────────────────────────
# User directive: Choose experience as 6 months or 0-1 or other entry-level options
FRESHER_EXP_TIER1 = [
    re.compile(r"\b0\s*[-–to]\s*6\s*m(?:onths?)?\b", re.IGNORECASE),
    re.compile(r"\b6\s*m(?:onths?)?\b", re.IGNORECASE),
    re.compile(r"\b(?:less\s*than|<|under)\s*1\s*(?:years?|yrs?|yr)?\b", re.IGNORECASE),
    re.compile(r"\b<\s*1\b", re.IGNORECASE),
    re.compile(r"\b0\.5\s*(?:years?|yrs?|yr)?\b", re.IGNORECASE),
]

FRESHER_EXP_TIER2 = [
    re.compile(r"\b0\s*[-–to]\s*1\s*(?:years?|yrs?|yr)?\b", re.IGNORECASE),
    re.compile(r"\b0\s*[-–]\s*1\b", re.IGNORECASE),
    re.compile(r"\b0\.0\s*[-–]\s*1\.0\b", re.IGNORECASE),
]

FRESHER_EXP_TIER3 = [
    re.compile(r"\bfresher\b", re.IGNORECASE),
    re.compile(r"\bfresh\s*graduate\b", re.IGNORECASE),
    re.compile(r"\bentry[\s-]level\b", re.IGNORECASE),
    re.compile(r"\bbeginner\b", re.IGNORECASE),
    re.compile(r"\btrainee\b", re.IGNORECASE),
    re.compile(r"\bintern(?:ship)?\b", re.IGNORECASE),
    re.compile(r"\b0\s*(?:years?|yrs?|yr)\b", re.IGNORECASE),
    re.compile(r"\bnone\b", re.IGNORECASE),
    re.compile(r"\bno\s*experience\b", re.IGNORECASE),
    re.compile(r"^0$", re.IGNORECASE),
]

FRESHER_EXP_TIER4 = [
    re.compile(r"\b1\s*(?:years?|yrs?|yr)\b", re.IGNORECASE),
    re.compile(r"\b1\s*[-–to]\s*2\s*(?:years?|yrs?|yr)?\b", re.IGNORECASE),
    re.compile(r"\b1\s*[-–to]\s*3\s*(?:years?|yrs?|yr)?\b", re.IGNORECASE),
    re.compile(r"^1$", re.IGNORECASE),
]


class FormFiller:
    def __init__(self, config, logger, ollama_client, non_interactive: bool = False) -> None:
        self.config = config
        self.logger = logger
        self.ollama_client = ollama_client
        self.templates: dict[str, Any] = {}
        self.non_interactive = non_interactive
        cache_path = getattr(config, "templates_dir", None)
        self.selector_cache = SelectorCache(cache_path / "selector_cache.json" if cache_path else None)

    def set_templates(self, templates: dict[str, Any]) -> None:
        self.templates = templates

    def heal_and_fill_unknown_field(
        self,
        page: Page,
        field_dict: dict[str, Any],
        domain: str,
        answer_map: dict[str, str],
    ) -> str | None:
        """
        Self-healing DOM resolver: extracts question context from field dict / HTML,
        deduces the intended profile answer, identifies the CSS locator, and records
        the working selector in selector_cache.json.
        """
        labels = " ".join(field_dict.get("labelTexts", []))
        question_text = field_dict.get("placeholder") or field_dict.get("ariaLabel") or field_dict.get("name") or labels
        if not question_text:
            return None

        # Check cache first
        cached_selector = self.selector_cache.get_selector(domain, question_text)
        if cached_selector:
            try:
                target = page.locator(cached_selector).first
                if target.count() and target.is_visible():
                    return cached_selector
            except Exception:
                pass

        # Try to match question_text to an answer in answer_map
        matched_answer = None
        norm_q = normalize_key(question_text)
        for k, v in answer_map.items():
            if normalize_key(k) in norm_q or norm_q in normalize_key(k):
                matched_answer = v
                break

        if not matched_answer:
            return None

        # Build stable CSS selector for the field
        field_name = field_dict.get("name")
        field_id = field_dict.get("id")
        aria_label = field_dict.get("ariaLabel")
        tag = field_dict.get("tag", "input")

        selector = None
        if field_name:
            selector = f"{tag}[name='{field_name}']"
        elif field_id:
            selector = f"#{field_id}"
        elif aria_label:
            selector = f"{tag}[aria-label='{aria_label}']"

        if selector:
            self.selector_cache.record_selector(domain, question_text, selector)
        return selector

    def fill(
        self,
        page: Page,
        job: JobPosting,
        match: MatchResult,
        profile: ProfileData,
        auto_submit_safe: bool = False,
    ) -> tuple[FillResult, Page]:
        # Check if already applied
        if self._check_already_applied(page):
            result = FillResult(status="applied")
            self.logger.info("Detected 'Already Applied' status on job board.")
            return result, page

        # EXPIRED JOB DETECTION:
        if "naukri.com" in job.url and "job-listings" not in page.url:
            self.logger.warning("Naukri job expired/redirected to generic search.")
            result = FillResult(status="skipped")
            result.errors.append("Job expired (redirected to search).")
            return result, page
            
        if "linkedin.com" in job.url:
            try:
                page.wait_for_timeout(2000)
                if page.title() == "Jobs | LinkedIn" or page.locator("text='No longer accepting applications'").count() > 0 or page.locator("text='This job is closed'").count() > 0:
                    self.logger.warning("LinkedIn job is closed or expired.")
                    result = FillResult(status="skipped")
                    result.errors.append("LinkedIn job closed.")
                    return result, page
            except Exception:
                pass

        active_page = self._ensure_application_form_open(page)
        result = FillResult(status="filled_pending_submit")

        # ── Mobile / SMS OTP check — attempt auto-read via Phone Link / ADB ──
        mobile_otp_patterns = (
            "mobile otp",
            "sms verification",
            "phone verification",
            "text code to your phone",
            "sent to your mobile",
            "sent to your phone",
            "sms otp",
            "otp sent to your registered mobile",
            "enter otp",
            "enter the otp",
            "otp sent",
            "verification code sent",
            "enter verification code",
            "one time password",
            "one-time password",
        )
        page_text = ""
        try:
            page_text = compact_whitespace(active_page.locator("body").inner_text(timeout=3000)).lower()
        except Exception:
            pass

        has_otp_element = False
        try:
            has_otp_element = active_page.locator("input[placeholder*='otp' i], input[name*='otp' i], input[id*='otp' i], input[aria-label*='otp' i], input.otp-input").count() > 0
        except Exception:
            pass

        if any(p in page_text for p in mobile_otp_patterns) or has_otp_element:
            self.logger.info("Mobile/SMS OTP gate detected — attempting auto-read via Phone Link / ADB...")
            sms_otp = self._handle_sms_otp_gate(active_page)
            if not sms_otp:
                result.status = "needs_manual_input"
                result.submit_blockers.append("Mobile/SMS OTP required")
                self.logger.warning("SMS OTP auto-read failed — deferred for manual handling.")
                return result, active_page

        # ── Registration Gate: create account / register on company site ──
        self._handle_registration_gate(active_page)

        # ── Email OTP Gate: read verification code from Gmail via IMAP ──
        otp_handled = self._handle_otp_gate(active_page)

        # ── Residual Blockers (CAPTCHA traps, unsolved gates) ──
        blockers = self._detect_blockers(active_page)
        if blockers:
            unhandled = [b for b in blockers if b not in ("otp", "verification code", "email verification")]
            # Only block on OTP if an OTP field is still present after IMAP attempt
            if any(b in ("otp", "verification code", "email verification") for b in blockers) and not otp_handled:
                unhandled.append("Unresolved OTP field")
            if unhandled:
                result.status = "needs_manual_input"
                result.submit_blockers.extend(unhandled)
                self.logger.warning("Application blocked by verification gate: %s", ", ".join(unhandled))
                return result, active_page

        material = self.ollama_client.generate_application_material(job, profile)
        answer_map = self._build_answer_map(profile, material)
        if material.get("used_fallback"):
            result.guessed_fields.extend(["cover_letter", "experience_summary"])
        seen_field_signatures: set[tuple] = set()
        for step in range(1, 8):
            fields = self._collect_fields(active_page)

            visible_fields = [f for f in fields if f.get("visible") and not f.get("disabled")]
            sig = tuple(sorted(str(f.get("id") or f.get("name") or f.get("index")) for f in visible_fields))
            if sig and sig in seen_field_signatures:
                self.logger.warning("Application step did not advance after action (unfulfilled validation or required field).")
                result.status = "needs_manual_input"
                result.errors.append("Application step did not advance (validation/required field).")
                break
            if sig:
                seen_field_signatures.add(sig)
            
            # IFRAME SUPPORT: If no fields found, check if they are hidden inside an iframe
            if not fields and hasattr(active_page, "frames"):
                best_frame = None
                max_fields = 0
                for frame in active_page.frames:
                    try:
                        frame_fields = self._collect_fields(frame)
                        if len(frame_fields) > max_fields:
                            max_fields = len(frame_fields)
                            best_frame = frame
                    except Exception:
                        pass
                if best_frame and max_fields > 0:
                    self.logger.info("Switched active context to an iframe containing %d fields", max_fields)
                    active_page = best_frame
                    fields = self._collect_fields(active_page)

            if not fields:
                # 1. Check if already submitted / applied
                if self._check_already_applied(active_page):
                    result.status = "applied"
                    return result, active_page

                if self._check_job_expired(active_page):
                    result.status = "skipped"
                    result.errors.append("Job posting has expired or is no longer accepting applications.")
                    return result, active_page

                # 2. Check if a submit button is ready
                if self._has_submit_button(active_page):
                    break

                # 3. Check if there's a Next / Continue / Review button
                if self._advance_application_step(active_page):
                    continue

                # 4. Don't bail immediately — Naukri and ATS sites need time to render
                # their React/JS form after clicking Apply. Retry up to 3 times.
                if step <= 3:
                    self.logger.info("No fields found on step %d — waiting and retrying...", step)
                    # Try clicking every Apply button variant aggressively
                    for apply_selector in [
                        "button#apply-button", "button.apply-button",
                        "button:has-text('Apply')", "a:has-text('Apply Now')",
                        "button:has-text('Apply Now')", "[data-testid='apply-button']",
                    ]:
                        try:
                            btn = active_page.locator(apply_selector)
                            if btn.count() > 0 and btn.first.is_visible():
                                btn.first.click(timeout=3000)
                                self.logger.info("Clicked Apply button via '%s'", apply_selector)
                                break
                        except Exception:
                            pass
                    active_page.wait_for_timeout(5000)
                    # Re-check if a new tab opened (company site redirect)
                    if hasattr(active_page, "context") and len(active_page.context.pages) > 1:
                        active_page = active_page.context.pages[-1]
                        active_page.wait_for_timeout(3000)
                    continue

                if self._check_already_applied(active_page):
                    result.status = "applied"
                    return result, active_page

                if self._check_job_expired(active_page):
                    result.status = "skipped"
                    result.errors.append("Job posting has expired or is no longer accepting applications.")
                    return result, active_page

                result.status = "needs_manual_input"
                result.errors.append("No fillable form fields detected.")
                return result, active_page

            for field in fields:
                if not field["visible"] or field["disabled"]:
                    continue

                category = self._classify_field(field)
                label = self._label_for_field(field)

                # ── STABLE LOCATOR: prefer id/name over fragile nth(index) ──
                # Dynamic ATS pages (Greenhouse, Workday) inject invisible CAPTCHA
                # textareas mid-page, shifting nth counts and causing false timeouts.
                field_id = field.get("id", "")
                field_name = field.get("name", "")
                if field_id:
                    # Use attribute selector [id='...'] instead of #... because CSS IDs cannot start with a digit
                    locator = active_page.locator(f"[id='{field_id}']").first
                elif field_name:
                    locator = active_page.locator(f"[name='{field_name}']").first
                else:
                    locator = active_page.locator(FIELD_SELECTOR).nth(field["index"])

                # ── RUNTIME CAPTCHA GUARD ──
                # Dynamically injected CAPTCHA textareas can shift nth() positions
                # after the initial scan. Always verify the resolved element before filling.
                try:
                    resolved_name = locator.get_attribute("name", timeout=1000) or ""
                    resolved_id = locator.get_attribute("id", timeout=1000) or ""
                    resolved_combo = (resolved_name + " " + resolved_id).lower()
                    if any(kw in resolved_combo for kw in ("captcha", "turnstile", "cf-chl")):
                        self.logger.debug("Skipping dynamically-injected CAPTCHA trap: %s", resolved_combo)
                        continue
                except Exception:
                    pass

                if category in {"ignore", "submit"}:
                    continue

                if category == "resume_upload":
                    self._upload_resume(locator, label, result, job=job, profile=profile, page=active_page)
                    continue

                if category == "photo_upload":
                    self._upload_photo(locator, label, result)
                    continue

                if category == "consent":
                    self._handle_consent(locator, label, result)
                    continue

                if category == "blocked_sensitive":
                    result.status = "needs_manual_input"
                    result.submit_blockers.append(f"Sensitive field requires manual handling: {label}")
                    result.skipped_fields.append(label)
                    continue

                answerable_categories = {"manual", "aria_dropdown"}

                # For dropdowns, get available options to constrain the matching/LLM answer
                dropdown_options: list[str] = []
                if category == "aria_dropdown":
                    dropdown_options = [o["text"] for o in field.get("ariaOptions", [])]
                elif field.get("tag") == "select":
                    dropdown_options = [o["text"] for o in field.get("options", [])]

                # 1. Direct answer from pre-built candidate answer map
                answer = answer_map.get(category)

                # 2. Domain smart auto-answer rule (Fresher rules: experience, notice period, CTC, work auth, shifts, relocation, gender)
                if not answer:
                    answer = self._smart_auto_answer(label, field, job, profile, dropdown_options or None)
                    if answer:
                        self.logger.info("Resolved field %r via smart auto-answer rule: %r", label, answer)

                # 3. Candidate profile custom answers / clean templates lookup
                if not answer:
                    answer = lookup_saved_answer(label, self.templates, profile)

                # 4. Fuzzy match against verified profile questions
                if not answer and category in answerable_categories:
                    answer = self._resolve_via_fuzzy_match(label, profile)

                # 5. LLM question resolution for novel / technical questions
                if not answer and category in answerable_categories:
                    answer = self._resolve_via_llm(label, job, profile, dropdown_options or None)
                    if answer:
                        self._remember_answer(label, answer)

                # 6. Interactive prompt fallback (if interactive mode enabled)
                if not answer and category in answerable_categories:
                    answer = self._prompt_unknown_answer(label, store_answer=True)
                    if answer:
                        self._remember_answer(label, answer)

                # 7. Fail-safe auto-answer for required fields
                if not answer and field.get("required"):
                    answer = dropdown_options[0] if dropdown_options else "Yes"
                    self.logger.info("Applied fail-safe auto-answer for required field %r: %r", label, answer)

                if answer and category == "aria_dropdown":
                    self._fill_aria_dropdown(locator, field, answer, label, result)
                elif answer:
                    self._fill_locator(locator, field, answer, label, result)
                else:
                    result.skipped_fields.append(label)

            ready = not result.submit_blockers and not result.errors and not result.unknown_questions
            result.ready_to_submit = ready
            if not ready:
                break
            if not self._advance_application_step(active_page):
                break

        # External ATS and company sites will now proceed to the auto-submit block below

        if auto_submit_safe and self._can_auto_submit(job, match, result):
            submitted, message = self.submit_final(active_page, explicit_confirmation=False)
            if submitted:
                result.status = "applied"
                result.auto_submitted = True
            elif any(marker in message.lower() for marker in ("verification gate", "captcha", "otp")):
                result.status = "needs_manual_input"
                result.submit_blockers.append(message)
            else:
                result.status = "failed"
                result.errors.append(message)

        self.logger.info(
            "Form fill result | status=%s | ready=%s | filled=%s | unknown=%s",
            result.status,
            result.ready_to_submit,
            len(result.filled_fields),
            len(result.unknown_questions),
        )
        return result, active_page

    def _handle_registration_gate(self, page: Page) -> bool:
        """Detect and fill a company-site registration form. Returns True if registration was attempted."""
        try:
            # Guard: Credentials must be configured
            if not (self.config.company_site_login_email and self.config.company_site_login_password):
                return False

            # Guard: Must be secure HTTPS connection
            current_url = page.url.lower()
            if not current_url.startswith("https://"):
                return False

            # Guard: Never auto-register on major identity or job board domains
            from app.utils import domain_from_url
            domain = domain_from_url(page.url).lower()
            protected_domains = ("linkedin.com", "naukri.com", "google.com", "github.com", "microsoft.com")
            if any(pd in domain for pd in protected_domains):
                return False

            has_password = page.locator("input[type='password']").count() > 0
            if not has_password:
                return False
            has_email = page.locator("input[type='email'], input[name*='email' i], input[placeholder*='email' i]").count() > 0
            if not has_email:
                return False
            register_pattern = re.compile(r"register|sign\s*up|create\s*account|get\s*started", re.IGNORECASE)
            register_btn = page.get_by_role("button", name=register_pattern)
            if not register_btn.count():
                return False
            email_field = page.locator("input[type='email'], input[name*='email' i], input[placeholder*='email' i]").first
            if email_field.is_visible():
                email_field.fill(self.config.company_site_login_email)
            for pw_field in page.locator("input[type='password']").all():
                if pw_field.is_visible():
                    pw_field.fill(self.config.company_site_login_password)
            register_btn.first.click()
            page.wait_for_timeout(3000)
            self.logger.info("Registration gate on %s: filled and clicked register button.", domain)
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Registration gate detection failed: %s", exc)
            return False

    def _handle_otp_gate(self, page: Page) -> bool:
        """Detect an OTP entry field, fetch OTP from inbox, and fill it. Returns True if handled."""
        try:
            from app.otp_reader import OtpReader  # noqa: PLC0415
            otp_label_pattern = re.compile(r"otp|one.time|verification\s*code|enter.*code", re.IGNORECASE)
            otp_field = None
            for field in page.locator("input[type='text'], input[type='number'], input[type='tel']").all():
                try:
                    placeholder = field.get_attribute("placeholder") or ""
                    aria_label = field.get_attribute("aria-label") or ""
                    name_attr = field.get_attribute("name") or ""
                    combined = " ".join([placeholder, aria_label, name_attr])
                    if otp_label_pattern.search(combined):
                        otp_field = field
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not otp_field:
                return False
            if not (self.config.otp_email_address and self.config.otp_email_app_password):
                self.logger.warning("OTP field found but OTP_EMAIL_ADDRESS / OTP_EMAIL_APP_PASSWORD not set in .env")
                return False
            
            self.logger.info("OTP field detected. Fetching securely via IMAP backend...")
            
            reader = OtpReader(
                host=self.config.otp_email_imap_host,
                address=self.config.otp_email_address,
                app_password=self.config.otp_email_app_password,
                logger=self.logger,
            )
            otp = reader.fetch_latest_otp(wait_seconds=45, poll_interval=5)
            if not otp:
                self.logger.warning("Could not fetch OTP from email inbox — trying SMS fallback...")
                otp = self._fetch_sms_otp()

            if not otp:
                self.logger.warning("Could not fetch OTP from any source (email IMAP or SMS).")
                return False

            otp_field.fill(otp)
            page.wait_for_timeout(500)
            for label in ("verify", "confirm", "next", "continue", "submit"):
                btn = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
                if btn.count():
                    btn.first.click()
                    page.wait_for_timeout(2000)
                    break
            self.logger.info("OTP gate: successfully entered OTP.")
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("OTP gate detection failed: %s", exc)
            return False

    def _fetch_email_otp(self, wait_seconds: int = 25) -> str | None:
        """Read the latest OTP from Gmail inbox via IMAP."""
        try:
            if not (self.config.otp_email_address and self.config.otp_email_app_password):
                return None
            from app.otp_reader import OtpReader  # noqa: PLC0415
            reader = OtpReader(
                host=self.config.otp_email_imap_host,
                address=self.config.otp_email_address,
                app_password=self.config.otp_email_app_password,
                logger=self.logger,
            )
            return reader.fetch_latest_otp(wait_seconds=wait_seconds, poll_interval=5)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Email OTP reader error: %s", exc)
            return None

    def _fetch_sms_otp(self, wait_seconds: int = 45) -> str | None:
        """Read the latest OTP from SMS via Windows Phone Link DB or ADB."""
        try:
            from app.sms_otp_reader import SmsOtpReader  # noqa: PLC0415
            reader = SmsOtpReader(self.logger)
            return reader.fetch_latest_otp(wait_seconds=wait_seconds, poll_interval=5)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("SMS OTP reader error: %s", exc)
            return None

    def _handle_sms_otp_gate(self, page: Page) -> bool:
        """Find mobile OTP input fields, fetch SMS OTP via Phone Link / ADB, fill & submit.

        Returns True if OTP was successfully read and filled, False otherwise.
        """
        try:
            # Find the OTP input field
            otp_label_pattern = re.compile(r"otp|one.time|verification\s*code|enter.*code|mobile.*otp|sms.*otp", re.IGNORECASE)
            otp_field = None
            for field in page.locator("input[type='text'], input[type='number'], input[type='tel'], input[type='password']").all():
                try:
                    placeholder = field.get_attribute("placeholder") or ""
                    aria_label = field.get_attribute("aria-label") or ""
                    name_attr = field.get_attribute("name") or ""
                    combined = " ".join([placeholder, aria_label, name_attr])
                    if otp_label_pattern.search(combined):
                        otp_field = field
                        break
                except Exception:  # noqa: BLE001
                    continue

            # If no labeled OTP field, look for multi-box segmented OTP inputs (e.g. 4-6 single-digit inputs)
            if not otp_field:
                multi_boxes = page.locator("input[maxlength='1'], input.otp-input, input[data-index]").all()
                if len(multi_boxes) in (4, 5, 6, 8):
                    otp = self._fetch_sms_otp(wait_seconds=45)
                    if not otp:
                        # Fail-safe: try email OTP fallback
                        self.logger.info("[SMS-OTP] SMS OTP timed out — checking email IMAP fallback...")
                        otp = self._fetch_email_otp(wait_seconds=20)
                    if not otp:
                        self.logger.warning("[SMS-OTP] Disconnection / timeout fail sequence: could not retrieve OTP.")
                        return False
                    for i, char in enumerate(otp[:len(multi_boxes)]):
                        try:
                            multi_boxes[i].fill(char)
                            page.wait_for_timeout(100)
                        except Exception:
                            pass
                    page.wait_for_timeout(800)
                    for label in ("verify", "confirm", "next", "continue", "submit", "validate"):
                        btn = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
                        if btn.count():
                            btn.first.click()
                            page.wait_for_timeout(2000)
                            break
                    self.logger.info("[SMS-OTP] Successfully filled multi-box OTP (%d digits): %s", len(multi_boxes), otp)
                    return True

            # If still no field, look for a single short text/number input
            if not otp_field:
                candidates = page.locator("input[type='text'], input[type='number'], input[type='tel']").all()
                for field in candidates:
                    try:
                        maxlen = field.get_attribute("maxlength") or ""
                        if maxlen and 4 <= int(maxlen) <= 8:
                            otp_field = field
                            break
                    except Exception:
                        continue

            if not otp_field:
                self.logger.warning("[SMS-OTP] Could not identify OTP input field on page.")
                return False

            otp = self._fetch_sms_otp(wait_seconds=45)
            if not otp:
                # Fail-safe: try email OTP fallback
                self.logger.info("[SMS-OTP] SMS OTP timed out — checking email IMAP fallback...")
                otp = self._fetch_email_otp(wait_seconds=20)
            if not otp:
                self.logger.warning("[SMS-OTP] Disconnection / timeout fail sequence: could not retrieve OTP.")
                return False

            otp_field.fill(otp)
            page.wait_for_timeout(800)
            for label in ("verify", "confirm", "next", "continue", "submit", "validate"):
                btn = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
                if btn.count():
                    btn.first.click()
                    page.wait_for_timeout(2000)
                    break
            self.logger.info("[SMS-OTP] Successfully filled and submitted mobile OTP: %s", otp)
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("[SMS-OTP] _handle_sms_otp_gate failed: %s", exc)
            return False

    @staticmethod
    def _check_already_applied(page: Page) -> bool:
        try:
            if page.locator("#already-applied, .already-applied, [data-applied='true']").count() > 0:
                return True
            for text_pattern in (
                "text='Already Applied'",
                "text='Already applied'",
                "text='Application submitted'",
                "text='You have already applied'",
                "text='Applied on'",
                "text='Applied today'",
                "text='Lamaran terkirim'",
                "button:has-text('Applied')",
                "span.already-applied",
            ):
                loc = page.locator(text_pattern)
                if loc.count() > 0 and loc.first.is_visible():
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _has_submit_button(page: Page) -> bool:
        for pattern in (
            r"submit application",
            r"submit",
            r"send application",
            r"save & apply",
            r"save and apply",
            r"apply without",
            r"update & apply",
            r"update and apply",
        ):
            try:
                if page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).count():
                    return True
            except Exception:  # noqa: BLE001
                continue
        for loc in (
            "button[type='submit']",
            "input[type='submit']",
            "[data-testid='apply-button']",
            "button.styles_submit-button__",
        ):
            try:
                if page.locator(loc).count() > 0:
                    return True
            except Exception:
                continue
        return False

    def _advance_application_step(self, page: Page) -> bool:
        for pattern in (r"^next$", r"^continue$", r"^review$", r"^review application$", r"^save and continue$", r"^save and next$"):
            try:
                button = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
                if button.count():
                    try:
                        button.first.click(timeout=5000)
                    except Exception:
                        button.first.evaluate("el => { el.removeAttribute('disabled'); el.removeAttribute('aria-disabled'); el.classList.remove('disabled'); el.style.display = 'block'; el.style.visibility = 'visible'; el.style.opacity = '1'; el.click(); }")
                    page.wait_for_timeout(1500)
                    self.logger.info("Advanced application step via %s button.", pattern)
                    return True
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Unable to advance application step with %s: %s", pattern, exc)
        return False

    def submit_final(self, page: Page, explicit_confirmation: bool = True) -> tuple[bool, str]:
        # Try to automatically solve reCAPTCHA using free audio transcription
        blockers = self._detect_blockers(page)
        if blockers:
            if "captcha" in blockers:
                self.logger.warning("CAPTCHA checkpoint detected on %s — routing to manual review for user resolution.", page.url)
                return False, "Submit blocked by verification gate: captcha"
            # If blocker is OTP or phone/SMS verification, attempt auto-read via connected phone before failing
            if any(b in ("otp", "verification code", "phone verification", "sms verification") for b in blockers):
                self.logger.info("Verification gate detected during submit: %s — attempting auto-read via SMS OTP...", ", ".join(blockers))
                if self._handle_sms_otp_gate(page):
                    page.wait_for_timeout(2000)
                    remaining = [b for b in self._detect_blockers(page) if b in ("otp", "verification code", "phone verification", "sms verification")]
                    if not remaining:
                        self.logger.info("SMS OTP successfully resolved verification gate during submit!")
                        return True, "submitted via SMS OTP verification"
            return False, f"Submit blocked by verification gate: {', '.join(blockers)}"

        # Check if a "Review" button must be clicked first (e.g. LinkedIn Easy Apply multi-step)
        for review_pattern in (r"^review$", r"^review application$", r"^review your application$"):
            btn = page.get_by_role("button", name=re.compile(review_pattern, re.IGNORECASE))
            if btn.count() and btn.first.is_visible():
                try:
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    self.logger.info("Clicked Review button before final submit.")
                    break
                except Exception:
                    pass

        submit_patterns = [
            r"^submit application$",
            r"^submit$",
            r"^send application$",
            r"^apply now$",
            r"^apply$",
            r"^finish application$",
            r"^save & apply$",
            r"^save and apply$",
            r"^apply without",
            r"^update & apply$",
            r"^update and apply$",
        ]
        
        # 1. Try ARIA role="button"
        for pattern in submit_patterns:
            button = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
            if button.count():
                try:
                    button.first.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    self.logger.info("Clicked final submit/apply button (role=button).")
                    return True, "Application submitted."
                except Exception:
                    pass

        # 2. Try generic text locators, input[type=submit], etc.
        generic_locators = [
            "input[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Submit application')",
            "button[aria-label='Submit application']",
            "button:has-text('Apply Now')",
            "button:has-text('Send Application')",
            "a:has-text('Submit Application')",
            "button:has-text('Complete Application')",
            "button:has-text('Finish')",
            "button:has-text('Done')",
            "a:has-text('Submit')",
            "button:has-text('Save & Apply')",
            "button:has-text('Save and Apply')",
            "button:has-text('Apply without')",
            "button:has-text('Update & Apply')",
            "button:has-text('Update and Apply')",
            "button.application-submit",
            "button[data-automation-id='bottom-navigation-next-button']:has-text('Submit')",
            "input[value='Submit Application']",
            "input[value='Submit']",
            "button[type='submit']"
        ]
        
        for loc in generic_locators:
            elements = page.locator(loc)
            if elements.count():
                for idx in range(elements.count()):
                    try:
                        elements.nth(idx).click(timeout=3000)
                        page.wait_for_timeout(2000)
                        self.logger.info(f"Clicked final submit/apply button ({loc}).")
                        return True, "Application submitted."
                    except Exception:
                        pass
                
                # JS fallback using the exact Playwright element
                try:
                    elements.first.evaluate("el => { el.removeAttribute('disabled'); el.removeAttribute('aria-disabled'); el.classList.remove('disabled'); el.style.display = 'block'; el.style.visibility = 'visible'; el.style.opacity = '1'; el.click(); }")
                    page.wait_for_timeout(2000)
                    self.logger.info(f"Clicked final submit/apply button ({loc}) via JS fallback.")
                    return True, "Application submitted."
                except Exception:
                    pass

        # 3. Naukri-specific: check if modal is already open, if not open it, then submit
        if self._try_naukri_apply_flow(page):
            return True, "Application submitted via Naukri modal flow."

        return False, "No final submit button was found."

    def _try_naukri_apply_flow(self, page: Page) -> bool:
        """On Naukri listing pages, click 'Apply' to re-open the modal if needed, then submit."""
        if "naukri.com/job-listings" not in page.url:
            return False
        try:
            # Check if modal submit button is already visible before trying to open it
            modal_locators = [
                "button:has-text('Submit')",
                "button:has-text('Apply')",
                "button:has-text('Save & Apply')",
                "button:has-text('Save and Apply')",
                "button:has-text('Apply without')",
                "button:has-text('Update & Apply')",
                "button:has-text('Update and Apply')",
                "input[type='submit']",
                "[data-testid='apply-button']",
                "button.styles_submit-button__",
            ]
            
            modal_already_open = False
            for loc in modal_locators:
                if page.locator(loc).count() > 0:
                    modal_already_open = True
                    break
            
            if not modal_already_open:
                # Click Apply button to open the application modal
                apply_btn = page.locator("button#apply-button, button.apply-button, button:has-text('Apply')")
                if not apply_btn.count():
                    apply_btn = page.get_by_role("button", name=re.compile(r"^apply$", re.IGNORECASE))
                if apply_btn.count():
                    try:
                        apply_btn.first.click(timeout=5000)
                    except Exception:
                        apply_btn.first.evaluate("el => { el.removeAttribute('disabled'); el.removeAttribute('aria-disabled'); el.style.display = 'block'; el.style.visibility = 'visible'; el.click(); }")
                    page.wait_for_timeout(3000)
                    self.logger.info("Triggered Naukri Apply modal.")
            
            # Now click the inner submit button in the modal
            for loc in modal_locators:
                btn = page.locator(loc)
                if btn.count():
                    try:
                        btn.first.click(timeout=5000)
                    except Exception:
                        btn.first.evaluate("el => { el.removeAttribute('disabled'); el.removeAttribute('aria-disabled'); el.classList.remove('disabled'); el.style.display = 'block'; el.style.visibility = 'visible'; el.style.opacity = '1'; el.click(); }")
                    page.wait_for_timeout(2000)
                    self.logger.info("Submitted Naukri modal via %s", loc)
                    return True
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Naukri apply flow failed: %s", exc)
        return False


    def _ensure_application_form_open(self, page: Page) -> Page:
        active = page

        # Direct Naukri & standard ATS button locators
        direct_buttons = active.locator("#company-site-button, .company-site-button, #apply-button, .apply-button, [data-testid='apply-button']")
        if direct_buttons.count() > 0 and direct_buttons.first.is_visible():
            try:
                initial_count = len(active.context.pages) if hasattr(active, "context") else 1
                direct_buttons.first.click(timeout=5000)
                active.wait_for_timeout(3000)
                if hasattr(active, "context") and len(active.context.pages) > initial_count:
                    active = active.context.pages[-1]
                    active.wait_for_load_state("domcontentloaded")
                    active.wait_for_timeout(2000)
                    self.logger.info("Followed company-site-button to new tab: %s", active.url)
            except Exception as e:
                self.logger.debug("Direct apply button click failed: %s", e)

        patterns = [
            r"apply on company site",
            r"apply on company website",
            r"apply on company",
            r"company website",
            r"company site",
            r"easy apply",
            r"apply now",
            r"apply",
        ]
        
        for pattern in patterns:
            clicked = False
            # First try buttons, then links
            button = active.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
            if button.count():
                try:
                    button.first.click(timeout=5000)
                    clicked = True
                except Exception:
                    pass
            else:
                link = active.get_by_role("link", name=re.compile(pattern, re.IGNORECASE))
                if link.count():
                    try:
                        link.first.click(timeout=5000)
                        clicked = True
                    except Exception:
                        pass
            if clicked:
                active.wait_for_timeout(3000)
                active = active.context.pages[-1] if active.context.pages else active
                break
                
        # Check for Lever ATS
        if "lever.co" in active.url:
            self.logger.info("Detected Lever job page: %s", active.url)
            if not active.url.rstrip("/").endswith("/apply"):
                lever_apply = active.locator("a.postings-btn, a[href$='/apply'], a:has-text('Apply for this job'), a:has-text('Apply')")
                if lever_apply.count() > 0 and lever_apply.first.is_visible():
                    try:
                        lever_apply.first.click(timeout=5000)
                        active.wait_for_load_state("domcontentloaded")
                        active.wait_for_timeout(5000)
                        self.logger.info("Navigated to Lever form: %s", active.url)
                    except Exception as e:
                        self.logger.debug("Lever apply click failed: %s", e)
            else:
                active.wait_for_timeout(4000)

        # Check for Greenhouse ATS
        if "greenhouse.io" in active.url:
            self.logger.info("Detected Greenhouse job page: %s", active.url)
            gh_apply = active.locator("a#apply_button, a:has-text('Apply for this job'), a:has-text('Apply')")
            if gh_apply.count() > 0 and gh_apply.first.is_visible():
                try:
                    gh_apply.first.click(timeout=5000)
                    active.wait_for_timeout(2000)
                except Exception:
                    pass

        # Check for Workday Multi-Hop
        if "myworkdayjobs.com" in active.url:
            self.logger.info("Detected Workday site. Triggering multi-hop logic...")
            wd_apply = active.get_by_role("button", name=re.compile(r"^apply$", re.IGNORECASE))
            if not wd_apply.count():
                wd_apply = active.get_by_role("link", name=re.compile(r"^apply$", re.IGNORECASE))
            
            for btn in wd_apply.all():
                if btn.is_visible():
                    btn.click()
                    active.wait_for_timeout(2000)
                    break
                    
            manual_btn = active.get_by_role("link", name=re.compile(r"apply manually", re.IGNORECASE))
            if not manual_btn.count():
                manual_btn = active.get_by_role("button", name=re.compile(r"apply manually", re.IGNORECASE))
            if manual_btn.count():
                manual_btn.first.click()
                active.wait_for_timeout(3000)
                    
        if len(active.context.pages) == 1 and "naukri.com/job-listings" in active.url:
            # We are still on the original Naukri tab. If it's an external job, this is a failure.
            # (Native jobs will have opened a modal, but external jobs should have opened a new tab).
            if active.locator("button:has-text('Apply on company site'), button:has-text('Apply on company website'), #company-site-button").count() > 0:
                raise Exception("Failed to open company website. Tab did not open.")
            
        return active

    def _collect_fields(self, page: Page) -> list[dict[str, Any]]:
        try:
            return page.locator(FIELD_SELECTOR).evaluate_all(FIELD_SCAN_JS)
        except Exception as exc:  # noqa: BLE001
            if any(sig in str(exc).lower() for sig in ("connection closed", "target closed", "browser has been closed")):
                raise
            self.logger.warning("Unable to scan form fields: %s", exc)
            return []

    def _build_answer_map(self, profile: ProfileData, material: dict[str, Any]) -> dict[str, str]:
        first_name, _, last_name = profile.name.partition(" ")
        # Derive numeric notice period (0 for immediate joiner)
        notice_raw = profile.notice_period or "Immediate"
        notice_numeric = "0" if any(w in notice_raw.lower() for w in ("immediate", "joining immediately")) else notice_raw
        
        addr = getattr(profile, "address", None)
        edu = getattr(profile, "education", None)
        elig = getattr(profile, "work_eligibility", None)
        comp = getattr(profile, "compensation", None)

        return {
            "name": profile.name,
            "first_name": first_name,
            "last_name": last_name or first_name,
            "email": profile.email,
            "phone": profile.phone,
            "country": addr.country if addr and addr.country else "India",
            "country_code": addr.country_code if addr and addr.country_code else "India (+91)",
            "city": addr.city if addr and addr.city else "Bengaluru",
            "state": addr.state if addr and addr.state else "Karnataka",
            "postal_code": addr.postal_code if addr and addr.postal_code else "560001",
            "relocation": elig.willing_to_relocate if elig else "Yes",
            "shifts": elig.willing_to_work_shifts if elig else "Yes",
            "work_authorization": elig.work_authorization if elig else "Yes",
            "visa_sponsorship": elig.visa_sponsorship if elig else "No",
            "gender": elig.gender if elig else "Male",
            "marital_status": elig.marital_status if elig else "Single",
            "education": edu.highest_degree if edu and edu.highest_degree else "Bachelor's Degree",
            "graduation_year": edu.graduation_year if edu and edu.graduation_year else "2024",
            "language": "English",
            "location": profile.location,
            "notice_period": profile.notice_period or "Immediate",
            "notice_period_days": notice_numeric,
            "current_salary": comp.current_salary if comp else "0 LPA (Fresher)",
            "expected_salary": comp.expected_salary if comp else "₹4.5 LPA (4-6 LPA)",
            "skills": material.get("skills_pitch") or ", ".join(profile.skills),
            "experience_summary": material.get("experience_summary") or profile.summary,
            "cover_letter": material.get("cover_letter") or profile.summary,
            "years_experience": "0-1",
            "account_password": getattr(self.config, "company_site_login_password", "") if self.config else "",
            "linkedin": profile.links.get("linkedin", ""),
            "github": profile.links.get("github", ""),
            "portfolio": profile.links.get("portfolio", ""),
        }

    def _classify_field(self, field: dict[str, Any]) -> str:
        label = self._label_for_field(field)
        normalized = normalize_key(label)
        field_type = field["type"]
        tag = field["tag"]
        accept = normalize_key(field.get("accept", ""))

        if field.get("isAriaWidget"):
            # Enterprise ATS platforms (Workday/Greenhouse) heavily obfuscate dropdowns and dynamically render options after a click.
            # We treat all ARIA widgets as dynamic dropdowns instead of manual text fields to prevent invalid `.fill()` crashes on <button> tags.
            return "aria_dropdown"

        name_id_text = (str(field.get("name", "")) + " " + str(field.get("id", ""))).lower()
        if "captcha" in name_id_text or "turnstile" in name_id_text or "cf-" in name_id_text:
            return "ignore"

        if field_type in {"hidden", "submit", "reset", "search"}:
            return "ignore"
        # Normalised label set — also catches duplicated labels like "Bangalore Bangalore"
        _city_words = {"bangalore", "bengaluru", "mumbai", "pune", "delhi", "hyderabad",
                       "chennai", "noida", "gurgaon", "gurugram", "kolkata"}
        _norm_words = set(normalized.split())
        if any(keyword in normalized for keyword in (
            "describe the job you want", "search by title", "search jobs",
            "search keywords", "keyword search", "search for jobs",
            "cookie", "enable analytics", "enable performance", "enable functional",
            "enable advertisement", "necessary cookies", "functional cookies",
            "analytics cookies", "advertising cookies",
            "applied", "bookmarked", "clear all", "job type",
            "working mode", "experience level",
            # QuickHire / job-board filter widgets (experience bands)
            "0 1 year", "1 3 years", "3 5 years", "6 years", "10 years",
        )) or normalized in {"search", "applied", "bookmarked", "pan india"} \
          or _norm_words <= _city_words:   # all words are city names (handles "bangalore bangalore")
            return "ignore"
        if field_type == "password":
            field_id = str(field.get("id", "")).lower()
            field_name = str(field.get("name", "")).lower()
            # Ignore session/login widgets from page footers or auth-walls (e.g. LinkedIn session_password)
            if (
                "session_password" in field_id
                or "session_password" in field_name
                or "session_key" in field_id
                or "session_key" in field_name
                or "login" in field_id
                or "signin" in field_id
                or any(kw in normalized for kw in ("kata sandi", "session", "login", "signin", "auth", "masuk"))
            ):
                return "ignore"
            if self.config and getattr(self.config, "company_site_login_password", ""):
                return "account_password"
            return "ignore"
        if any(keyword in normalized for keyword in ("photo", "picture", "avatar", "profile photo", "headshot", "photograph", "passport size")):
            return "photo_upload"
        if field_type == "file" or "resume" in normalized or "cv" in normalized or "pdf" in accept:
            return "resume_upload"
        if field_type == "checkbox":
            if any(keyword in normalized for keyword in ("privacy", "consent", "terms", "agree", "certify", "declaration", "confirm")):
                return "consent"
            if any(kw in normalized for kw in (
                "applied", "bookmarked", "filter", "hybrid", "on site", "remote",
                "internship", "full time", "part time", "freelance",
                "keep me logged in", "remember me", "stay signed in", "ingat saya",
            )):
                return "ignore"
            return "manual"
        if any(keyword in normalized for keyword in SENSITIVE_DATA_KEYWORDS):
            return "blocked_sensitive"
        if any(keyword in normalized for keyword in (
            "require visa", "require sponsorship", "need sponsorship", "visa sponsorship",
            "will you require sponsorship", "sponsorship to retain", "require company sponsorship"
        )):
            return "visa_sponsorship"
        if any(keyword in normalized for keyword in (
            "authorized to work", "legally authorized", "right to work", "work permit",
            "eligible to work", "work authorization", "authorisation to work"
        )):
            return "work_authorization"
        if any(keyword in normalized for keyword in ("rotational shift", "night shift", "working in shifts", "shift")):
            return "shifts"
        if any(keyword in normalized for keyword in ("gender", "sex")) and "transgender" not in normalized:
            return "gender"
        if "marital" in normalized:
            return "marital_status"
        if any(keyword in normalized for keyword in ("highest qualification", "highest degree", "education level", "degree")):
            return "education"
        if any(keyword in normalized for keyword in ("graduation year", "year of graduation", "passing year", "year of passing")):
            return "graduation_year"
        if any(keyword in normalized for keyword in ("postal code", "zip code", "pincode", "pin code")):
            return "postal_code"
        if any(keyword in normalized for keyword in ("state", "province", "state province")):
            return "state"
        if any(keyword in normalized for keyword in ("city", "current city")):
            return "city"
        if any(keyword in normalized for keyword in ("ethnicity", "race", "veteran", "disability", "religion", "date of birth", "dob")):
            return "manual"
        if any(keyword in normalized for keyword in ("country of residence", "current country", "country/region", "nationality", "country and language")) or normalized == "country":
            return "country"
        if any(keyword in normalized for keyword in ("country code", "phone code", "dialing code")):
            return "country_code"
        if (
            field_type == "email"
            or "email" in normalized
            or "ibmid" in normalized
            or "ibm id" in normalized
            or "e mail" in normalized
            or "example.com" in normalized
        ):
            return "email"
        if field_type == "tel" or any(keyword in normalized for keyword in ("phone", "mobile", "contact number", "contact no", "telephone", "9876543210")):
            return "phone"
        if "first name" in normalized or "fname" in normalized or normalized == "first":
            return "first_name"
        if "last name" in normalized or "lname" in normalized or "surname" in normalized:
            return "last_name"
        if (
            "full name" in normalized
            or normalized == "name"
            or "candidate name" in normalized
            or "applicant name" in normalized
            or "your name" in normalized
            or "name" in normalized.split()
            or any(dummy in normalized for dummy in ("rajesh", "john doe", "jane doe"))
        ):
            return "name"
        if any(keyword in normalized for keyword in (
            "relocat", "willing to relocate", "open to relocate", "open to relocation",
            "work in our san francisco office", "work in our office", "work from office",
            "onsite", "relocate to us", "willing to move",
        )):
            return "relocation"
        if any(keyword in normalized for keyword in ("city", "current location", "location", "address")):
            return "location"
        if any(keyword in normalized for keyword in ("availability", "available to join", "joining in days", "days to join", "notice in days", "notice period in days")):
            return "notice_period_days"
        if "notice" in normalized:
            return "notice_period"
        if "language" in normalized:
            return "language"
        if any(keyword in normalized for keyword in (
            "current ctc", "current salary", "present ctc", "present salary", "existing ctc",
            "last drawn salary", "last drawn ctc", "fixed ctc", "current compensation",
        )):
            return "current_salary"
        if any(keyword in normalized for keyword in (
            "expected ctc", "expected salary", "target ctc", "desired ctc", "expected compensation",
            "salary expectation", "pay expectation", "salary", "ctc", "compensation",
        )):
            return "expected_salary"
        if any(keyword in normalized for keyword in ("skill", "technology", "tech stack")):
            return "skills"
        if any(keyword in normalized for keyword in ("experience summary", "professional summary", "about yourself", "summary", "tell us about yourself")):
            return "experience_summary"
        if any(keyword in normalized for keyword in ("cover letter", "why are you interested", "message to hiring", "why should we hire")):
            return "cover_letter"
        if "linkedin" in normalized:
            return "linkedin"
        if "github" in normalized:
            return "github"
        if any(keyword in normalized for keyword in ("portfolio", "website", "personal site")):
            return "portfolio"
        if any(keyword in normalized for keyword in (
            "years of experience", "experience in years", "total experience",
            "relevant experience", "work experience", "overall experience",
            "experience level", "experience range", "total work experience",
            "how many years of experience", "no of years of experience",
            "experience in cybersecurity", "cybersecurity experience",
            "penetration testing experience", "vapt experience"
        )) or normalized in ("experience", "total exp", "exp", "experience years", "years exp"):
            return "years_experience"
        if tag == "select":
            return "manual"
        return "manual"

    @staticmethod
    def _label_for_field(field: dict[str, Any]) -> str:
        labels = [p for p in field.get("labelTexts", []) if p]
        legend = field.get("legend", "")
        aria = field.get("ariaLabel", "")
        primary = compact_whitespace(" ".join(labels + ([legend] if legend else []) + ([aria] if aria else [])))
        if primary:
            return primary
        fallback = compact_whitespace(field.get("name", "") or field.get("placeholder", ""))
        return fallback or "unlabeled field"

    @staticmethod
    def _extract_numeric_answer(answer: str) -> str:
        """Extract the first numeric value from answer text for input[type=number] fields.

        Examples:
          "Immediate"            -> "0"
          "0 LPA (Fresher)"      -> "0"
          "₹4.5 LPA (4-6 LPA)"   -> "4.5"
          "30 days"              -> "30"
          "0-1 years"            -> "1"
        """
        import re as _re
        stripped = str(answer).strip()
        if _re.fullmatch(r"-?\d+(\.\d+)?", stripped):
            return stripped
        lower = stripped.lower()
        if any(k in lower for k in ("immediate", "immediately", "joining immediately", "fresher", "currently 0", "0 lpa")) or _re.search(r"\b0\s*days?\b", lower) or _re.search(r"\b0-day\b", lower):
            return "0"
        if "4.5" in lower:
            return "4.5"
        if _re.search(r"\b4\s*[-–to ]\s*6\b", lower):
            return "4.5"
        if _re.search(r"\b0\s*[-–to ]\s*1\b", lower):
            return "1"
        if "month" in lower and not any(k in lower for k in ("12 month", "6 month", "3 month")):
            return "0"
        # Extract first floating point or integer
        m = _re.search(r"\b(\d+(?:\.\d+)?)\b", stripped)
        if m:
            return m.group(1)
        return ""

    @classmethod
    def _should_click_radio(cls, label: str, field: dict[str, Any], answer: str) -> bool:
        """Determine whether a specific radio button element should be clicked."""
        norm_label = normalize_key(label)
        norm_val = normalize_key(str(field.get("value", "")))
        norm_ans = normalize_key(str(answer))
        field_combo = norm_label + " " + norm_val

        # 1. Experience Field Matching (4-tier fresher priority)
        if cls._is_experience_field(label, field, []):
            is_fresher_choice = any(
                p.search(field_combo)
                for p in (FRESHER_EXP_TIER1 + FRESHER_EXP_TIER2 + FRESHER_EXP_TIER3 + FRESHER_EXP_TIER4)
            )
            return is_fresher_choice

        # 2. Gender
        if any(kw in norm_label for kw in ("gender", "sex")) and "transgender" not in norm_label:
            words = set(field_combo.split())
            return ("male" in words or "man" in words or norm_val == "m") and "female" not in words

        # 3. Highest Qualification / Education
        if any(kw in norm_label for kw in ("degree", "qualification", "education", "highest")):
            return any(k in field_combo for k in ("bachelor", "b tech", "b e", "undergraduate", "btech", "be computer")) and "master" not in field_combo and "phd" not in field_combo

        # 4. Notice Period
        if any(kw in norm_label for kw in ("notice", "available", "joining", "availability")):
            return any(k in field_combo for k in ("immediate", "0 to 15", "0 15", "segera", "can join immediately", "immediate joiner")) or bool(re.search(r"\b0\s*days?\b", field_combo)) or norm_val == "0"

        # 5. Work Authorization (Yes)
        if any(kw in norm_label for kw in ("authorized", "legally", "right to work", "work permit", "authorization", "eligible")):
            words = set(field_combo.split())
            return any(k in words for k in ("yes", "authorized", "true", "1")) and "no" not in words

        # 6. Visa Sponsorship (No)
        if any(kw in norm_label for kw in ("require sponsor", "require visa", "sponsorship", "need sponsor")):
            words = set(field_combo.split())
            return any(k in words for k in ("no", "false", "0", "not")) and "yes" not in words

        # 7. Relocation / Shifts / Travel (Yes)
        if any(kw in norm_label for kw in ("relocat", "travel", "shift", "onsite", "office")):
            words = set(field_combo.split())
            return any(k in words for k in ("yes", "willing", "open", "flexible", "true", "1")) and "no" not in words

        # 8. General Affirmative Answer ("yes", "true", "1")
        if norm_ans in ("yes", "true", "1"):
            words = set(field_combo.split())
            return any(k in words for k in ("yes", "true", "1")) and "no" not in words

        # 9. General Negative Answer ("no", "false", "0")
        if norm_ans in ("no", "false", "0"):
            words = set(field_combo.split())
            return any(k in words for k in ("no", "false", "0")) and "yes" not in words

        # 10. Direct Exact / Substring Match
        if norm_ans and (norm_ans == norm_val or norm_ans in norm_label or norm_label in norm_ans):
            if norm_ans == "male" and "female" in field_combo:
                return False
            return True

        return False

    def _fill_locator(
        self,
        locator: Locator,
        field: dict[str, Any],
        answer: str,
        label: str,
        result: FillResult,
    ) -> None:
        # Anti-Bot Token & Honeypot Quarantine Gate
        field_id = str(field.get("id", "")).lower()
        field_name = str(field.get("name", "")).lower()
        if any(token in (field_id + " " + field_name) for token in ("recaptcha", "turnstile", "cf-chl", "hcaptcha", "bot-field")):
            self.logger.debug("Quarantined anti-bot token honeypot: %s (id=%s, name=%s)", label, field_id, field_name)
            return

        try:
            if field["tag"] == "select":
                self._fill_select(locator, field, answer, label=label)
            elif field.get("type") == "number":
                numeric_answer = self._extract_numeric_answer(answer)
                if numeric_answer:
                    locator.fill(numeric_answer, timeout=8000)
                    result.filled_fields.append(label)
                    self.logger.info("Filled number field: %s -> %s (from '%s')", label, numeric_answer, answer[:40])
                else:
                    self.logger.warning("Skipped number field %s: could not extract numeric value from '%s'", label, answer)
                return
            elif field.get("type") in ("checkbox", "radio"):
                if field.get("type") == "radio":
                    if self._should_click_radio(label, field, answer):
                        locator.click(force=True, timeout=8000)
                        result.filled_fields.append(label)
                        self.logger.info("Selected radio button: %s (value=%s)", label, field.get("value", ""))
                        return
                    else:
                        # Do not click un-matched radio options in the group
                        return
                locator.click(force=True, timeout=8000)
            else:
                locator.fill(answer, timeout=8000)
            result.filled_fields.append(label)
            display_val = str(answer)[:35] + "..." if len(str(answer)) > 35 else str(answer)
            self.logger.info("Filled field: %s -> %s", label, display_val)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{label}: {exc}")
            self.logger.warning("Failed to fill field %s: %s", label, exc)

    @classmethod
    def _is_experience_field(cls, label: str, field: dict[str, Any], options: list[Any]) -> bool:
        """Check whether a field or its options represent a years-of-experience question."""
        norm_label = normalize_key(label)
        field_name_id = normalize_key(str(field.get("name", "")) + " " + str(field.get("id", "")))
        combined = norm_label + " " + field_name_id
        if any(kw in combined for kw in (
            "experience", "total exp", "work exp", "relevant exp", "exp in years",
            "years exp", "experience level", "experience band", "experience range",
            "how many years", "no of years", "number of years", "years of", "overall exp"
        )):
            return True
        # Check if the options themselves look like experience bands
        exp_opt_count = 0
        for opt in options:
            txt = opt.get("text", "") if isinstance(opt, dict) else str(opt)
            val = opt.get("value", "") if isinstance(opt, dict) else str(opt)
            combined_opt = (txt + " " + val).lower()
            if any(kw in combined_opt for kw in (
                "fresher", "0-1", "0 - 1", "0 to 1", "6 month", "1-2", "1-3",
                "years", "year", "yrs", "yr", "< 1 year", "<1 year", "less than 1"
            )):
                exp_opt_count += 1
        return exp_opt_count >= 2

    @classmethod
    def _match_fresher_experience_option(cls, options: list[Any]) -> Any | None:
        """
        Choose experience for a fresher/early-career candidate following user directive:
        1. '6 months' or '0-6 months' or '< 1 year' or 'less than 1 year'
        2. '0-1' or '0-1 years' or '0 to 1 year'
        3. 'Fresher' or 'Entry Level' or 'Beginner' or 'Trainee' or '0 years'
        4. '1 year' or '1-2 years' (fallback if 0-1 / 6 months / fresher not listed)
        """
        # Tier 1: 6 months / less than 1 year
        for opt in options:
            txt = opt.get("text", "") if isinstance(opt, dict) else str(opt)
            val = opt.get("value", "") if isinstance(opt, dict) else str(opt)
            for p in FRESHER_EXP_TIER1:
                if p.search(txt) or p.search(val):
                    return opt
        # Tier 2: 0-1 years / 0 to 1
        for opt in options:
            txt = opt.get("text", "") if isinstance(opt, dict) else str(opt)
            val = opt.get("value", "") if isinstance(opt, dict) else str(opt)
            for p in FRESHER_EXP_TIER2:
                if p.search(txt) or p.search(val):
                    return opt
        # Tier 3: Fresher / Entry Level / 0 years
        for opt in options:
            txt = opt.get("text", "") if isinstance(opt, dict) else str(opt)
            val = opt.get("value", "") if isinstance(opt, dict) else str(opt)
            for p in FRESHER_EXP_TIER3:
                if p.search(txt) or p.search(val):
                    return opt
        # Tier 4: 1 year / 1-2 years
        for opt in options:
            txt = opt.get("text", "") if isinstance(opt, dict) else str(opt)
            val = opt.get("value", "") if isinstance(opt, dict) else str(opt)
            for p in FRESHER_EXP_TIER4:
                if p.search(txt) or p.search(val):
                    return opt
        return None

    @classmethod
    def _match_dropdown_option(
        cls,
        options: list[dict[str, Any]],
        label: str,
        answer: str,
        field: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Domain-aware option matcher for selects and ARIA dropdowns, eliminating false selections."""
        if not options:
            return None

        norm_label = normalize_key(label)
        norm_ans = normalize_key(answer)
        field = field or {}
        field_combo = norm_label + " " + normalize_key(str(field.get("name", "")) + " " + str(field.get("id", "")))

        # 1. Experience Field Matching (4-tier fresher priority)
        if cls._is_experience_field(label, field, options):
            best_opt = cls._match_fresher_experience_option(options)
            if best_opt:
                return best_opt

        # 2. Notice Period / Availability
        if any(kw in field_combo for kw in ("notice", "availability", "available", "joining", "start date", "how soon")):
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                if (
                    any(k in t for k in ("immediate", "0 to 15", "0 15", "segera", "can join immediately", "immediate joiner"))
                    or bool(re.search(r"\b0\s*days?\b", t))
                    or str(opt.get("value", "")) == "0"
                ):
                    return opt
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                if any(k in t for k in ("15 days", "< 15", "less than 15", "within 15", "0 30")):
                    return opt

        # 3. Current CTC / Salary
        if any(kw in field_combo for kw in ("current ctc", "current salary", "present ctc", "fixed ctc", "last drawn")):
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                if (
                    any(k in t for k in ("fresher", "0 1", "0 to 1", "less than 1", "< 1", "0 lpa", "none", "0 lakh", "not applicable"))
                    or t.strip() == "0"
                    or str(opt.get("value", "")) == "0"
                ):
                    return opt

        # 4. Expected CTC / Salary
        if any(kw in field_combo for kw in ("expected ctc", "expected salary", "target ctc", "desired ctc", "salary", "ctc")):
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                if re.search(r"\b4\s*[-–to ]\s*6\b", t) or re.search(r"\b4\.5\b", t) or re.search(r"\b4\s*[-–to ]\s*5\b", t):
                    return opt
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                if re.search(r"\b3\s*[-–to ]\s*[56]\b", t) or "entry level" in t:
                    return opt

        # 5. Work Authorization
        if any(kw in field_combo for kw in ("authorized", "legally authorized", "right to work", "work permit", "authorization", "eligible to work")):
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                words = set(t.split())
                if any(k in words for k in ("yes", "authorized", "citizen", "permanent resident", "india")) and "no" not in words:
                    return opt

        # 6. Visa Sponsorship
        if any(kw in field_combo for kw in ("require sponsor", "require visa", "sponsorship", "need sponsor")):
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                words = set(t.split())
                if any(k in words for k in ("no", "false", "0", "not")) and "yes" not in words:
                    return opt

        # 7. Relocation / Shifts / Travel
        if any(kw in field_combo for kw in ("relocat", "travel", "shift", "onsite", "office")):
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                words = set(t.split())
                if any(k in words for k in ("yes", "willing", "open", "flexible", "true")) and "no" not in words:
                    return opt

        # 8. Gender (Male)
        if any(kw in field_combo for kw in ("gender", "sex")) and "transgender" not in field_combo:
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                words = set(t.split())
                if ("male" in words or "man" in words or str(opt.get("value", "")).lower() == "m") and "female" not in words:
                    return opt

        # 9. Education (Bachelor)
        if any(kw in field_combo for kw in ("degree", "highest qualification", "education", "highest degree")):
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                if (
                    any(k in t for k in ("bachelor", "b tech", "b e", "undergraduate", "btech", "be computer"))
                    and "master" not in t
                    and "phd" not in t
                ):
                    return opt

        # 10. Country / Nationality (India)
        if any(kw in field_combo for kw in ("country", "nationality", "citizenship")):
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                words = set(t.split())
                if (
                    ("india" in words or "indian" in words or str(opt.get("value", "")).lower() == "in")
                    and "british" not in words
                    and "territory" not in words
                ):
                    return opt

        # 11. Disclaimers: Disability & Veteran
        if "disability" in field_combo:
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                if any(k in t for k in ("no i do not have", "no disability", "do not have a disability", "no", "decline")):
                    return opt
        if "veteran" in field_combo:
            for opt in options:
                t = normalize_key(opt.get("text", "") + " " + str(opt.get("value", "")))
                if any(k in t for k in ("not a protected veteran", "not a veteran", "no", "decline")):
                    return opt

        # 12. Standard Answer Exact Match
        for opt in options:
            t = normalize_key(opt.get("text", ""))
            v = normalize_key(str(opt.get("value", "")))
            if norm_ans and (norm_ans == t or norm_ans == v):
                return opt

        # 13. Standard Answer Substring Match
        for opt in options:
            t = normalize_key(opt.get("text", ""))
            v = normalize_key(str(opt.get("value", "")))
            if norm_ans and (norm_ans in t or norm_ans in v or (t and t in norm_ans)):
                if norm_ans == "male" and ("female" in t or "female" in v):
                    continue
                return opt

        # 14. Binary Yes/No Match
        if norm_ans in ("yes", "true", "1"):
            for opt in options:
                words = set(normalize_key(opt.get("text", "") + " " + str(opt.get("value", ""))).split())
                if any(k in words for k in ("yes", "true", "1")) and "no" not in words:
                    return opt
        elif norm_ans in ("no", "false", "0"):
            for opt in options:
                words = set(normalize_key(opt.get("text", "") + " " + str(opt.get("value", ""))).split())
                if any(k in words for k in ("no", "false", "0")) and "yes" not in words:
                    return opt

        # 15. Safe first valid option (ignore placeholder texts like "select...")
        valid = [
            o for o in options
            if normalize_key(o.get("text", "")) not in ("", "select", "choose", "select one", "-1", "please select")
            and normalize_key(str(o.get("value", ""))) not in ("", "select", "choose", "-1", "null", "none")
        ]
        return valid[0] if valid else None

    @classmethod
    def _fill_select(cls, locator: Locator, field: dict[str, Any], answer: str, label: str = "") -> None:
        options = field.get("options", [])
        matched = cls._match_dropdown_option(options, label, answer, field)
        if matched and "value" in matched:
            locator.select_option(value=matched["value"], force=True, timeout=3000)
            logging.getLogger(__name__).info(
                "Selected option for %s: '%s' (value=%s)",
                label or "select field",
                matched.get("text", ""),
                matched.get("value", ""),
            )
            return

        raise ValueError(f"No matching select option found for answer: {answer}")

    def _fill_aria_dropdown(
        self,
        locator: Locator,
        field: dict[str, Any],
        answer: str,
        label: str,
        result: FillResult,
    ) -> None:
        """
        Handles both standard ARIA comboboxes and Select2 widget dropdowns.
        Select2 hides options until clicked — we click first, then scan the DOM for options.
        """
        try:
            # Step 1: click to open the dropdown (works for both ARIA and Select2)
            locator.click(timeout=3000, force=True)
            locator.page.wait_for_timeout(600)

            # Step 2: build options list — prefer live DOM scan over pre-scan (Select2 lazy renders)
            live_options: list[dict] = []
            try:
                live_options = locator.page.evaluate("""() => {
                    const containers = document.querySelectorAll(
                        'ul.select2-results__options, ul[role="listbox"], [role="listbox"]'
                    );
                    const opts = [];
                    containers.forEach(c => {
                        c.querySelectorAll('li, [role="option"]').forEach(el => {
                            const txt = (el.innerText || el.textContent || '').trim();
                            if (txt) opts.push({text: txt});
                        });
                    });
                    return opts;
                }""")
            except Exception:
                pass

            # Fall back to pre-scanned options if live scan returned nothing
            options = live_options if live_options else field.get("ariaOptions", [])

            match = self._match_dropdown_option(options, label, answer, field)

            if match is None:
                # Last resort — Playwright role=option search
                opt_loc = locator.page.get_by_role("option", name=re.compile(re.escape(answer[:20]), re.IGNORECASE))
                if opt_loc.count():
                    opt_loc.first.click()
                    result.filled_fields.append(label)
                    self.logger.info("Selected dropdown via Playwright role=option: %s", label)
                    return
                avail = [o.get("text", "") for o in options[:8]]
                raise ValueError(f"No matching option for '{answer}'. Available: {avail}")

            # Step 3: click the matched option
            clicked = False
            safe_text = match.get("text", "").replace("'", "\\'")
            for sel in [f"li:has-text('{safe_text}')", f"[role='option']:has-text('{safe_text}')"]:
                try:
                    el = locator.page.locator(sel).first
                    if el.count() and el.is_visible():
                        el.click()
                        clicked = True
                        break
                except Exception:
                    pass

            if not clicked:
                opt_loc = locator.page.get_by_role("option", name=re.compile(re.escape(match.get("text", "")), re.IGNORECASE))
                if opt_loc.count():
                    opt_loc.first.click()
                    clicked = True

            if not clicked:
                raise ValueError(f"Could not click option: {match.get('text', '')}")

            result.filled_fields.append(label)
            self.logger.info("Selected dropdown option: %s -> %s", label, match.get("text", ""))
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{label}: {exc}")
            self.logger.warning("Failed to fill dropdown %s: %s", label, exc)

    def _upload_resume(
        self,
        locator: Locator,
        label: str,
        result: FillResult,
        job: JobPosting | None = None,
        profile: ProfileData | None = None,
        page: Page | None = None,
    ) -> None:
        try:
            resume_path = str(self.config.resume_path)
            if job and profile and page:
                try:
                    from app.resume_tailorer import ResumeTailorer  # noqa: PLC0415
                    tailorer = ResumeTailorer(self.config.project_root, self.logger)
                    tailored_pdf = tailorer.generate_tailored_pdf(job, profile, page)
                    if tailored_pdf and Path(tailored_pdf).exists():
                        resume_path = tailored_pdf
                except Exception as t_err:  # noqa: BLE001
                    self.logger.warning("Dynamic resume tailoring fallback to base: %s", t_err)

            # Use tailored resume if generated, otherwise fall back to configured master resume
            # Do NOT overwrite upload_target (preserves candidate's master resume on disk)
            upload_target = Path(self.config.resume_path)
            if not Path(resume_path).exists() and upload_target.exists():
                resume_path = str(upload_target)

            try:
                locator.set_input_files(resume_path, timeout=7000)
                result.filled_fields.append(label)
                self.logger.info("Uploaded resume (%s) for field: %s", Path(resume_path).name, label)
            except Exception as loc_exc:
                if page:
                    try:
                        page.locator("input[type='file']").first.set_input_files(resume_path, timeout=5000)
                        result.filled_fields.append(label)
                        self.logger.info("Uploaded tailored resume via fallback file input: %s", label)
                        return
                    except Exception:
                        pass
                raise loc_exc
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{label}: {exc}")
            self.logger.warning("Resume upload failed for %s: %s", label, exc)

    def _upload_photo(self, locator: Locator, label: str, result: FillResult) -> None:
        try:
            photo_path = self.config.project_root / "profile" / "photo.jpg"
            if photo_path.exists():
                locator.set_input_files(str(photo_path))
                result.filled_fields.append(label)
                self.logger.info("Uploaded candidate photo for field: %s", label)
            else:
                self.logger.warning("Photo requested but profile/photo.jpg not found.")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{label}: {exc}")
            self.logger.warning("Photo upload failed for %s: %s", label, exc)

    @staticmethod
    def _handle_consent(locator: Locator, label: str, result: FillResult) -> None:
        try:
            locator.check()
            result.filled_fields.append(label)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{label}: {exc}")

    def _prompt_unknown_answer(self, label: str, store_answer: bool) -> str:
        if self.non_interactive:
            self.logger.info("Non-interactive mode: leaving unknown field for manual handling: %s", label)
            return ""
        print(f"Unknown field detected: {label}")
        if store_answer:
            print("The answer will be stored for reuse unless you leave it blank.")
        try:
            return input("Enter answer (leave blank to handle manually): ").strip()
        except EOFError:
            self.logger.warning("No interactive input available for unknown field: %s", label)
            return ""

    def _remember_answer(self, label: str, answer: str) -> None:
        if is_refusal_or_invalid_answer(answer, label):
            self.logger.warning("Rejected saving invalid or refusal answer for %r: %s", label, str(answer)[:60])
            return
        clean_key = normalize_key(label)
        # Block raw DOM system tokens, internal IDs, and garbage
        if any(tok in clean_key for tok in (
            "standardfields", "ra937", "rbcd", "r280", "r21a", "rd5f", "r6ea", "rfdf",
            "rc902", "rd0b", "wpforms", "form fields", "menu 754", "textarea", "systemfield",
            "questions 248", "multipleanswers"
        )):
            return
        if clean_key.isdigit() and len(clean_key) >= 4:
            return
        if not clean_key or clean_key in ("unlabeled field", "query", "message", "query query", "enter your answer", "add your response here"):
            return
        # Block phone prefix (+91) being saved for non-phone labels
        if str(answer).strip() in ("+91", "91", "+91 (India)") and not any(k in clean_key for k in ("country code", "phone code", "dialing code")):
            return
        # Block overly long text unless cover letter/summary
        if len(str(answer)) > 200 and not any(k in clean_key for k in ("cover letter", "summary", "why", "about you", "tell us", "pitch")):
            return
        self.templates.setdefault("custom_answers", {})[clean_key] = answer
        save_answer_templates(self.config.answer_templates_path, self.templates)
        self.logger.info("Stored new verified custom answer for reuse: %s -> %s", label, str(answer)[:40])

    def _resolve_via_fuzzy_match(self, label: str, profile: ProfileData) -> str | None:
        found = lookup_saved_answer_fuzzy(label, self.templates, profile)
        if found is None:
            return None
        answer, matched_key = found
        self.logger.info("Fuzzy-matched %r to saved question %r", label, matched_key)
        return answer

    def _smart_auto_answer(
        self,
        label: str,
        field: dict[str, Any],
        job: JobPosting,
        profile: ProfileData,
        options: list[str] | None = None,
    ) -> str:
        """Determines the optimal answer for any question or form field, ensuring 100% automation.
        
        Applies the candidate's configured profile data with these decision rules:
        - Fresher / 6 months / 0-1 years for experience options.
        - Immediate notice period / 0 days.
        - Authorized to work in India / open to relocation and rotational shifts.
        - Realistic candidate salary: 0 LPA current, 4-6 LPA expected.
        - Authentic VAPT / AppSec / Python skills.
        """
        norm = normalize_key(label)

        # 0. Candidate Name / Identity fields
        if any(kw in norm for kw in ("full name", "first name", "last name", "your name", "candidate name", "applicant name", "priya sharma", "john doe")):
            return profile.name or ""

        # 0b. Contact, Location, and Social Links
        if any(kw in norm for kw in ("email", "e-mail")) and "hiring" not in norm:
            return profile.email or ""
        if any(kw in norm for kw in ("phone", "mobile", "contact no", "contact number", "whatsapp")):
            return profile.phone or ""
        if any(kw in norm for kw in ("country of residence", "current country", "nationality", "citizenship")) or norm == "country":
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    words = set(opt_norm.split())
                    if ("india" in words or "indian" in words) and "british" not in words and "territory" not in words:
                        return opt
                return options[0]
            return "India" if ("country" in norm or "residence" in norm) else "Indian"
        if any(kw in norm for kw in ("current city", "current location", "current address", "city of residence", "residence address")):
            return profile.location or "Bengaluru, India"
        if "linkedin" in norm:
            return (profile.links or {}).get("linkedin", "")
        if "github" in norm:
            return (profile.links or {}).get("github", "")

        # 1. Experience Questions (Fresher Rule: choose 6 months / 0-1 years / Fresher)
        if any(kw in norm for kw in ("experience", "pengalaman", "years", "duration", "tenure")):
            if options:
                opts_norm = [normalize_key(o) for o in options]
                # If binary Yes/No question on experience, candidate has hands-on experience
                if "yes" in opts_norm and "no" in opts_norm:
                    return options[opts_norm.index("yes")]
                # Priority Tier 1: 0-6 months / < 1 year
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if any(k in opt_norm for k in ("6 month", "6 bln", "0 6", "0 to 6", "< 1", "less than 1")):
                        return opt
                # Priority Tier 2: 0-1 years / 0 to 1
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if re.search(r"\b0\s*[-–to ]\s*1\b", opt_norm):
                        return opt
                # Priority Tier 3: Fresher / Entry Level / 0 years
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if any(k in opt_norm for k in ("fresher", "entry level", "beginner", "trainee", "intern")) or opt_norm == "0":
                        return opt
                # Priority Tier 4: 1 year / 1-2 years
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if re.search(r"\b1\s*(?:year|yr)?\b", opt_norm) and "10" not in opt_norm and "15" not in opt_norm:
                        return opt
                return options[0]
            return "0-1 years" if ("year" in norm or "range" in norm or "band" in norm) else "1"

        # 2. Notice Period / Availability Questions
        if any(kw in norm for kw in ("notice", "available", "availability", "join", "start date", "ketersediaan")):
            if any(kw in norm for kw in ("days to join", "joining in days", "notice in days", "notice period in days", "how many days")):
                return "0"
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if (
                        any(k in opt_norm for k in ("immediate", "segera", "0 to 15", "0 15", "less than 15", "less than 1 month", "can join immediately", "immediate joiner"))
                        or re.search(r"\b0\s*days?\b", opt_norm)
                        or opt_norm == "0"
                    ):
                        return opt
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if any(k in opt_norm for k in ("15 days", "< 15", "less than 15", "within 15", "0 30")):
                        return opt
                return options[0]
            return "Immediate"

        # 3. Work Authorization / Visa / Legal
        if any(kw in norm for kw in ("sponsorship", "visa sponsor", "require sponsor", "need sponsor")):
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    words = set(opt_norm.split())
                    if any(k in words for k in ("no", "tidak", "false", "non", "not")) and "yes" not in words:
                        return opt
                return options[-1]
            return "No"

        if any(kw in norm for kw in ("authorized", "legally", "work permit", "authorization", "eligible", "right to work")):
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    words = set(opt_norm.split())
                    if any(k in words for k in ("yes", "ya", "true", "oui", "authorized", "citizen")) and "no" not in words:
                        return opt
                return options[0]
            return "Yes"

        # 4. Relocation / Travel / Shift Questions
        if any(kw in norm for kw in ("relocate", "relocation", "willing to relocate", "travel", "shift", "night shift", "rotational", "onsite", "office")):
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    words = set(opt_norm.split())
                    if any(k in words for k in ("yes", "ya", "true", "flexible", "open", "willing")) and "no" not in words:
                        return opt
                return options[0]
            return "Yes"

        # 5. Current CTC vs Expected CTC
        if any(kw in norm for kw in ("current ctc", "current salary", "present ctc", "present salary", "existing ctc", "last drawn", "fixed ctc")):
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if (
                        any(k in opt_norm for k in ("fresher", "0 1", "0 to 1", "less than 1", "< 1", "0 lpa", "none", "0 lakh", "not applicable"))
                        or opt_norm == "0"
                    ):
                        return opt
                return options[0]
            return "0 LPA (Fresher)"

        if any(kw in norm for kw in ("expected ctc", "expected salary", "target ctc", "desired ctc", "salary", "ctc", "compensation", "gaji")):
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if re.search(r"\b4\s*[-–to ]\s*6\b", opt_norm) or re.search(r"\b4\.5\b", opt_norm) or re.search(r"\b4\s*[-–to ]\s*5\b", opt_norm):
                        return opt
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if re.search(r"\b3\s*[-–to ]\s*[56]\b", opt_norm) or "entry level" in opt_norm:
                        return opt
                return options[0]
            return "₹4.5 LPA (4-6 LPA)"

        # 6. Gender / Personal
        if "gender" in norm or "sex" in norm or "jenis kelamin" in norm:
            if "transgender" not in norm:
                if options:
                    for opt in options:
                        words = set(normalize_key(opt).split())
                        if ("male" in words or "man" in words or "pria" in words) and "female" not in words:
                            return opt
                    return options[0]
                return "Male"

        if "marital" in norm:
            if options:
                for opt in options:
                    words = set(normalize_key(opt).split())
                    if "single" in words or "unmarried" in words:
                        return opt
                return options[0]
            return "Single"

        if "pronoun" in norm:
            if options:
                for opt in options:
                    if normalize_key(opt) in ("he/him", "he him", "he/him/his"):
                        return opt
                return options[0]
            return "He/him"

        if "veteran" in norm:
            if options:
                for opt in options:
                    if any(k in normalize_key(opt) for k in ("not a protected veteran", "not a veteran", "decline", "no")):
                        return opt
                return options[0]
            return "I am not a protected veteran"

        if "disability" in norm:
            if options:
                for opt in options:
                    if any(k in normalize_key(opt) for k in ("no i do not have a disability", "no disability", "do not have", "no")):
                        return opt
                return options[0]
            return "No, I do not have a disability and have not had one in the past"

        # 7. Education / Degree
        if any(kw in norm for kw in ("education", "degree", "qualification", "pendidikan", "highest qualification", "highest degree")):
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    if (
                        any(k in opt_norm for k in ("bachelor", "b tech", "b e", "undergraduate", "btech", "be computer", "computer science"))
                        and "master" not in opt_norm
                        and "phd" not in opt_norm
                    ):
                        return opt
                return options[0]
            return "Bachelor's Degree (B.Tech in Computer Science / Cybersecurity)"

        # 7b. Country of Residence / Nationality
        if any(kw in norm for kw in ("country of residence", "current country", "nationality", "citizenship")) or norm == "country":
            if options:
                for opt in options:
                    opt_norm = normalize_key(opt)
                    words = set(opt_norm.split())
                    if ("india" in words or "indian" in words) and "british" not in words and "territory" not in words:
                        return opt
                return options[0]
            return "India" if ("country" in norm or "residence" in norm) else "Indian"

        # 8. Generic Yes / No Questions
        if options and len(options) == 2:
            opts_norm = [normalize_key(o) for o in options]
            if "yes" in opts_norm and "no" in opts_norm:
                return options[opts_norm.index("yes")]
            return options[0]

        # 9. Free-form text fields (Cover letters, Why hire me, Technical skills)
        if any(kw in norm for kw in ("why", "cover letter", "about you", "describe", "summary", "strengths", "tell us")):
            return (
                "I am a cybersecurity and Python engineer with hands-on practice in VAPT, OWASP Top 10, "
                "Burp Suite, API Security, and SOC workflows. I bring strong analytical skills and build secure, "
                "efficient applications. Available immediately."
            )

        # 10. Fallback: if options exist, pick first non-empty option; else return authentic affirmative
        if options:
            valid = [o for o in options if normalize_key(o) not in ("", "select", "choose", "-1", "please select")]
            return valid[0] if valid else options[0]
        return "Yes"

    def _resolve_via_llm(self, label: str, job: JobPosting, profile: ProfileData, options: list[str] | None = None) -> str | None:
        try:
            # If dropdown options are available, append them to the label so the LLM picks one
            effective_label = label
            if options:
                opts_str = " | ".join(options[:15])
                effective_label = f"{label} [PICK EXACTLY ONE: {opts_str}]"
            draft = self.ollama_client.answer_question(job, profile, effective_label)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("LLM answer_question failed for %r: %s", label, exc)
            return None
        if not draft or "need user input" in normalize_key(draft):
            return None
        if is_refusal_or_invalid_answer(draft, label):
            self.logger.warning("LLM returned refusal or policy notice for field %r: %s", label, draft[:80])
            return None
        # If options were given, find the closest match in the list (LLM may paraphrase)
        if options and draft:
            draft_norm = normalize_key(draft)
            for opt in options:
                if normalize_key(opt) == draft_norm or normalize_key(opt) in draft_norm or draft_norm in normalize_key(opt):
                    draft = opt
                    break
        confirmed = self._confirm_llm_answer(label, draft)
        if confirmed:
            self._remember_answer(label, confirmed)
        return confirmed

    def _confirm_llm_answer(self, label: str, draft: str) -> str | None:
        if self.non_interactive:
            self.logger.info("Non-interactive mode: auto-accepting LLM answer for field: %s", label)
            return draft
        print(f"\nField: {label}")
        print(f"AI-drafted answer: {draft}")
        try:
            choice = input("Use this answer? [y/n/e=edit]: ").strip().lower()
        except EOFError:
            self.logger.warning("No interactive input available to confirm LLM answer for: %s", label)
            return None
        if choice == "y":
            return draft
        if choice == "e":
            try:
                edited = input("Enter corrected answer: ").strip()
            except EOFError:
                return None
            return edited or None
        return None

    @staticmethod
    def _detect_blockers(page: Page) -> list[str]:
        try:
            # 1. Real interactive CAPTCHA challenges (iframes / DOM elements)
            for sel in (
                "iframe[src*='recaptcha' i]", "iframe[src*='hcaptcha' i]", "iframe[src*='turnstile' i]",
                ".g-recaptcha", ".cf-turnstile", "div#challenge-running", "iframe[title*='reCAPTCHA' i]",
                "iframe[title*='hCaptcha' i]", "iframe[src*='challenge' i]",
            ):
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        return ["captcha"]
                except Exception:
                    pass

            # 2. Real OTP / SMS entry input fields currently visible on screen
            for sel in (
                "input[placeholder*='otp' i]", "input[name*='otp' i]", "input[id*='otp' i]",
                "input[aria-label*='otp' i]", "input.otp-input",
            ):
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        return ["otp"]
                except Exception:
                    pass
        except Exception:  # noqa: BLE001
            return []
        return []

    @staticmethod
    def _check_job_expired(page: Page) -> bool:
        try:
            url = page.url.lower()
            if "expjd=true" in url or "expired_jd_redirect" in url or "/job-expired" in url:
                return True
            if "naukri.com" in url and "job-listings" not in url:
                return True
            for text_pattern in (
                "text='This job has expired'",
                "text='This job is no longer active'",
                "text='Job has expired'",
                "text='This job is inactive'",
                "text='No longer accepting applications'",
                "text='Job posting has expired'",
                "text='Pekerjaan ini sudah tidak menerima lamaran'",
            ):
                loc = page.locator(text_pattern)
                if loc.count() > 0 and loc.first.is_visible():
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _can_auto_submit(job: JobPosting, match: MatchResult, result: FillResult) -> bool:
        return (
            match.score >= 50
            and match.min_years_required <= 3
            and match.max_years_required <= 8
            and not result.submit_blockers
            and not result.unknown_questions
            and result.ready_to_submit
        )
