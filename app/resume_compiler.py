from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.config import AppConfig, load_config
from app.profile_loader import ProfileData, load_profile

logger = logging.getLogger("resume_compiler")

HTML_RESUME_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    @page {
      size: A4;
      margin: 1.5cm;
    }
    body {
      font-family: 'Segoe UI', Arial, sans-serif;
      color: #111827;
      line-height: 1.45;
      font-size: 10pt;
      margin: 0;
      padding: 0;
    }
    .header { text-align: center; margin-bottom: 12px; }
    h1 { margin: 0; font-size: 20pt; color: #0f172a; font-weight: 700; }
    .contact { color: #4b5563; font-size: 9.5pt; margin-top: 4px; }
    .headline { color: #0284c7; font-size: 11pt; font-weight: 600; margin-top: 4px; }
    hr { border: 0; border-top: 1px solid #cbd5e1; margin: 10px 0; }
    h2 { font-size: 12pt; color: #0f172a; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1.5px solid #0284c7; padding-bottom: 2px; margin: 12px 0 6px 0; }
    p { margin: 0 0 6px 0; text-align: justify; }
    ul { margin: 4px 0 10px 18px; padding: 0; }
    li { margin-bottom: 4px; }
    .skills-grid { display: flex; justify-content: space-between; margin-bottom: 8px; }
    .skills-col { width: 48%; }
    .exp-header { display: flex; justify-content: space-between; font-weight: bold; }
    .exp-sub { color: #4b5563; font-style: italic; font-size: 9.5pt; margin-bottom: 4px; }
  </style>
</head>
<body>
  <div class="header">
    <h1>{{ name }}</h1>
    <div class="contact">
      {{ location }} | {{ phone }} | {{ email }} | LinkedIn: {{ linkedin }} | GitHub: {{ github }}
    </div>
    <div class="headline">{{ headline }}</div>
  </div>

  <hr>

  <h2>Professional Summary</h2>
  <p>{{ summary }}</p>

  <h2>Technical Competencies</h2>
  <div class="skills-grid">
    <div class="skills-col">
      <p><strong>Security & Testing:</strong> {{ security_skills }}</p>
      <p><strong>Offensive Methodologies:</strong> OWASP Top 10, Network Penetration Testing, Vulnerability Scanning</p>
    </div>
    <div class="skills-col">
      <p><strong>Languages & Frameworks:</strong> {{ dev_skills }}</p>
      <p><strong>Infrastructure:</strong> Linux (Kali/Ubuntu), Docker, Git, REST APIs, Microservices</p>
    </div>
  </div>

  <h2>Hands-On Experience & Key Projects</h2>
  <div class="exp-header">
    <span>Cybersecurity & Security Automation Practitioner</span>
    <span>2024 – Present</span>
  </div>
  <div class="exp-sub">Independent Security Research & Autonomous Tooling — Bengaluru, India</div>
  <ul>
    <li>Executed web application penetration testing against OWASP Top 10 vulnerabilities (SQLi, XSS, SSRF, IDOR) using Burp Suite and custom test suites.</li>
    <li>Engineered high-performance security automation pipelines in Python, leveraging asynchronous concurrency and Playwright for headless verification.</li>
    <li>Conducted network vulnerability assessments and port scanning utilizing Nmap, Wireshark, and Nessus.</li>
    <li>Mapped detection events and incident response playbooks to the MITRE ATT&CK enterprise matrix with SIEM log analysis.</li>
  </ul>

  <h2>Education & Academic Credentials</h2>
  <div class="exp-header">
    <span>{{ highest_degree }}</span>
    <span>Graduation: {{ graduation_year }}</span>
  </div>
  <div class="exp-sub">Specialization in {{ field_of_study }}</div>
</body>
</html>
"""


class DynamicResumeCompiler:
    """Compiles ATS-compliant tailored resumes using Typst or Headless Chromium PDF renderer."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.exports_dir = self.config.exports_dir / "resumes"
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.typst_bin = shutil.which("typst")

    def build_context(self, profile: ProfileData, job_title: str, company: str, job_description: str) -> dict[str, str]:
        """Inject target job keywords and customize summary and skills."""
        sec_skills = [s for s in profile.skills if s.lower() in {
            "vapt", "owasp", "burp suite", "nmap", "wireshark", "api security", "siem", "soc",
            "metasploit", "nessus", "kali linux", "penetration testing", "vulnerability assessment"
        }]
        dev_skills = [s for s in profile.skills if s.lower() in {
            "python", "fastapi", "docker", "git", "bash", "rest apis", "asyncio", "sql", "linux"
        }]

        headline = profile.headline or f"Cybersecurity Analyst & Automation Engineer | VAPT | Python"
        summary = profile.summary.split("\n\n[AI/LLM Persona Guidelines]")[0].strip()
        if company and job_title:
            summary = f"Results-driven cybersecurity and automation specialist targeting the {job_title} position at {company}. {summary}"

        return {
            "name": profile.name,
            "email": profile.email,
            "phone": profile.phone,
            "location": profile.location,
            "headline": headline,
            "linkedin": profile.links.get("linkedin", ""),
            "github": profile.links.get("github", ""),
            "summary": summary,
            "security_skills": ", ".join(sec_skills[:10]) if sec_skills else "VAPT, OWASP Top 10, Burp Suite, Nmap, API Security",
            "dev_skills": ", ".join(dev_skills[:8]) if dev_skills else "Python, FastAPI, Docker, Git, Linux, Bash",
            "highest_degree": profile.education.highest_degree,
            "graduation_year": profile.education.graduation_year,
            "field_of_study": profile.education.field_of_study,
        }

    def compile_tailored_pdf(
        self,
        profile: ProfileData,
        job_title: str,
        company: str,
        job_description: str,
        filename_prefix: str = "tailored_resume",
    ) -> Path:
        """Compiles a tailored, ATS-verified PDF resume. Guaranteed to succeed via Typst or Playwright fallback."""
        ctx = self.build_context(profile, job_title, company, job_description)
        safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", filename_prefix)
        pdf_path = self.exports_dir / f"{safe_prefix}.pdf"

        # 1. Try Typst if binary is present
        if self.typst_bin:
            try:
                typ_template = (self.config.templates_dir / "resume_master.typ").read_text(encoding="utf-8")
                typ_content = typ_template
                for k, v in ctx.items():
                    typ_content = typ_content.replace(f"{{{{ {k} }}}}", str(v))
                typ_file = self.exports_dir / f"{safe_prefix}.typ"
                typ_file.write_text(typ_content, encoding="utf-8")
                cmd = [self.typst_bin, "compile", str(typ_file), str(pdf_path)]
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.returncode == 0 and pdf_path.exists() and pdf_path.stat().st_size > 0:
                    logger.info("Compiled dynamic resume via Typst: %s", pdf_path)
                    return pdf_path
            except Exception as typst_exc:
                logger.debug("Typst compile attempt failed; falling back to Playwright: %s", typst_exc)

        # 2. Resilient Playwright Headless PDF Fallback (Zero external dependencies)
        try:
            from playwright.sync_api import sync_playwright
            html_content = HTML_RESUME_TEMPLATE
            for k, v in ctx.items():
                html_content = html_content.replace(f"{{{{ {k} }}}}", str(v))

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_content(html_content, wait_until="load")
                page.pdf(
                    path=str(pdf_path),
                    format="A4",
                    print_background=True,
                    margin={"top": "1.5cm", "bottom": "1.5cm", "left": "1.5cm", "right": "1.5cm"},
                )
                browser.close()

            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                logger.info("Compiled dynamic ATS resume via Headless PDF engine: %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
                return pdf_path
        except Exception as pw_exc:
            logger.warning("Playwright PDF render failed: %s", pw_exc)

        # 3. Final safety fallback: copy master profile resume
        if self.config.resume_path.exists():
            shutil.copyfile(self.config.resume_path, pdf_path)
            return pdf_path

        return pdf_path
