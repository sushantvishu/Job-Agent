from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from app.utils import JobPosting, ProfileData, compact_whitespace, normalize_key


class ResumeTailorer:
    """Dynamically tailors and compiles an ATS-optimized single-column PDF resume
    matching the exact requirements of a target job posting.
    """

    def __init__(self, project_root: Path, logger: logging.Logger | None = None) -> None:
        self.project_root = Path(project_root)
        self.logger = logger or logging.getLogger("job_agent.resume_tailorer")
        self.template_path = self.project_root / "templates" / "resume_template.html"
        self.output_dir = self.project_root / "exports" / "resumes"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def determine_archetype(self, job: JobPosting) -> str:
        """Classify the job into one of 5 technical archetypes."""
        text = f"{job.title} {job.description}".lower()
        
        # Python / Software Engineering
        if any(kw in text for kw in ("python", "backend", "software engineer", "developer", "fastapi", "django", "flask", "algorithmic", "automation engineer")):
            return "python_developer"
        
        # VAPT / Pentesting
        if any(kw in text for kw in ("vapt", "penetration", "pentest", "ethical hack", "burp", "vulnerability assessment")):
            return "vapt_analyst"
            
        # AppSec / API Security
        if any(kw in text for kw in ("appsec", "application security", "api security", "devsecops", "sast", "dast", "secure code")):
            return "appsec_engineer"
            
        # SOC / Incident Response
        if any(kw in text for kw in ("soc", "siem", "splunk", "incident response", "incident monitoring", "alert triage", "sentinel")):
            return "soc_analyst"
            
        # Network & Cloud Security
        if any(kw in text for kw in ("network security", "ccna", "firewall", "cloud security", "azure security", "routing", "switching")):
            return "network_security"
            
        # Default based on profile primary focus
        return "vapt_analyst"

    def generate_tailored_pdf(self, job: JobPosting, profile: ProfileData, page: Any) -> str:
        """Generate an ATS-optimized tailored PDF for the job using Playwright page."""
        archetype = self.determine_archetype(job)
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", profile.name.strip()) or "Candidate"
        output_pdf = self.output_dir / f"{safe_name}_{archetype}.pdf"

        html_content = self.render_html(archetype, profile, job)

        try:
            # Open an isolated tab to render PDF so we never overwrite the active job form
            pdf_page = page.context.new_page() if hasattr(page, "context") and page.context else page
            try:
                pdf_page.set_content(html_content, wait_until="load")
                pdf_page.pdf(
                    path=str(output_pdf),
                    format="A4",
                    print_background=True,
                    margin={"top": "12mm", "bottom": "12mm", "left": "14mm", "right": "14mm"},
                )
            finally:
                if pdf_page is not page and not pdf_page.is_closed():
                    pdf_page.close()
            self.logger.info("Successfully generated tailored resume for %s | archetype=%s | path=%s", job.url, archetype, output_pdf)
            return str(output_pdf)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to compile tailored PDF via Playwright: %s — falling back to base resume", exc)
            fallback = self.project_root / "profile" / "resume.pdf"
            for candidate in ("resume.pdf", "Resume.pdf", "CV.pdf", "cv.pdf"):
                c_path = self.project_root / "profile" / candidate
                if c_path.exists():
                    fallback = c_path
                    break
            else:
                # Discover any PDF in profile directory
                profile_dir = self.project_root / "profile"
                if profile_dir.is_dir():
                    pdfs = list(profile_dir.glob("*.pdf"))
                    if pdfs:
                        fallback = pdfs[0]
            return str(fallback)

    def render_html(self, archetype: str, profile: ProfileData, job: JobPosting) -> str:
        """Fill the resume template with tailored sections for the archetype."""
        data = self._build_archetype_data(archetype, profile, job)
        template_text = self.template_path.read_text(encoding="utf-8")

        try:
            import jinja2
            env = jinja2.Environment(autoescape=True)
            template = env.from_string(template_text)
            return template.render(**data)
        except Exception as exc:
            self.logger.debug("Jinja2 render fallback to string replacement: %s", exc)

        # Simple robust template substitution fallback
        # Replace basic scalar fields
        for key in ("name", "headline", "email", "phone", "location", "github", "portfolio", "summary"):
            template_text = template_text.replace(f"{{{{ {key} }}}}", data.get(key, ""))
            
        # Replace skill_groups block
        skills_html = []
        for g in data["skill_groups"]:
            skills_html.append(
                f'<div class="skill-line"><span class="skill-label">{g["category"]}:</span> <span class="skill-val">{g["skills"]}</span></div>'
            )
        template_text = re.sub(
            r"\{%\s*for group in skill_groups\s*%\}.*?\{%\s*endfor\s*%\}",
            "\n".join(skills_html),
            template_text,
            flags=re.DOTALL,
        )

        # Replace projects block
        proj_html = []
        for p in data["projects"]:
            bullets_html = "".join(f"<li>{b}</li>" for b in p["bullets"])
            tech_span = f'<span class="entry-sub"> | <em>{p["tech"]}</em></span>' if p.get("tech") else ""
            link_span = f'<span class="entry-date">{p["link"]}</span>' if p.get("link") else ""
            proj_html.append(f"""
            <div class="entry">
              <div class="entry-header">
                <div><span class="entry-title">{p["title"]}</span>{tech_span}</div>
                {link_span}
              </div>
              <ul class="entry-bullets">{bullets_html}</ul>
            </div>
            """)
        template_text = re.sub(
            r"\{%\s*for proj in projects\s*%\}.*?\{%\s*endfor\s*%\}",
            "\n".join(proj_html),
            template_text,
            flags=re.DOTALL,
        )

        # Replace experiences block
        exp_html = []
        for e in data["experiences"]:
            bullets_html = "".join(f"<li>{b}</li>" for b in e["bullets"])
            exp_html.append(f"""
            <div class="entry">
              <div class="entry-header">
                <div><span class="entry-title">{e["role"]}</span> — <span class="entry-company">{e["company"]}</span></div>
                <span class="entry-date">{e["period"]}</span>
              </div>
              <ul class="entry-bullets">{bullets_html}</ul>
            </div>
            """)
        template_text = re.sub(
            r"\{%\s*for exp in experiences\s*%\}.*?\{%\s*endfor\s*%\}",
            "\n".join(exp_html),
            template_text,
            flags=re.DOTALL,
        )

        # Replace certifications block
        cert_html = []
        for c in data["certifications"]:
            cert_html.append(f'<div class="cert-item">• <strong>{c["name"]}</strong> ({c["issuer"]})</div>')
        template_text = re.sub(
            r"\{%\s*for cert in certifications\s*%\}.*?\{%\s*endfor\s*%\}",
            "\n".join(cert_html),
            template_text,
            flags=re.DOTALL,
        )

        # Replace education block
        edu_html = []
        for edu in data["education"]:
            edu_html.append(f"""
            <div class="entry">
              <div class="entry-header">
                <div><span class="entry-title">{edu["degree"]}</span> — <span class="entry-company">{edu["institution"]}</span></div>
                <span class="entry-date">{edu["grade"]}</span>
              </div>
            </div>
            """)
        template_text = re.sub(
            r"\{%\s*for edu in education\s*%\}.*?\{%\s*endfor\s*%\}",
            "\n".join(edu_html),
            template_text,
            flags=re.DOTALL,
        )

        # Cleanup any leftover Jinja tags if portfolio wasn't passed
        template_text = re.sub(r"\{% if portfolio %}.*?\{% endif %}", "", template_text)

        return template_text

    def _build_archetype_data(self, archetype: str, profile: ProfileData, job: JobPosting) -> dict[str, Any]:
        """Construct verified, tailored data for the given archetype."""
        github_url = profile.links.get("github", "")
        clean_github = re.sub(r"^https?://", "", github_url).rstrip("/") or "github.com"
        portfolio_url = profile.links.get("portfolio", "")

        base = {
            "name": profile.name or "Candidate",
            "email": profile.email,
            "phone": profile.phone,
            "location": profile.location + (" (Open to Relocation)" if profile.custom_answers.get("relocation") else ""),
            "github": clean_github,
            "portfolio": portfolio_url,
        }

        # Master Experience Data
        exp_analyst = {
            "company": "Tech Solutions Inc.",
            "role": "Product / Security Operations Analyst",
            "period": "Dec 2023 – Sep 2024",
            "bullets": [
                "Monitored SIEM dashboards for critical and high-severity security events, analyzing source IP, destination, timestamp, and alert vectors.",
                "Managed incident lifecycles, documenting alerts in ServiceNow and JIRA ticketing systems, ensuring timely team circulation and escalation.",
                "Generated structured shift handover reports and security status summaries for cross-functional technical teams.",
            ],
        }

        exp_consultant = {
            "company": "Enterprise Tech Services",
            "role": "Sr. Technical Consultant",
            "period": "May 2018 – Sep 2023",
            "bullets": [
                "Conducted deep diagnostics to investigate and resolve enterprise technical and network connectivity issues.",
                "Applied operational procedural controls and tested operating systems for potential security vulnerabilities.",
                "Collaborated with backend engineering teams on procedural network controls, IP connectivity, and security policy enforcement.",
            ],
        }

        # Master Projects Data
        proj_antares = {
            "title": "Antares Algorithmic Trading System",
            "tech": "Python, Redis, WebSockets, AWS EC2, Systemd",
            "link": clean_github,
            "bullets": [
                "Engineered a high-throughput Python market data pipeline streaming live options-chain ticks via broker WebSocket API with per-second VWAP snapshots and cumulative drift <0.37ms/snapshot.",
                "Built an end-to-end Order Management System (OMS) with Redis-backed state, lifecycle tracking, multi-leg coordination, and automated risk checks (84/84 live test orders executed without FatFinger rejects).",
                "Reverse-engineered undocumented exchange protocol quirks (epoch offsets, error semantics), built cross-validation replay across multi-day datasets, and ported the engine to Binance EAPI feeds.",
            ],
        }

        proj_jobagent = {
            "title": "Job Agent — Autonomous ATS Penetration Daemon",
            "tech": "Python, Playwright, Local AI (Ollama), SQLite, Async",
            "link": clean_github,
            "bullets": [
                "Architected an autonomous Python agent executing automated form parsing, safe submission, and ATS penetration across 800+ enterprise portals.",
                "Integrated local LLM inference (Llama 3.2 / Qwen) for real-time schema extraction, question-answering, and dynamic DOM interaction.",
                "Built an IMAP 2FA interceptor to autonomously capture and inject OTPs, paired with self-healing state management and memory context recycling.",
            ],
        }

        proj_burp_ai = {
            "title": "Burp AI Bridge",
            "tech": "Python, FastAPI, Burp Suite Pro (Montoya API), MCP Protocol, Ollama",
            "link": clean_github,
            "bullets": [
                "Developed a two-part security advisory framework integrating a Burp Suite Pro Montoya extension with an asynchronous FastAPI backend via MCP protocol.",
                "Streamed selected HTTP traffic to local LLM models to autonomously suggest vulnerabilities, payload vectors, and prioritize testing targets for manual pen tests.",
            ],
        }

        proj_bugbounty = {
            "title": "Responsible Security Disclosures & Vulnerability Findings",
            "tech": "Burp Suite Pro, OWASP Top 10, Nmap, Kali Linux, NCIIPC, Bugcrowd",
            "link": "Responsible Disclosure",
            "bullets": [
                "Performed Host Header Injection on production target, identifying critical broken authentication and session invalidation vulnerabilities.",
                "Discovered and responsibly disclosed an exposed XML-RPC interface and credential enumeration vector on target web service.",
                "Demonstrated wireless network security testing against WPA/WPA2-PSK and WPA3-SAE protocols.",
            ],
        }

        # Master Education & Certs
        education = [
            {
                "degree": "Bachelor of Computer Applications (BCA) - Cyber Security Specialization",
                "institution": "State University of Technology",
                "grade": "First Class | 2020 – 2024",
            },
            {
                "degree": "Senior Secondary (Class 12) with Computer Science",
                "institution": "Higher Secondary Board",
                "grade": "78%",
            },
            {
                "degree": "Secondary (Class 10) with Computer Applications",
                "institution": "Secondary School Board",
                "grade": "85%",
            },
        ]

        certs_all = [
            {"name": "Cisco Certified Network Associate (CCNA 200-301 Routing & Switching)", "issuer": "Cisco"},
            {"name": "Ethical Hacking Essentials (EHE)", "issuer": "EC-Council"},
            {"name": "Microsoft Azure Fundamentals (AZ-900)", "issuer": "Microsoft"},
            {"name": "Microsoft Azure Data Fundamentals (DP-900)", "issuer": "Microsoft"},
            {"name": "(ISC)² Candidate", "issuer": "(ISC)²"},
            {"name": "Learn Burp Suite for Advanced Web Penetration Testing", "issuer": "Security Cert"},
        ]

        # ── ARCHETYPE SPECIALIZATIONS ───────────────────────────────────────
        if archetype == "python_developer":
            base["headline"] = "Python Software Engineer | Backend & Algorithmic Systems Specialist"
            base["summary"] = (
                "Software Engineer with strong hands-on experience in high-throughput Python backend systems, WebSocket streaming pipelines, "
                "asynchronous architectures, and automation. Proven track record building production-grade algorithmic trading engines with Redis state "
                "management and autonomous reverse-engineering daemons. Passionate about low-latency system design, API engineering, and clean code."
            )
            base["skill_groups"] = [
                {"category": "Programming Languages", "skills": "Python (Advanced, asyncio), SQL, Bash, Java, C++, HTML5, CSS3, JavaScript"},
                {"category": "Frameworks & Backends", "skills": "FastAPI, WebSockets, Redis, REST APIs, JSON, SQLite, Systemd"},
                {"category": "Infrastructure & Cloud", "skills": "AWS (EC2), Linux (Kali, Ubuntu), Git, GitHub, TCP/IP, Docker Basics"},
                {"category": "Core Competencies", "skills": "Algorithmic Trading OMS, Real-time Data Streaming, Automation Daemons, Reverse Engineering"},
            ]
            base["projects"] = [proj_antares, proj_jobagent, proj_burp_ai]
            base["experiences"] = [exp_analyst, exp_consultant]
            base["certifications"] = certs_all

        elif archetype == "vapt_analyst":
            base["headline"] = "VAPT Analyst | Web Application & Network Penetration Tester"
            base["summary"] = (
                "Cybersecurity Specialist with hands-on expertise in Vulnerability Assessment and Penetration Testing (VAPT), OWASP Top 10 vulnerabilities, "
                "and bug bounty disclosures. Proven ability to conduct manual testing on web applications and APIs using Burp Suite Pro, coupled with custom "
                "Python and Bash security automation scripts. Holds industry credentials including CCNA and EC-Council EHE."
            )
            base["skill_groups"] = [
                {"category": "Offensive Security", "skills": "VAPT, OWASP Top 10, Burp Suite Pro, Nmap, SQLmap, Sublist3r, Subfinder, airmon-ng"},
                {"category": "Security Methodologies", "skills": "Web & API Penetration Testing, Broken Authentication, Host Header Injection, Wireless (WPA3-SAE)"},
                {"category": "Scripting & Automation", "skills": "Python, Bash Scripting, Kali Linux, PowerShell, Git"},
                {"category": "Security Operations", "skills": "Splunk (Log Analysis), ServiceNow (Ticketing), Microsoft Azure"},
            ]
            base["projects"] = [proj_bugbounty, proj_burp_ai, proj_jobagent]
            base["experiences"] = [exp_analyst, exp_consultant]
            base["certifications"] = certs_all

        elif archetype == "appsec_engineer":
            base["headline"] = "Application Security Engineer | DevSecOps & API Security"
            base["summary"] = (
                "Application Security Engineer focused on secure software development lifecycle (SDLC), REST/SOAP API security assessments, "
                "and vulnerability remediation. Experienced in developing custom security extensions with FastAPI, Burp Suite Pro (Montoya API), "
                "and local AI models for automated payload analysis."
            )
            base["skill_groups"] = [
                {"category": "Application Security", "skills": "OWASP Top 10, REST & SOAP API Security, Burp Suite Pro, ZAP, SAST/DAST concepts"},
                {"category": "Software Engineering", "skills": "Python, FastAPI, Java, C++, SQL, Bash, JSON, Git"},
                {"category": "Security Engineering", "skills": "Local AI Security Advisory (Ollama/MCP), Automated Triage, Authentication & Session Security"},
                {"category": "Cloud & Systems", "skills": "Microsoft Azure (AZ-900, DP-900), Kali Linux, Windows, AWS EC2"},
            ]
            base["projects"] = [proj_burp_ai, proj_bugbounty, proj_antares]
            base["experiences"] = [exp_analyst, exp_consultant]
            base["certifications"] = certs_all

        elif archetype == "soc_analyst":
            base["headline"] = "SOC Analyst | Security Operations & Incident Response"
            base["summary"] = (
                "Security Operations Analyst with hands-on experience in SIEM event monitoring, critical alert triage, and incident response workflows. "
                "Proficient in analyzing event data across Splunk, documenting incident tickets in ServiceNow and JIRA, and investigating TCP/IP network anomalies. "
                "CCNA certified with practical knowledge of networking fundamentals and procedural controls."
            )
            base["skill_groups"] = [
                {"category": "SIEM & Monitoring", "skills": "Splunk (Log Monitoring & False Positive Elimination), SIEM Dashboards, Alert Triage"},
                {"category": "Incident Response", "skills": "ServiceNow, JIRA, Incident Documentation, Severity Classification, Shift Handover"},
                {"category": "Networking & Protocols", "skills": "CCNA (TCP/IP, DNS, OSI Layers, Routing & Switching), Wireshark, Network Access"},
                {"category": "Security & Scripting", "skills": "Python, Bash, OWASP Basics, Azure Fundamentals, Kali Linux"},
            ]
            base["projects"] = [proj_jobagent, proj_antares, proj_bugbounty]
            base["experiences"] = [exp_analyst, exp_consultant]
            base["certifications"] = certs_all

        else:  # network_security
            base["headline"] = "Network & Cloud Security Specialist | CCNA Certified"
            base["summary"] = (
                "Network & Cloud Security Specialist with CCNA certification and 5+ years of combined IT systems experience. "
                "Demonstrated competence in network access protocols, procedural security controls, IP connectivity, and Microsoft Azure cloud fundamentals. "
                "Skilled in automation scripting with Python and Bash."
            )
            base["skill_groups"] = [
                {"category": "Network Infrastructure", "skills": "CCNA 200-301 (Routing, Switching, IP Connectivity, Network Services, Security Fundamentals)"},
                {"category": "Cloud Technologies", "skills": "Microsoft Azure (AZ-900 Fundamentals, DP-900 Data Fundamentals), AWS EC2"},
                {"category": "Systems Administration", "skills": "Procedural Controls, Diagnostics, Protocol Implementation, Linux, Windows"},
                {"category": "Scripting & Automation", "skills": "Python, Bash, WebSockets, Redis, Git"},
            ]
            base["projects"] = [proj_antares, proj_jobagent, proj_bugbounty]
            base["experiences"] = [exp_consultant, exp_analyst]
            base["certifications"] = certs_all

        base["education"] = education
        return base



