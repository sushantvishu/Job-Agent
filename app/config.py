from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class MaskedSecret(str):
    """String subclass that prevents credential leakage in repr(), logs, and tracebacks."""

    def __repr__(self) -> str:
        return "'**********'" if self else "''"

    def get_secret_value(self) -> str:
        return str(self)


class AppConfig(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    project_root: Path
    app_dir: Path
    profile_dir: Path
    templates_dir: Path
    jobs_dir: Path
    logs_dir: Path
    exports_dir: Path
    browser_profile_dir: Path
    browser_engine: str = "chrome"
    env_path: Path
    db_path: Path
    profile_path: Path
    resume_path: Path
    answer_templates_path: Path
    scoring_rules_path: Path
    urls_path: Path
    email_accounts_path: Path
    log_path: Path
    active_profile: str = "default"
    ai_api_style: str = "ollama"
    ai_api_key: MaskedSecret = Field(default_factory=lambda: MaskedSecret(""))
    ollama_base_url: str
    ollama_model: str
    fallback_models: list[str] = Field(default_factory=list)
    default_timeout_ms: int = 45000
    log_level: str = "INFO"
    headless: bool = False
    browser_channel: str = "chrome"
    browser_executable_path: str = ""
    company_site_login_email: str = ""
    company_site_login_password: MaskedSecret = Field(default_factory=lambda: MaskedSecret(""))
    smtp_sender_password: MaskedSecret = Field(default_factory=lambda: MaskedSecret(""))
    otp_email_imap_host: str = "imap.gmail.com"
    otp_email_address: str = ""
    otp_email_app_password: MaskedSecret = Field(default_factory=lambda: MaskedSecret(""))
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    )

    def validate_safe_path(self, path: Path) -> Path:
        """Verify that a path is strictly confined within project boundaries."""
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.project_root.resolve()):
            raise ValueError(f"Security: Path traversal violation for {path}")
        return resolved


@lru_cache(maxsize=16)
def load_config(profile_name: str | None = None) -> AppConfig:
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    fallback_env = project_root / ".env.example"
    load_dotenv(env_path if env_path.exists() else fallback_env)

    # Determine active profile
    selected_profile = profile_name or os.getenv("JOB_AGENT_PROFILE") or "default"
    if selected_profile != "default" and (project_root / "profiles" / selected_profile / "profile.json").exists():
        profile_dir = project_root / "profiles" / selected_profile
        profile_path = profile_dir / "profile.json"
    else:
        profile_dir = project_root / "profile"
        profile_path = profile_dir / "profile.json"
        selected_profile = "default"

    fallback_models = [
        item.strip()
        for item in os.getenv("LOCAL_AI_FALLBACK_MODELS", "").split(",")
        if item.strip()
    ]

    browser_engine = os.getenv("PLAYWRIGHT_BROWSER", "chrome").lower()
    browser_profile_dir = project_root / ("browser-profile-firefox" if browser_engine == "firefox" else "browser-profile")
    email_accounts_path = Path(os.getenv("EMAIL_ACCOUNTS_PATH", str(project_root / "profile" / "email_accounts.json")))
    if not email_accounts_path.is_absolute():
        email_accounts_path = project_root / email_accounts_path

    # Auto-discover resume file dynamically from profile directory or root profile directory
    default_resume = project_root / "profile" / "resume.pdf"
    for candidate_name in ("resume.pdf", "Resume.pdf", "CV.pdf", "cv.pdf"):
        # Check profile-specific dir first, then global profile dir
        candidate_path = profile_dir / candidate_name
        if candidate_path.exists():
            default_resume = candidate_path
            break
        global_path = project_root / "profile" / candidate_name
        if global_path.exists():
            default_resume = global_path
            break

    browser_channel = os.getenv("PLAYWRIGHT_BROWSER_CHANNEL", "chrome" if browser_engine in ("chrome", "chromium") else "")

    return AppConfig(
        project_root=project_root,
        app_dir=project_root / "app",
        profile_dir=profile_dir,
        templates_dir=project_root / "templates",
        jobs_dir=project_root / "jobs",
        logs_dir=project_root / "logs",
        exports_dir=project_root / "exports",
        browser_profile_dir=browser_profile_dir,
        browser_engine=browser_engine,
        env_path=env_path,
        db_path=project_root / "jobs.db",
        profile_path=profile_path,
        resume_path=default_resume,
        answer_templates_path=project_root / "templates" / "answer_templates.json",
        scoring_rules_path=project_root / "templates" / "job_scoring_rules.md",
        urls_path=project_root / "jobs" / "urls.txt",
        email_accounts_path=email_accounts_path,
        log_path=project_root / "logs" / "job_agent.log",
        active_profile=selected_profile,
        ai_api_style=os.getenv("AI_API_STYLE", "ollama").lower(),
        ai_api_key=MaskedSecret(os.getenv("LOCAL_AI_API_KEY") or os.getenv("AI_API_KEY", "")),
        ollama_base_url=os.getenv("LOCAL_AI_BASE_URL") or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("LOCAL_AI_MODEL") or os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
        fallback_models=fallback_models,
        default_timeout_ms=int(os.getenv("DEFAULT_TIMEOUT_MS", "45000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        headless=os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true",
        browser_channel=browser_channel,
        browser_executable_path=os.getenv("PLAYWRIGHT_BROWSER_EXECUTABLE", ""),
        company_site_login_email=os.getenv("COMPANY_SITE_LOGIN_EMAIL", ""),
        company_site_login_password=MaskedSecret(os.getenv("COMPANY_SITE_LOGIN_PASSWORD", "")),
        smtp_sender_password=MaskedSecret(
            os.getenv("JOB_AGENT_GMAIL_PRIMARY_APP_PASSWORD")
            or os.getenv("SMTP_SENDER_APP_PASSWORD")
            or os.getenv("OTP_EMAIL_APP_PASSWORD", "")
        ),
        otp_email_imap_host=os.getenv("OTP_EMAIL_IMAP_HOST", "imap.gmail.com"),
        otp_email_address=os.getenv("OTP_EMAIL_ADDRESS", ""),
        otp_email_app_password=MaskedSecret(os.getenv("OTP_EMAIL_APP_PASSWORD", "")),
    )
