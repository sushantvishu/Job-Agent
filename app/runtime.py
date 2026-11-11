"""
app/runtime.py — Central Dependency Injection Factory for Job Agent Framework.

Builds and coordinates runtime objects:
- Config, Logger, JobTracker, ProfileData, AnswerTemplates
- JobCollector, JobMatcher, OllamaClient, FormFiller, Exporter
- ShutdownManager (process signal and resource management)
"""
from __future__ import annotations

import logging
import shutil
from typing import Any

from app.config import AppConfig, load_config
from app.exporter import Exporter
from app.form_filler import FormFiller
from app.job_collector import JobCollector
from app.matcher import JobMatcher
from app.ollama_client import OllamaClient
from app.profile_loader import ProfileData, load_answer_templates, load_profile
from app.tracker import JobTracker
from app.utils import setup_logger


def ensure_runtime_layout(config: AppConfig) -> None:
    """Ensure all required framework directories exist."""
    for path in [
        config.app_dir,
        config.profile_dir,
        config.templates_dir,
        config.jobs_dir,
        config.logs_dir,
        config.exports_dir,
        config.browser_profile_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    if not config.env_path.exists() and (config.project_root / ".env.example").exists():
        shutil.copyfile(config.project_root / ".env.example", config.env_path)


def build_runtime(profile_name: str | None = None) -> tuple[
    AppConfig,
    logging.Logger,
    JobTracker,
    ProfileData,
    JobCollector,
    JobMatcher,
    FormFiller,
    Exporter,
]:
    """
    Builds the complete operational runtime for the Job Agent framework.
    Returns:
        (config, logger, tracker, profile, collector, matcher, filler, exporter)
    """
    config = load_config(profile_name=profile_name)
    ensure_runtime_layout(config)
    logger = setup_logger(config.log_path, config.log_level)

    # Initialize and register Windows Disconnection & Crash Fail-Safe Manager
    try:
        from app.shutdown import ShutdownManager

        shutdown_mgr = ShutdownManager(logger)
        shutdown_mgr.register()
        setattr(config, "_shutdown_manager", shutdown_mgr)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not register ShutdownManager: %s", exc)

    tracker = JobTracker(config.db_path, logger)
    tracker.init_db()

    profile = load_profile(config.profile_path)
    templates = load_answer_templates(config.answer_templates_path)
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

    exporter = Exporter(config.exports_dir, logger)

    return config, logger, tracker, profile, collector, matcher, filler, exporter
