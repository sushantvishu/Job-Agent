import math
import random
import time
from playwright.sync_api import Page, Locator

class CaptchaDefeater:
    """
    A free, heuristic CAPTCHA bypass engine using biometric mouse emulation.
    Defeats standard reCAPTCHA v2 and Cloudflare Turnstile checkpoints without paid APIs.
    """
    def __init__(self, page: Page, logger):
        self.page = page
        self.logger = logger

    def _human_mouse_move(self, x: float, y: float, steps: int = 15):
        """Simulates a non-linear, bezier-like human mouse movement."""
        start_x = random.randint(0, self.page.viewport_size["width"] or 1000)
        start_y = random.randint(0, self.page.viewport_size["height"] or 800)
        
        self.page.mouse.move(start_x, start_y)
        for i in range(1, steps + 1):
            t = i / steps
            # Add jitter
            jitter_x = random.uniform(-2, 2)
            jitter_y = random.uniform(-2, 2)
            # Ease-out calculation
            ease_t = 1 - math.pow(1 - t, 3)
            current_x = start_x + (x - start_x) * ease_t + jitter_x
            current_y = start_y + (y - start_y) * ease_t + jitter_y
            self.page.mouse.move(current_x, current_y)
            time.sleep(random.uniform(0.01, 0.04))

    def solve_if_present(self) -> bool:
        """
        Scans for visible CAPTCHA iframes and attempts to defeat them.
        Returns True if a CAPTCHA was found and an attempt was made.
        """
        solved = False
        try:
            # 1. Google reCAPTCHA v2
            recaptcha_frames = self.page.frames
            for frame in recaptcha_frames:
                if "recaptcha" in frame.url:
                    checkbox = frame.locator(".recaptcha-checkbox-border")
                    if checkbox.count() > 0 and checkbox.first.is_visible():
                        self.logger.info("Detected reCAPTCHA v2 checkpoint. Engaging biometric solver...")
                        box = checkbox.first.bounding_box()
                        if box:
                            target_x = box["x"] + box["width"] / 2
                            target_y = box["y"] + box["height"] / 2
                            self._human_mouse_move(target_x, target_y)
                            time.sleep(random.uniform(0.2, 0.5))
                            self.page.mouse.click(target_x, target_y)
                            self.page.wait_for_timeout(3000)
                            solved = True

            # 2. Cloudflare Turnstile
            turnstile_frames = [f for f in self.page.frames if "turnstile" in f.url]
            for frame in turnstile_frames:
                checkbox = frame.locator("input[type='checkbox']")
                if checkbox.count() > 0 and checkbox.first.is_visible():
                    self.logger.info("Detected Cloudflare Turnstile checkpoint. Engaging bypass...")
                    box = checkbox.first.bounding_box()
                    if box:
                        target_x = box["x"] + box["width"] / 2
                        target_y = box["y"] + box["height"] / 2
                        self._human_mouse_move(target_x, target_y)
                        time.sleep(random.uniform(0.2, 0.5))
                        self.page.mouse.click(target_x, target_y)
                        self.page.wait_for_timeout(3000)
                        solved = True

        except Exception as e:
            self.logger.warning(f"CaptchaDefeater encountered an error: {e}")
            
        return solved
