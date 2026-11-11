"""
Review and submit ID 2014 (Codoid) and ID 1572 (First Advantage).
"""
import logging
import sys
from pathlib import Path

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.browser import BrowserSession
from app.form_filler import FormFiller
from app.job_collector import JobCollector
from app.matcher import JobMatcher
from app.profile_loader import load_profile, load_answer_templates
from app.tracker import JobTracker
from app.ollama_client import OllamaClient
import sqlite3

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("submit_autorun")

config = load_config()
profile = load_profile(config.profile_path)
templates = load_answer_templates(config.answer_templates_path)
tracker = JobTracker(config.db_path, logger)
collector = JobCollector(logger)
matcher = JobMatcher(profile)
ollama_client = OllamaClient(
    config.ollama_base_url,
    config.ollama_model,
    logger,
    timeout=max(30, config.default_timeout_ms // 1000),
    api_style=config.ai_api_style,
    fallback_models=config.fallback_models,
    api_key=config.ai_api_key,
)
filler = FormFiller(config, logger, ollama_client, non_interactive=True)
filler.set_templates(templates)

targets = [2014, 1572]

with sqlite3.connect(config.db_path) as conn:
    c = conn.cursor()
    c.execute(f"SELECT id, title, company, url, score, source FROM jobs WHERE id IN ({','.join(map(str, targets))})")
    rows = c.fetchall()

with BrowserSession(config, logger, headless=True) as browser:
    for j_id, title, company, url, score, source in rows:
        logger.info("=== Processing ID %d: %s @ %s ===", j_id, title, company)
        page = browser.current_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            
            body_text = page.inner_text("body").lower()
            if "already applied" in body_text or "applied on" in body_text:
                logger.info("Already applied on page.")
                with tracker._connect() as conn:
                    conn.execute("UPDATE jobs SET status = 'applied', reason = 'already applied on site', applied_at = datetime('now') WHERE id = ?", (j_id,))
                continue

            job = collector.collect(page, url)
            match = matcher.score(job)
            fill_result, active_page = filler.fill(page=page, job=job, match=match, profile=profile, auto_submit_safe=True)
            logger.info("Fill result status: %s, blockers: %s", fill_result.status, fill_result.submit_blockers)
            
            if fill_result.status == "applied":
                logger.info("[SUCCESS - APPLIED] %s", title)
                with tracker._connect() as conn:
                    conn.execute("UPDATE jobs SET status = 'applied', reason = 'auto-submitted after review', applied_at = datetime('now') WHERE id = ?", (j_id,))
            elif fill_result.ready_to_submit or not fill_result.submit_blockers:
                submitted, msg = filler.submit_final(active_page, explicit_confirmation=False)
                if submitted:
                    logger.info("[SUCCESS - SUBMITTED FINAL] %s: %s", title, msg)
                    with tracker._connect() as conn:
                        conn.execute("UPDATE jobs SET status = 'applied', reason = 'submitted after review', applied_at = datetime('now') WHERE id = ?", (j_id,))
                else:
                    logger.warning("Could not submit final: %s", msg)
        except Exception as e:
            logger.error("Error processing ID %d: %s", j_id, e)
        finally:
            try:
                browser.close_extra_tabs()
            except Exception:
                pass
