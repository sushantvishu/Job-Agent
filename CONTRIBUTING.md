# Contributing to Job Agent

Thank you for your interest in contributing to **Job Agent**! We welcome community contributions to improve platform support, form filling accuracy, and AI matching.

---

## Getting Started

1. **Fork and Clone the Repository**
   ```bash
   git clone https://github.com/your-username/job-agent.git
   cd job-agent
   ```

2. **Create a Virtual Environment**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
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
   cp .env.example .env
   cp profile/profile.example.json profile/profile.json
   ```
   Edit `.env` and `profile/profile.json` with your test configurations. Note that `.env` and `profile/profile.json` are git-ignored to prevent accidental credential leakage.

---

## Project Architecture

- **`app/`**: Core framework
  - `main.py`: Typer CLI entrypoint and platform analytics commands
  - `browser.py`: Playwright browser session manager, stealth mode, and tab lifecycle
  - `form_filler.py`: Multi-step form auto-filler, ARIA dropdown handlers, and safe submit
  - `job_collector.py`: Job scout and search discovery for Naukri & LinkedIn
  - `matcher.py`: Match scoring and qualification rule engine
  - `ollama_client.py`: Local AI client for answering application questionnaires
  - `tracker.py`: SQLite database state tracker and metrics
  - `shutdown.py`: Resource and connection cleanup manager

- **`templates/`**: Saved question-answer templates and fallback structures.

---

## Coding Guidelines

- **Code Formatting & Linting**: We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting. Ensure your changes follow PEP 8.
- **Safety First**: Never auto-submit applications on unknown sites without user consent gates.
- **Preserve Comments & Docstrings**: Maintain existing architectural documentation and inline comments.
- **Resource Cleanup**: Always use `try...finally` or `ShutdownManager` to release browser sessions, database cursors, and network ports.

---

## Submitting Pull Requests

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Commit your changes with clear, descriptive commit messages:
   ```bash
   git commit -m "feat(form_filler): add support for Workday multi-step textareas"
   ```
3. Push to your branch and open a Pull Request against `main`.

Thank you for helping build an open, ethical, and powerful job search automation platform!

