"""
config/settings.py — Configuration loader and environment variable manager.

Loads all runtime configurations dynamically from environment variables (.env)
with strict validation, fallback defaults, and zero hardcoded credentials.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Base project paths
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
ENV_EXAMPLE_PATH = BASE_DIR / ".env.example"

# Load environment: priority to .env, fallback to .env.example
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(dotenv_path=ENV_EXAMPLE_PATH, override=False)


@dataclass
class Settings:
    """Application configuration and credentials container."""

    # ─── Project Directories ───────────────────────────────────────────
    project_root: Path = BASE_DIR
    config_dir: Path = BASE_DIR / "config"
    database_dir: Path = BASE_DIR / "database"
    logs_dir: Path = BASE_DIR / "logs"
    src_dir: Path = BASE_DIR / "src"
    
    # ─── Database Path ─────────────────────────────────────────────────
    db_path: Path = field(default_factory=lambda: BASE_DIR / os.getenv("DB_PATH", "database/jobs.db"))

    # ─── Candidate Information ─────────────────────────────────────────
    candidate_name: str = field(default_factory=lambda: os.getenv("CANDIDATE_NAME", "Jane Doe"))
    candidate_email: str = field(default_factory=lambda: os.getenv("CANDIDATE_EMAIL", "jane.doe@example.com"))
    candidate_phone: str = field(default_factory=lambda: os.getenv("CANDIDATE_PHONE", "+1-555-000-1234"))
    resume_path: Path = field(
        default_factory=lambda: Path(os.getenv("RESUME_PATH", str(BASE_DIR / "profile" / "resume.pdf")))
    )
    linkedin_url: str = field(default_factory=lambda: os.getenv("LINKEDIN_URL", "https://www.linkedin.com/in/your-profile"))
    github_url: str = field(default_factory=lambda: os.getenv("GITHUB_URL", "https://github.com/your-username"))
    portfolio_url: str = field(default_factory=lambda: os.getenv("PORTFOLIO_URL", ""))

    # ─── Job Target Preferences ────────────────────────────────────────
    target_role: str = field(default_factory=lambda: os.getenv("TARGET_ROLE", "Software Engineer"))
    target_locations: List[str] = field(
        default_factory=lambda: [
            loc.strip() for loc in os.getenv("TARGET_LOCATIONS", "Remote, Bengaluru, San Francisco").split(",") if loc.strip()
        ]
    )
    experience_years: float = field(
        default_factory=lambda: float(os.getenv("EXPERIENCE_YEARS", "1.0"))
    )
    notice_period: str = field(default_factory=lambda: os.getenv("NOTICE_PERIOD", "Immediate"))
    expected_salary: str = field(default_factory=lambda: os.getenv("EXPECTED_SALARY", "Competitive"))

    # ─── Browser Automation (Selenium) ─────────────────────────────────
    browser_type: str = field(default_factory=lambda: os.getenv("BROWSER_TYPE", "chrome").lower())
    headless: bool = field(
        default_factory=lambda: os.getenv("HEADLESS", "false").strip().lower() in ("true", "1", "yes")
    )
    browser_timeout: int = field(
        default_factory=lambda: int(os.getenv("BROWSER_TIMEOUT_SECONDS", "30"))
    )
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
    )

    # ─── AI / LLM Integration ──────────────────────────────────────────
    ai_api_style: str = field(default_factory=lambda: os.getenv("AI_API_STYLE", "ollama").lower())
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    ai_base_url: str = field(
        default_factory=lambda: os.getenv("LOCAL_AI_BASE_URL", "http://127.0.0.1:11434")
    )
    ai_model: str = field(
        default_factory=lambda: os.getenv("LOCAL_AI_MODEL", "qwen2.5:7b-instruct")
    )

    # ─── Java Subprocess Components ────────────────────────────────────
    java_enabled: bool = field(
        default_factory=lambda: os.getenv("JAVA_ENABLED", "true").strip().lower() in ("true", "1", "yes")
    )
    java_home: str = field(default_factory=lambda: os.getenv("JAVA_HOME", ""))
    java_binary: str = field(default_factory=lambda: os.getenv("JAVA_BINARY", "java"))

    # ─── Logging & Auditing ────────────────────────────────────────────
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    log_file_path: Path = field(
        default_factory=lambda: BASE_DIR / "logs" / os.getenv("LOG_FILENAME", "job_agent.log")
    )

    def __post_init__(self) -> None:
        """Validate and resolve required filesystem paths."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.database_dir.mkdir(parents=True, exist_ok=True)
        
        # Ensure db path parent exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


# Global singleton settings instance
settings = Settings()
