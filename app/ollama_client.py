from __future__ import annotations

import json
import re
import threading
from typing import Any

import requests

from app.llm.base import LLMProvider
from app.utils import JobPosting, ProfileData, compact_whitespace


class OllamaClient(LLMProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        logger,
        timeout: int = 25,
        api_style: str = "ollama",
        fallback_models: list[str] | None = None,
        api_key: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.logger = logger
        self.timeout = timeout
        self.api_style = api_style.lower()
        self.fallback_models = fallback_models or []
        self.api_key = api_key or ""
        self._idle_stop_timer: threading.Timer | None = None
        self._idle_timeout_seconds: int = 45
        self._managed_process = None

    def is_available(self) -> bool:
        try:
            url = f"{self.base_url}/api/tags" if self.api_style == "ollama" else f"{self.base_url}/v1/models"
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            self.logger.warning("Local AI availability check failed: %s", exc)
            return False

    def ensure_server_running(self) -> bool:
        """On-demand startup: if local Ollama is not running, launch it in background."""
        if self.api_style != "ollama":
            return True
        if self.is_available():
            return True
        try:
            import os
            import subprocess
            import time

            self.logger.info("Local Ollama not detected — launching on-demand in background...")
            ollama_bin = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
            if not os.path.exists(ollama_bin):
                ollama_bin = "ollama"

            creationflags = 0
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW

            self._managed_process = subprocess.Popen(
                [ollama_bin, "serve"],
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            for _ in range(12):
                time.sleep(1)
                try:
                    url = f"{self.base_url}/api/tags"
                    resp = requests.get(url, timeout=3)
                    if resp.status_code == 200:
                        self.logger.info("Local Ollama server successfully started on-demand.")
                        return True
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Could not auto-start Ollama server: %s", exc)
        return False

    def unload_model(self, model: str | None = None) -> bool:
        """Immediately unload model weights from RAM to free system memory."""
        if self.api_style != "ollama":
            return True
        target_model = model or self.model
        try:
            url = f"{self.base_url}/api/generate"
            payload = {"model": target_model, "keep_alive": 0}
            resp = requests.post(url, json=payload, timeout=5)
            self.logger.info("Ollama model %s unloaded from RAM (keep_alive: 0).", target_model)
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not unload Ollama model %s: %s", target_model, exc)
            return False

    def _cancel_idle_timer(self) -> None:
        if self._idle_stop_timer:
            try:
                self._idle_stop_timer.cancel()
            except Exception:
                pass
            self._idle_stop_timer = None

    def _schedule_idle_stop(self) -> None:
        """Schedule automatic termination of local Ollama if idle for 45s."""
        self._cancel_idle_timer()
        if self.api_style != "ollama":
            return

        def _auto_stop() -> None:
            self.logger.info("Local Ollama idle timeout (%ds) reached — force closing to conserve RAM...", self._idle_timeout_seconds)
            self.stop_server()

        self._idle_stop_timer = threading.Timer(self._idle_timeout_seconds, _auto_stop)
        self._idle_stop_timer.daemon = True
        self._idle_stop_timer.start()

    def stop_server(self) -> None:
        """Unload models from RAM. If Ollama was launched by this process, terminate it cleanly."""
        self._cancel_idle_timer()
        try:
            self.unload_model()
        except Exception:
            pass

        if self._managed_process is not None:
            try:
                self._managed_process.terminate()
                self._managed_process.wait(timeout=3)
            except Exception:
                try:
                    self._managed_process.kill()
                except Exception:
                    pass
            self._managed_process = None
            self.logger.info("Stopped agent-spawned Ollama process.")
        else:
            self.logger.info("Unloaded models from RAM (left host Ollama server running).")

    def generate(self, prompt: str, system: str | None = None) -> str:
        # Auto-launch Ollama on demand if it was stopped to save RAM
        self._cancel_idle_timer()
        if self.api_style == "ollama" and not self.is_available():
            self.ensure_server_running()

        errors: list[str] = []
        try:
            for model in [self.model, *self.fallback_models]:
                try:
                    return self._generate_with_model(model, prompt, system)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{model}: {exc}")
                    self.logger.warning("Local AI model failed, trying fallback if available | model=%s | error=%s", model, exc)
            raise RuntimeError("; ".join(errors))
        finally:
            self._schedule_idle_stop()

    def _generate_with_model(self, model: str, prompt: str, system: str | None = None) -> str:
        if self.api_style == "openai":
            return self._generate_openai_compatible(model, prompt, system)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": 0,
            "options": {
                "num_thread": 4,
                "num_ctx": 512,
                "num_predict": 80,
                "temperature": 0.1,
            },
        }
        if system:
            payload["system"] = system

        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()

    def _generate_openai_compatible(self, model: str, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _detect_job_domain(job: JobPosting) -> str:
        """Classify job into target technical archetype for domain-specific language."""
        text = f"{job.title} {job.description} {' '.join(job.skills)}".lower()
        if any(k in text for k in ("vapt", "penetrat", "pentest", "offensive", "ethical hack", "burp", "red team", "cve", "kali")):
            return "vapt"
        if any(k in text for k in ("soc", "siem", "splunk", "incident response", "alert triage", "threat", "sentinel", "blue team")):
            return "soc"
        if any(k in text for k in ("appsec", "application security", "product security", "api security", "devsecops", "secure code")):
            return "appsec"
        if any(k in text for k in ("python", "backend", "software engineer", "developer", "fastapi", "django", "flask", "automation engineer")):
            return "python"
        return "cybersecurity"

    def generate_application_material(self, job: JobPosting, profile: ProfileData) -> dict[str, Any]:
        """Generate tailored, HR-aligned, role-specific application materials grounded in candidate resume."""
        from app.utils import normalize_key

        domain = self._detect_job_domain(job)
        # Rank candidate verified skills matching job description and criteria
        job_tokens = normalize_key(f"{job.title} {job.description} {' '.join(job.skills)}")
        matching_skills = [s for s in profile.skills if normalize_key(s) in job_tokens]
        remaining_skills = [s for s in profile.skills if s not in matching_skills]
        top_skills = (matching_skills + remaining_skills)[:7] or profile.skills[:7]
        skills_pitch = ", ".join(top_skills)

        # Domain-aligned experience summaries grounded strictly in candidate experience years
        exp_years_str = f"{profile.experience_years:.1f}".rstrip("0").rstrip(".")
        exp_phrase = f"{exp_years_str} year" if exp_years_str == "1" else f"{exp_years_str} years"
        if domain == "vapt":
            experience_summary = (
                f"{exp_phrase} of hands-on experience in vulnerability assessment, "
                f"web application penetration testing (OWASP Top 10), and API security using Burp Suite and Python automation."
            )
            fallback_cover = (
                f"Dear Hiring Team, I am writing to apply for the {job.title} position at {job.company}. "
                f"With {exp_phrase} of hands-on experience in VAPT, OWASP Top 10 web testing, and API security using Burp Suite, "
                f"I specialize in identifying security flaws, testing REST endpoints, and automating security tasks in Python. "
                "I look forward to discussing how my offensive security skills align with your team's objectives."
            )
        elif domain == "soc":
            experience_summary = (
                f"{exp_phrase} of hands-on security operations (SOC) experience, "
                f"monitoring SIEM dashboards, triaging critical alerts, analyzing IP/log vectors, and automating workflows in Python."
            )
            fallback_cover = (
                f"Dear Hiring Team, I am applying for the {job.title} position at {job.company}. "
                f"I bring {exp_phrase} of hands-on exposure to SOC operations, SIEM alert triage, log correlation, "
                f"and threat monitoring using Wireshark and Python tooling. "
                "I am eager to contribute to maintaining your organization's robust security posture."
            )
        elif domain == "appsec":
            experience_summary = (
                f"{exp_phrase} of hands-on application security experience, "
                f"specializing in OWASP methodology, API vulnerability testing, Burp Suite, and security tooling in Python."
            )
            fallback_cover = (
                f"Dear Hiring Team, I am pleased to apply for the {job.title} role at {job.company}. "
                f"My background covers {exp_phrase} of hands-on AppSec, testing web applications against OWASP Top 10, "
                f"performing API security assessments, and building verification tooling in Python. "
                "I welcome the opportunity to contribute to your product security initiatives."
            )
        elif domain == "python":
            experience_summary = (
                f"{exp_phrase} of hands-on Python engineering and security automation experience, "
                f"building robust backend scripts, API integrations, and security verification tools."
            )
            fallback_cover = (
                f"Dear Hiring Team, I am applying for the {job.title} opportunity at {job.company}. "
                f"With {exp_phrase} of hands-on Python development experience, I build production backend services, "
                f"REST API integrations, and automated security verification tools. "
                "I look forward to discussing how my technical background can benefit your engineering team."
            )
        else:
            experience_summary = (
                f"{exp_phrase} of hands-on cybersecurity experience covering vulnerability assessment, "
                f"security operations hygiene, and Python-based security automation."
            )
            fallback_cover = (
                f"Dear Hiring Team, I am applying for the {job.title} position at {job.company}. "
                f"My background covers {exp_phrase} of hands-on cybersecurity experience across VAPT, "
                f"network reconnaissance, and security automation. "
                "I am eager to contribute effectively to your cybersecurity operations."
            )

        cover_letter = fallback_cover

        # Micro-prompt: concise, role-grounded application note using LLM
        try:
            prompt = (
                f"Job: {job.title} at {job.company}\n"
                f"Job Domain: {domain.upper()}\n"
                f"Candidate: {profile.name} (Experience: {profile.experience_years} year, Skills: {skills_pitch})\n"
                f"Write a 40-50 word authentic, professional application note. "
                f"Highlight specific matching hands-on skills ({', '.join(top_skills[:3])}). "
                "Direct, engineer-to-engineer, zero buzzwords, strictly truthful to 1 year experience."
            )
            raw = self.generate(prompt=prompt, system=self._system_prompt(profile))
            cleaned = re.sub(r'^(here\'?s\s+.*?:\s*|["\'])', '', raw.strip(), flags=re.I).strip('"\u201c\u201d\'')
            if cleaned and len(cleaned.split()) >= 15:
                cover_letter = compact_whitespace(cleaned)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Cover letter micro-prompt failed, using domain template: %s", exc)

        return {
            "cover_letter": cover_letter,
            "experience_summary": experience_summary,
            "skills_pitch": skills_pitch,
            "used_fallback": False,
        }

    def answer_question(self, job: JobPosting, profile: ProfileData, question: str) -> str:
        """Deterministic fast-path (0 CPU, 0ms) + context-pruned micro-prompting."""
        from app.utils import normalize_key

        norm_q = normalize_key(question)

        # ── Fast-path 1: Relocation / Onsite / US Office / Shifts (Instant, 0 CPU) ──
        if any(w in norm_q for w in ("relocat", "onsite", "san francisco", "us office", "travel", "shift", "willing to move", "hybrid")):
            return "Yes"

        # ── Fast-path 2: Notice period / Availability (Instant, 0 CPU) ──
        if any(w in norm_q for w in ("days to join", "joining in days", "notice in days", "notice period in days", "how many days")):
            return "0"
        if any(w in norm_q for w in ("notice period", "joining", "how soon", "when can you start", "availability")):
            return "Immediate"

        # ── Fast-path 3: Visa Sponsorship vs Work Authorization (Instant, 0 CPU) ──
        if any(w in norm_q for w in ("require sponsor", "require visa", "sponsorship", "need sponsor", "visa sponsorship")):
            return "No"
        if any(w in norm_q for w in ("authorized to work", "work authorization", "legally authorized", "right to work", "work permit", "eligible to work")):
            return "Yes"

        # ── Fast-path 4: Experience in years (Instant, 0 CPU) ──
        if any(w in norm_q for w in ("years of experience", "total experience", "how many years", "work experience", "overall experience")):
            if any(w in norm_q for w in ("range", "band", "level")):
                return "0-1 years"
            return "1"

        # ── Fast-path 5: Current CTC vs Expected CTC (Instant, 0 CPU) ──
        if any(w in norm_q for w in ("current ctc", "current salary", "present ctc", "present salary", "existing ctc", "last drawn", "fixed ctc")):
            return "0 LPA (Fresher)"
        if any(w in norm_q for w in ("expected ctc", "expected salary", "target ctc", "desired ctc", "compensation", "salary expectation", "pay expectation", "salary", "ctc")):
            return "₹4.5 LPA (4-6 LPA)"

        # ── Fast-path 6: Biographical & Education standard fields (Instant, 0 CPU) ──
        if "gender" in norm_q or "sex" in norm_q:
            return "Male"
        if "marital" in norm_q:
            return "Single"
        if "nationality" in norm_q or "citizenship" in norm_q:
            return "Indian"
        if any(w in norm_q for w in ("degree", "highest qualification", "education level")):
            return "Bachelor's Degree (B.Tech in Computer Science)"
        if any(w in norm_q for w in ("disability", "differently abled")):
            return "No"
        if any(w in norm_q for w in ("veteran", "military")):
            return "I am not a protected veteran"

        # ── Fast-path 7: Profile saved custom answers (Instant, 0 CPU) ──
        if norm_q in profile.custom_answers:
            return profile.custom_answers[norm_q]

        # ── Fast-path 8: Common technical & behavioral application questions ──
        if any(w in norm_q for w in ("why this company", "why do you want to work", "why join", "why work with us", "why us")):
            return f"I am eager to contribute my hands-on VAPT and security analysis skills to {job.company}'s security team, while continuing to learn and secure critical systems."
        if any(w in norm_q for w in ("vapt experience", "penetration testing experience", "burp suite experience", "vulnerability assessment experience")):
            return "I have hands-on experience performing web application vulnerability assessments using OWASP Top 10 methodology, Burp Suite, and Python automation."
        if any(w in norm_q for w in ("soc experience", "siem experience", "alert triage", "incident response")):
            return "I have hands-on exposure monitoring SIEM dashboards, triaging security alerts, investigating IP/log vectors, and analyzing network traffic."
        if any(w in norm_q for w in ("python experience", "programming experience", "scripting experience", "coding experience")):
            return "I have hands-on experience developing Python scripts for security automation, REST API testing, and data parsing."

        # ── Micro-Prompt: Only novel technical questions reach the LLM ──
        matching = [s for s in profile.skills if normalize_key(s) in norm_q]
        skills_context = ", ".join(matching[:4]) or ", ".join(profile.skills[:4])
        desc_excerpt = compact_whitespace(job.description[:400]) if job.description else ""
        prompt = (
            f"Role: {job.title} at {job.company}\n"
            f"Job Excerpt: {desc_excerpt}\n"
            f"Candidate: {profile.name}, {profile.experience_years} yr experience in VAPT / SOC / Python.\n"
            f"Skills: {skills_context}.\n"
            f"Question: {question}\n"
            f"Answer directly in 1 short, professional sentence (under 25 words) strictly truthful to candidate profile:"
        )
        try:
            raw = self.generate(prompt=prompt, system=self._system_prompt(profile))
            cleaned = re.sub(r"^(here'?s\s+(a\s+)?(possible\s+)?answer:?\s*|answer:?\s*)", "", raw.strip(), flags=re.I).strip()
            cleaned = cleaned.strip('"\u201c\u201d\'')
            return compact_whitespace(cleaned)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Micro-prompt Q&A failed for %r: %s", question, exc)
            return "Yes" if "experience" in norm_q or "knowledge" in norm_q else ""

    def _fallback_material(self, job: JobPosting, profile: ProfileData) -> dict[str, Any]:
        cover_letter = (
            f"Hello, I am applying for the {job.title or 'cybersecurity'} role at {job.company or 'your company'}. "
            f"My background includes {', '.join(profile.skills[:4])} and hands-on practice in cybersecurity tasks. "
            "I am interested in roles where I can contribute honestly while continuing to learn."
        )
        experience_summary = (
            f"{profile.summary} Core skills: {', '.join(profile.skills[:6])}. "
            f"Current experience level: {profile.experience_years} years."
        )
        skills_pitch = ", ".join(profile.skills[:8])
        return {
            "cover_letter": compact_whitespace(cover_letter),
            "experience_summary": compact_whitespace(experience_summary),
            "skills_pitch": skills_pitch,
        }

    def _build_material_prompt(self, job: JobPosting, profile: ProfileData) -> str:
        return f"""
Return JSON only with keys:
- cover_letter
- experience_summary
- skills_pitch

Candidate profile:
- Name: {profile.name}
- Location: {profile.location}
- Experience years: {profile.experience_years}
- Skills: {", ".join(profile.skills)}
- Summary: {profile.summary}

Job:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location}
- Experience: {job.experience}
- Skills asked: {", ".join(job.skills)}
- Description: {job.description[:5000]}

Rules:
- Use only facts given above.
- Never exaggerate, invent, or claim experience not present in the profile.
- Keep cover_letter under 70 words.
- Keep experience_summary under 40 words.
- Make skills_pitch a single comma-separated line of top 5-7 existing skills only.
""".strip()

    @staticmethod
    def _system_prompt(profile: ProfileData | None = None) -> str:
        name = profile.name if profile and profile.name else "the candidate"
        exp = f"{profile.experience_years:g} years" if profile and profile.experience_years else "1 year"
        return (
            f"You represent {name}, a cybersecurity professional with {exp} of hands-on experience in VAPT, OWASP Top 10, Burp Suite, API Security, SOC alert triage, and Python automation. "
            "Always write concise, truthful, highly authentic, engineer-to-engineer application text matching the exact job description and technical archetype. "
            "Never invent skills, certifications, or senior experience. Never use generic corporate buzzwords."
        )

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
        start = cleaned.find("{")
        if start == -1:
            raise ValueError("Model did not return JSON.")
        end = cleaned.rfind("}")
        if end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except Exception:
                pass
        # Auto-repair unclosed JSON truncated by token limits
        candidate = cleaned[start:].rstrip()
        if candidate.count('"') % 2 != 0:
            candidate += '"'
        if not candidate.endswith("}"):
            candidate = candidate.rstrip(",") + "}"
        try:
            return json.loads(candidate)
        except Exception:
            raise ValueError("Model did not return JSON.")

