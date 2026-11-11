# Contributing to Job Agent

Thank you for your interest in contributing to **Job Agent**! We welcome community contributions to improve platform support, ATS form-filling accuracy, AI reasoning, and dashboard telemetry.

---

## 🚀 Getting Started

1. **Fork and Clone the Repository**
   ```bash
   git clone https://github.com/your-username/Job-Agent.git
   cd Job-Agent
   ```

2. **Create a Virtual Environment**
   ```bash
   python -m venv .venv
   # Windows:
   .\.venv\Scripts\Activate.ps1
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Set Up Local Configuration**
   ```bash
   # Windows:
   copy .env.example .env
   copy profile\profile.example.json profile\profile.json

   # Linux/macOS:
   cp .env.example .env
   cp profile/profile.example.json profile/profile.json
   ```
   Edit `.env` and `profile/profile.json` with your test configurations. Note that `.env` and `profile/profile.json` are git-ignored to prevent accidental credential or personal information leakage.

5. **Verify System Integrity**
   ```bash
   python src/main.py init
   ```

---

## 🏗 Project Architecture & Key Modules

- **`src/`**: Modular, decoupled entry points and hybrid components
  - `main.py`: Unified Typer CLI entrypoint (`init`, `run`, `dashboard`, `apply-posts`, `sync-inbox`, etc.)
  - `agent.py`: High-level discovery and scraping orchestrator
  - `browser.py`: Selenium WebDriver manager with CDP stealth masking
  - `java_runner.py` & `JavaBridge.java`: High-performance deduplication and token scoring bridge
  - `tracker.py`: SQLite database application tracker and analytics

- **`app/`**: Core enterprise automation engine
  - `form_filler.py`: Multi-step ATS auto-filler (Greenhouse, Lever, Workday, SmartRecruiters, BambooHR, Ashby, Taleo)
  - `job_collector.py`: Multi-board job collector & link extractor
  - `linkedin_post_scanner.py`: LinkedIn post scanner for hiring manager outreach
  - `cover_email_composer.py`: Ollama LLM tailored cover email generator
  - `email_sender.py`: SMTP dispatcher with quota tracking & resume attachment
  - `inbound_sync.py` & `email_followup.py`: Recruiter inbox triage & interview invitation tracking
  - `resume_compiler.py` & `resume_tailorer.py`: ATS-tailored resume compiler (Typst & HTML)
  - `web_radar.py`: Mission Control zero-dependency web dashboard server (`http://127.0.0.1:8765`)
  - `scrapers/`: Individual scrapers (LinkedIn, Naukri, Foundit, Wellfound, Instahyre, ATS)
  - `shutdown.py`: Graceful resource cleanup, browser shutdown, and RAM conservation

- **`templates/`**: Resume compilation templates and baseline answer templates.

---

## 🛠 Coding Guidelines

- **Privacy & Safety First**: Never hardcode personal data, credentials, or cookies. All configurations must be sourced dynamically via `os.getenv` or `.env`.
- **Preserve Documentation**: Maintain existing docstrings, type annotations, and architecture comments.
- **Resource Hygiene**: Always use `try...finally` or context managers to release browser sessions, database connections, and subprocesses.
- **Graceful Fallbacks**: If external runtimes (such as Java or Ollama) are unavailable, always ensure fallback logic executes cleanly without crashing the application.

---

## 📬 Submitting Pull Requests

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Commit your changes with clear, descriptive commit messages:
   ```bash
   git commit -m "feat(form_filler): add support for Workday multi-step textareas"
   ```
3. Push to your fork and submit a Pull Request to `main`.

Thank you for helping build an open, ethical, and powerful job search automation platform!
