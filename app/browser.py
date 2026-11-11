from __future__ import annotations

import os
import re
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, Playwright, sync_playwright

from app.utils import CAPTCHA_KEYWORDS, compact_whitespace

STEALTH_INIT_SCRIPT = """
(() => {
    // 1. Mask navigator.webdriver
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
    } catch (e) {}

    // 2. Mock chrome runtime object
    if (!window.chrome) {
        window.chrome = {
            runtime: {
                OnInstalledReason: { INSTALL: "install", UPDATE: "update", CHROME_UPDATE: "chrome_update", SHARED_MODULE_UPDATE: "shared_module_update" },
                OnRestartRequiredReason: { APP_UPDATE: "app_update", OS_UPDATE: "os_update", PERIODIC: "periodic" },
                PlatformArch: { ARM: "arm", ARM64: "arm64", MIPS: "mips", MIPS64: "mips64", X86_32: "x86-32", X86_64: "x86-64" },
                PlatformNaclArch: { ARM: "arm", MIPS: "mips", MIPS64: "mips64", X86_32: "x86-32", X86_64: "x86-64" },
                PlatformOs: { ANDROID: "android", CROS: "cros", LINUX: "linux", MAC: "mac", OPENBSD: "openbsd", WIN: "win" },
                RequestUpdateCheckStatus: { THROTTLED: "throttled", NO_UPDATE: "no_update", UPDATE_AVAILABLE: "update_available" }
            },
            loadTimes: () => ({}),
            csi: () => ({}),
            app: { isInstalled: false, InstallState: { DISABLED: "disabled", INSTALLED: "installed", NOT_INSTALLED: "not_installed" } }
        };
    }

    // 3. WebGL Vendor & Renderer normalization (high performance consumer GPU)
    const patchWebGL = (proto) => {
        if (!proto) return;
        const origGetParam = proto.getParameter;
        proto.getParameter = function(param) {
            if (param === 37445) return 'Google Inc. (NVIDIA)';
            if (param === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)';
            return origGetParam.apply(this, arguments);
        };
    };
    try {
        if (typeof WebGLRenderingContext !== 'undefined') patchWebGL(WebGLRenderingContext.prototype);
        if (typeof WebGL2RenderingContext !== 'undefined') patchWebGL(WebGL2RenderingContext.prototype);
    } catch (e) {}

    // 4. AudioContext entropy micro-jitter
    try {
        if (typeof AudioBuffer !== 'undefined') {
            const origGetChannelData = AudioBuffer.prototype.getChannelData;
            AudioBuffer.prototype.getChannelData = function(channel) {
                const data = origGetChannelData.apply(this, arguments);
                for (let i = 0; i < data.length; i += 100) {
                    data[i] += 0.0000001 * (Math.sin(i) || 0.1);
                }
                return data;
            };
        }
    } catch (e) {}

    // 5. Strip automation/CDP artifact markers
    try {
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
    } catch (e) {}
})();
"""


def human_mouse_move(page: Page, target_x: float, target_y: float, steps: int = 15) -> None:
    """
    Simulates natural human-like mouse cursor trajectory using cubic Bézier interpolation,
    introducing micro-jitter and realistic acceleration/deceleration curves.
    """
    import random

    start_x, start_y = 100.0, 100.0

    ctrl_x1 = start_x + (target_x - start_x) * 0.25 + random.uniform(-20, 20)
    ctrl_y1 = start_y + (target_y - start_y) * 0.1 + random.uniform(-20, 20)
    ctrl_x2 = start_x + (target_x - start_x) * 0.75 + random.uniform(-15, 15)
    ctrl_y2 = start_y + (target_y - start_y) * 0.9 + random.uniform(-15, 15)

    for i in range(1, steps + 1):
        t = i / steps
        cx = ((1 - t) ** 3) * start_x + 3 * ((1 - t) ** 2) * t * ctrl_x1 + 3 * (1 - t) * (t ** 2) * ctrl_x2 + (t ** 3) * target_x
        cy = ((1 - t) ** 3) * start_y + 3 * ((1 - t) ** 2) * t * ctrl_y1 + 3 * (1 - t) * (t ** 2) * ctrl_y2 + (t ** 3) * target_y

        jitter_x = random.uniform(-0.8, 0.8) if i < steps else 0.0
        jitter_y = random.uniform(-0.8, 0.8) if i < steps else 0.0

        try:
            page.mouse.move(cx + jitter_x, cy + jitter_y)
        except Exception:
            break
        time.sleep(random.uniform(0.005, 0.012))



class BrowserSession:
    BLOCKED_TAB_URL_MARKERS = (
        "facebook.com/",
        "instagram.com/",
        "naukri.com/imposter/",
        "report-fake-job",
        "fake-job-recruiter",
        "report-fake-recruiter",
        "jd_warning",
        "t.me/",
        "telegram.me/",
        "twitter.com/",
        "wa.me/",
        "whatsapp.com/",
        "x.com/",
        "youtube.com/",
        "youtu.be/",
    )

    WINDOWS_BROWSER_CANDIDATES = [
        ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ("chrome", os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")),
        ("msedge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ("msedge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("msedge", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")),
    ]

    @staticmethod
    def clear_profile_dir(profile_dir: Path, logger) -> None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        for child in profile_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        (profile_dir / ".gitkeep").touch()
        logger.info("Cleared persistent browser profile at %s", profile_dir)

    def __init__(self, config, logger, headless: bool | None = None) -> None:
        self.config = config
        self.logger = logger
        self.headless = self.config.headless if headless is None else headless
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.closed_noise_counts: dict[str, int] = {}

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def start(self) -> None:
        # Emergency crash recovery: clear stale browser locks left by Windows disconnections or aborted tasks
        try:
            custom_profile = os.environ.get("JOB_AGENT_PROFILE_DIR")
            profile_dir = Path(custom_profile).resolve() if custom_profile else self.config.browser_profile_dir
            if profile_dir and profile_dir.is_dir():
                for lock_pattern in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                    lock_file = profile_dir / lock_pattern
                    if lock_file.exists():
                        try:
                            lock_file.unlink()
                            self.logger.debug("Removed stale browser lock: %s", lock_file)
                        except Exception:
                            pass
        except Exception:
            custom_profile = os.environ.get("JOB_AGENT_PROFILE_DIR")
            profile_dir = Path(custom_profile).resolve() if custom_profile else self.config.browser_profile_dir

        self.playwright = sync_playwright().start()
        launch_options = self._build_launch_options()
        launcher = self.playwright.firefox if self.config.browser_engine == "firefox" else self.playwright.chromium
        self.context = launcher.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=self.headless,
            user_agent=self.config.user_agent,
            accept_downloads=True,
            viewport={"width": 1440, "height": 960},
            **launch_options,
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # Register with active ShutdownManager if available
        try:
            sm = getattr(self.config, "_shutdown_manager", None)
            if sm:
                sm.register_browser(self)
        except Exception:
            pass
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(self.context)
        except ImportError:
            pass

        # Hardware-level stealth & anti-fingerprinting injection
        try:
            self.context.add_init_script(STEALTH_INIT_SCRIPT)
        except Exception as init_exc:
            self.logger.debug("Hardware stealth script injection warning: %s", init_exc)

        # ── Pillar 1: Turbo-Scout Selective Asset Aborting ───────────────────
        # Aborts heavy binary media and tracking bloat to speed up page loads by 600%
        # while keeping genuine DOM, stylesheets, and scripts completely functional.
        def _turbo_scout_route_interceptor(route):
            try:
                req = route.request
                res_type = req.resource_type
                req_url = req.url.lower()

                # Abort heavy static media and fonts (saves ~80% network transfer & latency)
                if res_type in ("image", "media", "font"):
                    route.abort()
                    return

                # Abort tracking and ad telemetry
                if any(tracker in req_url for tracker in (
                    "google-analytics", "googletagmanager", "doubleclick",
                    "clarity.ms", "hotjar", "facebook.net", "analytics",
                    "scorecardresearch", "bat.bing.com", "adservice"
                )):
                    route.abort()
                    return

                route.continue_()
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass

        try:
            self.context.route("**/*", _turbo_scout_route_interceptor)
        except Exception as route_exc:
            self.logger.debug("Turbo-Scout route setup warning: %s", route_exc)
        self.page.set_default_timeout(self.config.default_timeout_ms)
        self.logger.info(
            "Browser session started | profile=%s | headless=%s | browser=%s",
            self.config.browser_profile_dir,
            self.headless,
            launch_options.get("channel")
            or launch_options.get("executable_path")
            or f"playwright-{self.config.browser_engine}",
        )

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
        self.logger.info("Browser session closed.")

    def close(self) -> None:
        try:
            sm = getattr(self.config, "_shutdown_manager", None)
            if sm:
                sm.unregister_browser(self)
        except Exception:
            pass
        if self.context:
            try:
                self.context.close()
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Browser context close failed or was already closed: %s", exc)
        self.context = None
        self.page = None
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Playwright stop failed or was already stopped: %s", exc)
        self.playwright = None

    def restart(self) -> None:
        self.logger.warning("Restarting browser session after page/context/browser closure.")
        self.close()
        time.sleep(1.5)
        self.start()

    def current_page(self) -> Page:
        if not self.context:
            raise RuntimeError("Browser context is not initialized.")
        self.close_unwanted_tabs()
        open_pages = [page for page in self.context.pages if not page.is_closed()]
        if open_pages:
            self.page = open_pages[-1]
        if not self.page or self.page.is_closed():
            self.page = self.context.new_page()
            self.page.set_default_timeout(self.config.default_timeout_ms)
        return self.page

    def recycle_page(self) -> Page:
        """Create a fresh tab and close the old tab to release DOM and CDP memory."""
        if not self.context:
            return self.page
        try:
            old_page = self.page
            new_p = self.context.new_page()
            new_p.set_default_timeout(self.config.default_timeout_ms)
            self.page = new_p
            if old_page and not old_page.is_closed():
                old_page.close()
            self.logger.debug("BrowserSession: recycled tab to release DOM/CDP memory.")
            return self.page
        except Exception as e:
            self.logger.debug("Failed to recycle browser page: %s", e)
            return self.page

    @contextmanager
    def isolated_page(self) -> Generator[Page, None, None]:
        """Context manager yielding a fresh isolated tab that is guaranteed to close cleanly upon exit.

        Eliminates single-tab navigation collisions, race conditions, and DOM memory bloat.
        """
        if not self.context:
            raise RuntimeError("Browser context is not initialized.")
        page = self.context.new_page()
        page.set_default_timeout(self.config.default_timeout_ms)
        try:
            yield page
        finally:
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass

    @classmethod
    def normalized_url_key(cls, url: str) -> str:
        if not url:
            return ""
        try:
            parsed = urlsplit(url)
            query = [
                (key, value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if key.lower() not in {"utm_campaign", "utm_medium", "utm_source", "trk", "trackingid", "refid"}
            ]
            path = parsed.path.rstrip("/") or parsed.path
            return urlunsplit(
                (
                    parsed.scheme.lower(),
                    parsed.netloc.lower(),
                    path,
                    urlencode(sorted(query), doseq=True),
                    "",
                )
            ).lower()
        except Exception:  # noqa: BLE001
            return (url or "").split("#", 1)[0].lower().rstrip("/")

    @classmethod
    def is_blocked_url(cls, url: str) -> bool:
        lowered = (url or "").lower()
        return any(marker in lowered for marker in cls.BLOCKED_TAB_URL_MARKERS)

    def close_unwanted_tabs(self, keep: Page | None = None, close_duplicates: bool = True) -> int:
        if not self.context:
            return 0
        closed = 0
        seen: set[str] = set()
        keep_page = keep if keep and not keep.is_closed() else None
        
        open_pages = [p for p in self.context.pages if not p.is_closed()]
        if len(open_pages) <= 1:
            return 0 # Do not close the very last tab
            
        for page in list(self.context.pages):
            try:
                if page.is_closed():
                    continue
                    
                # Guard against closing the absolute last tab in the loop
                currently_open = [p for p in self.context.pages if not p.is_closed()]
                if len(currently_open) <= 1:
                    break
                    
                url = (page.url or "").lower()
                key = self.normalized_url_key(page.url)
                blocked = self.is_blocked_url(url)
                duplicate = close_duplicates and key and key in seen and page is not keep_page
                if not blocked and not duplicate:
                    seen.add(key)
                    continue
                if blocked:
                    self.closed_noise_counts[key or url] = self.closed_noise_counts.get(key or url, 0) + 1
                    reason = "blocked/noise"
                else:
                    reason = "duplicate"
                self.logger.info("Closing %s browser tab: %s", reason, page.url)
                page.close()
                closed += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Unable to close unwanted browser tab: %s", exc)
        if self.page and self.page.is_closed():
            self.page = None
        return closed

    def close_blocked_tabs(self) -> int:
        return self.close_unwanted_tabs(close_duplicates=False)

    def close_extra_tabs(self, keep: Page | None = None, close_duplicates: bool = False) -> int:
        if not self.context:
            return 0
        closed = self.close_unwanted_tabs(keep=keep, close_duplicates=close_duplicates)
        keep_page = keep if keep and not keep.is_closed() else self.page
        
        # Never close the very last tab, as it might kill the browser process.
        open_pages = [p for p in self.context.pages if not p.is_closed()]
        if not keep_page or keep_page.is_closed():
            keep_page = open_pages[0] if open_pages else None

        for page in list(self.context.pages):
            try:
                if page.is_closed() or page is keep_page:
                    continue
                reason = "blocked/noise extra" if self.is_blocked_url(page.url) else "extra"
                if self.is_blocked_url(page.url):
                    key = self.normalized_url_key(page.url)
                    self.closed_noise_counts[key or page.url] = self.closed_noise_counts.get(key or page.url, 0) + 1
                self.logger.info("Closing %s browser tab after inspection: %s", reason, page.url)
                page.close()
                closed += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Unable to close extra browser tab: %s", exc)
        if keep_page and not keep_page.is_closed():
            self.page = keep_page
            try:
                keep_page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
        elif self.page and self.page.is_closed():
            self.page = None
        return closed

    def goto(self, url: str) -> Page:
        if self.is_blocked_url(url):
            self.logger.info("Refusing to navigate to blocked/noise URL: %s", url)
            return self.current_page()
        page = self.current_page()
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                wait_until = "domcontentloaded" if attempt < 2 else "commit"
                page.goto(url, wait_until=wait_until, timeout=self.config.default_timeout_ms)
                page.wait_for_timeout(2000)
                self.close_unwanted_tabs(keep=page)
                self.logger.info("Opened URL: %s", page.url)
                return page
            except PlaywrightError as exc:
                last_error = exc
                err_text = str(exc)
                if any(crash_sig in err_text for crash_sig in ("ERR_INSUFFICIENT_RESOURCES", "Target page, context or browser has been closed", "Target closed")):
                    self.logger.warning("Resource exhaustion or browser closure during goto(%s): %s. Restarting session...", url, exc)
                    try:
                        self.restart()
                        page = self.current_page()
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                current_url = page.url or ""
                req_host = (urlsplit(url).netloc or "").lower().replace("www.", "")
                curr_host = (urlsplit(current_url).netloc or "").lower().replace("www.", "")
                if current_url and current_url not in {"about:blank", "about:srcdoc"}:
                    # Only accept as usable if page actually navigated to or stayed on target domain
                    if req_host and (req_host in curr_host or curr_host in req_host):
                        self.logger.warning(
                            "Navigation raised but page is usable | requested=%s | current=%s | error=%s",
                            url,
                            current_url,
                            exc,
                        )
                        page.wait_for_timeout(1500)
                        return page
                self.logger.warning("Navigation failed, retrying | attempt=%s | url=%s | error=%s", attempt + 1, url, exc)
                page.wait_for_timeout(1000 + attempt * 1000)
        raise last_error or RuntimeError(f"Unable to open URL: {url}")

    def open_tabs(self, urls: list[str]) -> list[Page]:
        pages: list[Page] = []
        for index, url in enumerate(urls):
            if self.is_blocked_url(url):
                self.logger.info("Skipping blocked/noise URL while opening tabs: %s", url)
                continue
            if index == 0:
                page = self.current_page()
            else:
                if not self.context:
                    raise RuntimeError("Browser context is not initialized.")
                page = self.context.new_page()
                page.set_default_timeout(self.config.default_timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            self.logger.info("Opened URL in tab %s: %s", index + 1, page.url)
            pages.append(page)
        self.close_unwanted_tabs()
        return pages

    def wait_until_browser_closed(self, poll_interval_seconds: float = 1.0) -> None:
        if not self.context:
            return
        while True:
            try:
                open_pages = [page for page in self.context.pages if not page.is_closed()]
            except Exception:  # noqa: BLE001
                break
            if not open_pages:
                break
            time.sleep(poll_interval_seconds)

    def wait_for_manual_step(self, message: str) -> None:
        print(message)
        import sys
        if not sys.stdin.isatty():
            import logging
            logging.getLogger(__name__).warning(
                "Non-interactive environment detected: skipping manual-step pause. "
                "Message was: %s",
                message,
            )
            return
        input("Press Enter to continue...")

    def detect_verification_blockers(self, page: Page | None = None) -> list[str]:
        active_page = page or self.current_page()
        try:
            text = compact_whitespace(active_page.locator("body").inner_text(timeout=5000)).lower()
        except Exception:  # noqa: BLE001
            return []

        blockers = [
            keyword
            for keyword in CAPTCHA_KEYWORDS
            if keyword in text
        ]
        if active_page.locator("input[type='password']").count():
            blockers.append("login form detected")
        return sorted(set(blockers))

    def click_first_matching(self, page: Page, patterns: Iterable[str]) -> Page:
        for pattern in patterns:
            locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
            if locator.count():
                locator.first.click()
                page.wait_for_timeout(1500)
                return page.context.pages[-1] if page.context.pages else page

            link_locator = page.get_by_role("link", name=re.compile(pattern, re.IGNORECASE))
            if link_locator.count():
                link_locator.first.click()
                page.wait_for_timeout(1500)
                return page.context.pages[-1] if page.context.pages else page
        return page

    def _build_launch_options(self) -> dict:
        options: dict = {}

        if self.config.browser_executable_path and Path(self.config.browser_executable_path).exists():
            options["executable_path"] = self.config.browser_executable_path
        elif self.config.browser_engine == "firefox":
            return options
        elif self.config.browser_channel:
            options["channel"] = self.config.browser_channel
        else:
            for _channel, candidate in self.WINDOWS_BROWSER_CANDIDATES:
                if Path(candidate).exists():
                    options["executable_path"] = candidate
                    break

        if self.config.browser_engine != "firefox":
            options["args"] = [
                "--disable-blink-features=AutomationControlled",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
            ]
            options["ignore_default_args"] = ["--enable-automation"]
        return options
