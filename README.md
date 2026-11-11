# 🤖 Job Agent Framework

> **An autonomous, plug-and-play, open-source job application, outreach, and scraping automation framework.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Local AI](https://img.shields.io/badge/Local%20AI-Ollama-blueviolet.svg)](https://ollama.com/)
[![Selenium WebDriver](https://img.shields.io/badge/Browser%20Automation-Selenium-green.svg)](https://www.selenium.dev/)
[![Java Bridge](https://img.shields.io/badge/Java-Subprocess%20Bridge-orange.svg)](https://openjdk.org/)
[![Mission Control](https://img.shields.io/badge/Web%20Dashboard-Mission%20Control-purple.svg)](http://127.0.0.1:8765)
[![SQLite Self--Healing](https://img.shields.io/badge/Database-SQLite%20Self--Healing-lightblue.svg)](https://www.sqlite.org/)

---

## 📌 Overview

**Job Agent** is a production-grade, open-source automation suite engineered to transform job searching from manual repetitive labor into an intelligent, high-velocity autonomous pipeline.

Currently **pre-configured and battle-tested for LinkedIn and Naukri.com**, the framework navigates job listings, scores opportunities, automatically completes complex Applicant Tracking System (ATS) forms, scans recruiter hiring posts for direct cold-email outreach, dynamically compiles tailored resumes, intercepts 2FA/OTPs, and monitors your inbox for inbound interview invitations — all orchestrated locally on your machine with **zero API costs** and **strict privacy**.

Support for additional platforms like **Instahyre**, **Foundit**, **Shine**, and **Indeed** is currently on the active roadmap and welcoming community contributions.

---

## 🌐 Supported Job Portals & Roadmap

> [!NOTE]
> **Active Focus**: Job Agent is currently battle-tested and production-ready for **LinkedIn** and **Naukri.com**. Additional platforms are in active development or planned for upcoming releases.

| Platform / Portal | Status | Capabilities Supported |
| :--- | :---: | :--- |
| **LinkedIn** | 🟢 **Active** | Job Search, Easy Apply, Recruiter Post Scanner, Automated Cold Email Outreach |
| **Naukri.com** | 🟢 **Active** | Keyword Search, One-Click Apply, Company Portal Redirects, 2FA/OTP Interception |
| **Direct ATS Portals** | 🟢 **Active** | Greenhouse, Lever, Workday, SmartRecruiters, BambooHR, Ashby, Taleo |
| **Instahyre** | 🟡 *In Staging* | Search and opportunity collector; full application adapter in progress |
| **Foundit (Monster)** | 🟡 *In Staging* | Basic listing crawler built; end-to-end apply pipeline in development |
| **Shine.com** | ⚪ *Planned* | Scraper and application module on upcoming roadmap |
| **Indeed** | ⚪ *Planned* | Job feed parser and application handler planned |
| **Wellfound (AngelList)** | 🟡 *In Staging* | Startup job collector in development |

*Community contributions for new scrapers and portal adapters are warmly welcomed! See [CONTRIBUTING.md](CONTRIBUTING.md) to build an adapter for your favorite job site.*

---

## ⚡ Core Feature Matrix

| Capability | Module | Description |
| :--- | :--- | :--- |
| **Multi-Platform Scraper** | `app/scrapers/` | Pre-configured for **LinkedIn** & **Naukri**; staging adapters for **Instahyre**, **Foundit**, **Shine**, and **Company ATS** portals. |
| **Direct ATS Form Filler** | `app/form_filler.py` | Automatically fills multi-step application forms (**Greenhouse, Lever, Workday, SmartRecruiters, BambooHR, Ashby, Taleo**). |
| **LinkedIn Recruiter Outreach** | `linkedin_post_applier.py` | Scans LinkedIn feed posts where recruiters ask for resumes, generates bespoke cover emails via AI, and emails them with your resume. |
| **Local AI Answering (Ollama)** | `app/ollama_client.py` | Dynamically answers open-ended screening questions (*"Why are you a fit?"*, *"Years of experience with X"*) with **zero API costs**. |
| **Dynamic Resume Compiler** | `app/resume_compiler.py` | Compiles ATS-compliant, tailored PDF resumes per application using **Typst** and **HTML/CSS** templates based on job requirements. |
| **2FA & OTP Interception** | `app/otp_reader.py` | Solves portal verification gates automatically by reading OTPs via **IMAP email** and **Android SMS gateway**. |
| **Inbound Recruiter Triage** | `app/inbound_sync.py` | Continuously monitors IMAP inboxes for recruiter responses, interview requests, and tests, synchronizing state to SQLite. |
| **Mission Control Web UI** | `app/web_radar.py` | Built-in dark-mode web dashboard (`http://127.0.0.1:8765`) displaying real-time metrics, conversion funnels, and application history. |
| **High-Speed Java Bridge** | `src/JavaBridge.java` | Sub-millisecond cryptographic hash deduplication and token scoring executed seamlessly via Python subprocess. |
| **Stealth WebDriver** | `src/browser.py` | Anti-bot detection avoidance via CDP runtime scripts (masking `navigator.webdriver`), custom user-agents, and persistent profiles. |
| **RAM Conservation Daemon** | `app/shutdown.py` | Auto-launches Ollama on-demand and unloads models (`keep_alive: 0`) when idle to free 100% of GPU and system RAM. |

---

## 🏗 Directory Structure

```text
Job-agent/
├── config/                  # Configuration loaders and YAML schemas
│   ├── settings.py          # Dynamic environment configuration loader
│   └── settings.example.yaml# Example configuration template
├── database/                # Database initialization scripts and schemas
│   ├── init_db.py           # Self-healing SQLite initializer & health verification
│   └── schema.sql           # SQLite table schemas & performance indices
├── logs/                    # Isolated scraped job logs & audit trails (.gitkeep)
├── src/                     # Core modular Python and Java source code
│   ├── main.py              # Unified CLI entry point (init, run, dashboard, etc.)
│   ├── agent.py             # High-level scraping and scoring orchestrator
│   ├── browser.py           # Cross-platform portable Selenium WebDriver
│   ├── java_runner.py       # Seamless Python-to-Java subprocess bridge
│   ├── JavaBridge.java      # Fast Java deduplication & scoring component
│   └── tracker.py           # SQLite job status and log isolation tracker
├── app/                     # Full automation pipeline engine
│   ├── form_filler.py       # Multi-step ATS form auto-fill engine
│   ├── job_collector.py     # Multi-board job collector & link extractor
│   ├── linkedin_post_scanner.py # LinkedIn content/post hiring scanner
│   ├── cover_email_composer.py  # AI-powered personalized cover email generator
│   ├── email_sender.py      # SMTP dispatcher with quota tracking & attachments
│   ├── email_followup.py    # Inbound email monitor for interview invitations
│   ├── inbound_sync.py      # Recruiter inbox triage manager
│   ├── resume_compiler.py   # Typst / HTML dynamic tailored resume compiler
│   ├── resume_tailorer.py   # AI bullet-point tailoring engine
│   ├── web_radar.py         # Mission Control zero-dependency web server
│   ├── scrapers/            # Individual scrapers (LinkedIn, Naukri, Foundit, ATS)
│   └── forms/               # Selector caches and DOM widget adapters
├── profile/                 # Profile templates (git-ignored for privacy)
│   ├── profile.example.json # Template for candidate information & answers
│   └── email_accounts.example.json
├── jobs/                    # Target URL seeds (git-ignored for live runs)
│   └── urls.example.txt     # Example seed URLs for LinkedIn and Naukri
├── templates/               # Resume and email generation templates
│   ├── resume_master.typ    # Typst resume typesetting template
│   ├── resume_template.html # Clean HTML/CSS ATS resume template
│   └── answer_templates.json# Standard baseline question answer cache
├── .env.example             # Template for all environment variables
├── .gitignore               # Strict exclusion rules (secrets, db, logs, bytecode)
├── requirements.txt         # Complete Python dependencies
└── README.md                # Framework documentation & user guide
```

---

## 🚀 Quick Start Guide

Follow these steps to set up and run Job Agent on your machine.

### 1. Clone the Repository
```bash
git clone https://github.com/sushantvishu/Job-Agent.git
cd Job-Agent
```

### 2. Set Up a Virtual Environment
**On Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Your Profile & Environment
Copy the configuration templates:
```bash
# On Linux/macOS:
cp .env.example .env
cp profile/profile.example.json profile/profile.json

# On Windows:
copy .env.example .env
copy profile\profile.example.json profile\profile.json
```

Open `.env` in your editor and configure:
- **Candidate Details**: `CANDIDATE_NAME`, `CANDIDATE_EMAIL`, `CANDIDATE_PHONE`, `TARGET_ROLE`
- **Browser Settings**: `BROWSER_TYPE=chrome`, `HEADLESS=false` (to watch the browser) or `true` (background)
- **Local AI (Ollama)**: `AI_API_STYLE=ollama`, `LOCAL_AI_MODEL=qwen2.5:7b-instruct`
- **Email Outreach & Monitoring (Gmail / Google Workspace)**:
  > [!IMPORTANT]
  > **Gmail / Google Workspace App Password Required**:  
  > Google does NOT allow standard master login passwords for SMTP/IMAP automation.  
  > 1. Enable **2-Step Verification** in your [Google Security Settings](https://myaccount.google.com/security).  
  > 2. Go to **[Google App Passwords](https://myaccount.google.com/apppasswords)**.  
  > 3. Generate a new 16-character App Password (name it e.g. `Job Agent`).  
  > 4. Set `EMAIL_USER=your_workspace_email@yourdomain.com` and `EMAIL_PASSWORD=your_16_char_app_password` in `.env`.

### 5. Initialize the Self-Healing System
Run the system initialization check:
```bash
python src/main.py init
```
This automatically:
- Creates `database/jobs.db` with WAL mode and indices if missing.
- Tests for Java runtime and compiles `JavaBridge.java` via `javac` on demand.
- Audits logging paths and candidate configuration.

---

## 💻 CLI Command Reference

The framework includes a comprehensive CLI accessible via `python src/main.py`:

| Command | Usage | Description |
| :--- | :--- | :--- |
| **`init`** | `python src/main.py init` | Runs self-healing database setup and audits dependencies. |
| **`run`** | `python src/main.py run --input jobs/urls.txt` | Executes scraping, scoring, and deduplication over target URLs. |
| **`dashboard`** | `python src/main.py dashboard [--port 8765]` | Launches the Mission Control web UI at `http://127.0.0.1:8765`. |
| **`apply-posts`** | `python src/main.py apply-posts [--live] [--pages 5]` | Scans LinkedIn recruiter hiring posts, generates AI cover emails, and emails them. |
| **`sync-inbox`** | `python src/main.py sync-inbox [--max-messages 20]` | Triage IMAP email inbox for recruiter interview invites and updates. |
| **`compile-resume`** | `python src/main.py compile-resume --role "Role" --company "Co"` | Dynamically compiles a bespoke ATS-tailored PDF resume. |
| **`stats`** | `python src/main.py stats` | Displays terminal table of tracked applications by status. |
| **`export`** | `python src/main.py export [--output jobs.csv]` | Exports tracked applications from SQLite into a clean CSV file. |
| **`stop-ai`** | `python src/main.py stop-ai` | Unloads Ollama models and terminates background AI processes to free 100% RAM. |
| **`open-browser`** | `python src/main.py open-browser` | Opens an interactive browser session for manual login or verification. |

---

## 🧠 Local AI & LLM Integration (Ollama)

Job Agent leverages **[Ollama](https://ollama.com/)** for complete offline, privacy-guaranteed intelligence without ongoing API fees:

1. **Install Ollama**: Download from [ollama.com](https://ollama.com/).
2. **Pull the Default Model**:
   ```bash
   ollama pull qwen2.5:7b-instruct
   ```
3. **Automated Memory Management**: The agent boots Ollama on demand and sends an unload signal (`keep_alive: 0`) when idle, completely freeing GPU and system memory.
4. **Cloud LLM Support**: You can effortlessly switch from Ollama to OpenAI, Gemini, or Groq by setting `AI_API_STYLE=openai` and providing your API key in `.env`.

---

## ✉️ Automated LinkedIn Recruiter Outreach

Hiring managers frequently post on LinkedIn: *"We're urgently hiring a Security Analyst / Software Engineer. Email your CV to recruiter@company.com"*.

The **`apply-posts`** pipeline:
1. Searches recent LinkedIn feed content matching your role keywords.
2. Extracts recruiter email addresses, company names, and specific hiring criteria.
3. Uses local AI to generate a hyper-targeted, professional cover email referencing the recruiter's exact post.
4. Attaches your tailored PDF resume.
5. In dry-run mode (default), generates previews for your inspection. With `--live`, delivers the email via SMTP with rate-limiting and daily quota protection.

> [!TIP]
> **Gmail & Google Workspace SMTP Setup**:  
> If using Gmail or a custom Google Workspace domain, ensure **2-Step Verification** is enabled on your account, then generate a dedicated 16-character **[App Password](https://myaccount.google.com/apppasswords)**. Standard Google account login passwords will be rejected by Google's SMTP/IMAP servers.

---

## 📊 Mission Control Web Dashboard

Launch the zero-dependency web interface:
```bash
python src/main.py dashboard
```
Navigate to **`http://127.0.0.1:8765`** to view:
- **Live Metrics**: Total tracked jobs, applications submitted, interview requests, and conversion rates.
- **Platform Breakdown**: Success rates across LinkedIn, Naukri, Foundit, and direct ATS portals.
- **Application History**: Filterable table of all opportunities with status badges and timestamps.
- **Alert Log**: Latest recruiter invitations and assessment alerts.

---

## 🔒 Security & Privacy Guarantees

- **Zero Hardcoded Personal Data**: All names, contacts, credentials, and paths are resolved via dynamic environment variables (`.env`) and template files.
- **Bulletproof `.gitignore`**: Blocks `.env`, virtual environments, SQLite databases (`*.db`), compiled Java bytecode (`*.class`), browser session profiles, and private candidate documents.
- **Log Isolation**: All operational logs and screenshots are saved locally in the git-ignored `/logs` directory.

---

## ☕ Java Component Subprocess Integration

`src/JavaBridge.java` provides lightning-fast cryptographic deduplication and token matching:
- **Auto-Compilation**: `src/java_runner.py` detects if `JavaBridge.class` exists; if missing, it compiles `JavaBridge.java` using `javac` automatically.
- **Subprocess Bridge**: Communicates over standard I/O with JSON serialization.
- **Zero-Failure Fallback**: If Java is not installed, the framework automatically falls back to native Python routines with zero downtime.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
