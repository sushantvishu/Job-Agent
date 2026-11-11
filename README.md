# 🤖 Job Agent Framework

> **A robust, plug-and-play, open-source job application and scraping automation framework.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Local AI](https://img.shields.io/badge/Local%20AI-Ollama-blueviolet.svg)](https://ollama.com/)
[![Selenium WebDriver](https://img.shields.io/badge/Browser%20Automation-Selenium-green.svg)](https://www.selenium.dev/)
[![Java Bridge](https://img.shields.io/badge/Java-Subprocess%20Bridge-orange.svg)](https://openjdk.org/)
[![SQLite Self--Healing](https://img.shields.io/badge/Database-SQLite%20Self--Healing-lightblue.svg)](https://www.sqlite.org/)

---

## 📌 Overview

Job Agent is a production-ready, open-source automation framework designed to streamline and automate job searching, opportunity scoring, and application tracking across multiple job boards (LinkedIn, Naukri, and direct career portals). 

The framework is completely decoupled from any personal user data, credential-sanitized, and driven entirely by dynamic environment variables (`.env`) and local configuration files.

---

## 🏗 Directory Structure

The project is strictly organized into this modular hierarchy:

```text
Job-agent/
├── config/                  # Configurations and environment setups
│   ├── __init__.py
│   ├── settings.py          # Dynamic environment configuration loader
│   └── settings.example.yaml# Example community configuration
├── database/                # Database initialization scripts and schemas
│   ├── __init__.py
│   ├── init_db.py           # Self-healing SQLite initializer & health checks
│   └── schema.sql           # SQLite table schemas & performance indices
├── logs/                    # Isolated scraped job logs & audit trails (.gitkeep)
├── src/                     # Core Python and Java source code
│   ├── __init__.py
│   ├── agent.py             # Core job scraping and evaluation orchestrator
│   ├── browser.py           # Cross-platform portable Selenium WebDriver
│   ├── java_runner.py       # Seamless Python-to-Java subprocess bridge
│   ├── JavaBridge.java      # Fast Java deduplication & scoring component
│   ├── tracker.py           # SQLite job status and log isolation tracker
│   └── main.py              # CLI entry point (init, run, stats, open-browser)
├── profile/                 # Profile templates (git-ignored for privacy)
│   ├── profile.example.json # Template for candidate information
│   └── email_accounts.example.json
├── jobs/                    # URL target seeds (git-ignored for live runs)
│   └── urls.example.txt     # Example seed URLs for LinkedIn and Naukri
├── .env.example             # Template for all environment variables
├── .gitignore               # Strict exclusion rules (secrets, db, logs, bytecode)
├── requirements.txt         # Complete Python dependencies
└── README.md                # Documentation and Quick Start Guide
```

---

## 🚀 Quick Start Guide

Follow these steps to set up and run Job Agent on your machine.

### 1. Clone the Repository
```bash
git clone https://github.com/YOUR_USERNAME/job-agent.git
cd job-agent
```

### 2. Set Up a Python Virtual Environment
**On Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**On Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your details:
```bash
cp .env.example .env
```
*(On Windows: `copy .env.example .env`)*

Open `.env` in your editor and set:
- `CANDIDATE_NAME`, `CANDIDATE_EMAIL`, `CANDIDATE_PHONE`
- `TARGET_ROLE` (e.g. `"Software Engineer"` or `"Python Developer"`)
- `BROWSER_TYPE` (`chrome` or `firefox`)
- `HEADLESS` (`false` to view the browser window, `true` for background runs)

### 5. Initialize the Self-Healing Database
Run the system initialization command:
```bash
python src/main.py init
```
This automatically:
- Checks if `database/jobs.db` exists; if not, creates it and applies `database/schema.sql`.
- Checks for Java runtime availability, compiling `JavaBridge.java` via `javac` on demand.
- Verifies your logging and profile configurations.

### 6. Add Job URLs & Execute Queue
Add your target job search or posting URLs into `jobs/urls.example.txt` (or create `jobs/urls.txt`):
```bash
python src/main.py run --input jobs/urls.example.txt
```

### 7. Inspect Application Metrics
```bash
python src/main.py stats
```

---

## 🧠 Local AI & LLM Integration (Ollama)

The framework includes native integration with **[Ollama](https://ollama.com/)** for 100% offline, privacy-first AI intelligence with **zero API costs**:

- **Automated Form & Questionnaire Answering**: Dynamically responds to complex screening questions (*"Why are you a good fit for this role?"*, *"Describe your experience with X"*) based on your loaded candidate profile.
- **Personalized Cover Emails**: Generates tailored outreach and cover emails specific to the job description and candidate strengths.
- **On-Demand Lifecycle & RAM Conservation**: Automatically starts the local Ollama background server when needed, and immediately unloads models (`keep_alive: 0`) and releases GPU/system RAM once execution concludes.
- **Multi-Model Fallbacks**: Pre-configured for `qwen2.5:7b-instruct` with seamless fallback to lightweight models (`llama3.2:3b`, `qwen2.5:3b`) or cloud endpoints.

### Setting Up Ollama
1. Download and install Ollama from [ollama.com](https://ollama.com/).
2. Pull the recommended default model:
   ```bash
   ollama pull qwen2.5:7b-instruct
   ```
3. Set your preferences in `.env`:
   ```env
   AI_API_STYLE=ollama
   LOCAL_AI_BASE_URL=http://127.0.0.1:11434
   LOCAL_AI_MODEL=qwen2.5:7b-instruct
   LOCAL_AI_FALLBACK_MODELS=llama3.2:3b,qwen3:1.7b
   ```
*(Note: Cloud LLMs like OpenAI, Gemini, or Groq are also supported by setting `AI_API_STYLE=openai` and providing your API key).*

---

## 🔒 Security & Privacy Guarantees

- **Zero Hardcoded Secrets**: All credentials, tokens, and personal identifiers are loaded dynamically at runtime via `python-dotenv` and `os.getenv`.
- **Strict `.gitignore`**: Blocks `.env`, virtual environments (`venv/`, `.venv/`), compiled Java bytecode (`*.class`, `*.jar`), live SQLite databases (`*.db`), and generated logs.
- **Log Isolation**: All scraped data, audit lines, and CSV exports are strictly isolated into the `/logs` directory and excluded from version control.

---

## ☕ Java Component Subprocess Integration

The project includes an optional high-performance Java component (`src/JavaBridge.java`) for cryptographic hash deduplication and high-speed token matching:
- **Auto-Compilation**: `src/java_runner.py` detects if `JavaBridge.class` exists; if missing, it compiles `JavaBridge.java` using `javac` automatically.
- **Subprocess Bridge**: Executes via standard `subprocess.run` with JSON input/output.
- **Graceful Fallback**: If Java is not installed, the framework seamlessly falls back to pure Python calculations without throwing fatal exceptions.

---

## 🖥 Portable Selenium WebDriver

`src/browser.py` provides cross-platform browser automation:
- Uses `webdriver-manager` to automatically download and link Chrome/Firefox drivers without manual driver installations.
- Supports both visible and modern headless (`--headless=new`) modes.
- Injects anti-bot stealth overrides (masking `navigator.webdriver` via CDP scripts).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
