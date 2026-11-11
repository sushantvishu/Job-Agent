"""
app/cover_email_composer.py — Generates a tailored, authentic cover email body
for LinkedIn post or direct email job applications.

Uses the configured LLM client when available; falls back to a deterministic
template that is professional and reads naturally.

Part of the Job Agent Framework — https://github.com/YOUR_USERNAME/job-agent
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any

logger = logging.getLogger("cover_email_composer")

MAJOR_TECH_HUBS = [
    ("Bengaluru", ("bengaluru", "bangalore")),
    ("Pune", ("pune",)),
    ("Hyderabad", ("hyderabad",)),
    ("Chennai", ("chennai",)),
    ("Mumbai", ("mumbai", "navi mumbai")),
    ("Gurugram", ("gurugram", "gurgaon")),
    ("Noida", ("noida", "greater noida")),
    ("Delhi NCR", ("delhi", "delhi ncr", "new delhi")),
    ("Kolkata", ("kolkata", "calcutta")),
    ("Ahmedabad", ("ahmedabad",)),
    ("Kochi", ("kochi", "cochin")),
    ("Coimbatore", ("coimbatore",)),
    ("Indore", ("indore",)),
    ("Chandigarh", ("chandigarh", "mohali")),
    ("Jaipur", ("jaipur",)),
]


BAD_POSTER_TOKENS = {
    "threat", "security", "managed", "assistant", "manager", "recruiter",
    "team", "engineer", "lead", "analyst", "services", "solutions",
    "cyber", "hiring", "human", "resource", "talent", "staffing", "admin"
}


def clean_poster_name(name: str) -> str:
    if not name:
        return "Hiring Team"
    clean = name.strip()
    if clean.lower() in {"recruiter", "hiring manager", "talent acquisition"} or len(clean) > 35:
        return "Hiring Team"
    if any(b in clean.lower() for b in BAD_POSTER_TOKENS):
        return "Hiring Team"
    return clean


def clean_company_name(comp: str) -> str:
    if not comp:
        return ""
    clean = comp.strip().strip("'\"’“”.,;:!- ")
    if len(clean) <= 2:
        return ""
    try:
        from app.linkedin_post_scanner import EXACT_COMPANY_BLOCKLIST, GARBAGE_COMPANY_PHRASES
        clean_lower = clean.lower()
        if clean_lower in EXACT_COMPANY_BLOCKLIST:
            return ""
        if any(phrase in clean_lower for phrase in GARBAGE_COMPANY_PHRASES):
            return ""
    except Exception:
        if clean.lower() in {"application", "freshers", "cloud", "junior", "information", "cyber", "about the role", "we offer", "your company", "the company", "our company"}:
            return ""
    return clean


def extract_cities_from_context(text: str) -> list[str]:
    """Extract mentioned Indian tech hubs from post content/context."""
    from app.utils import contains_word
    lowered = text.lower()
    matched_cities: list[str] = []
    for canonical_name, aliases in MAJOR_TECH_HUBS:
        if any(contains_word(alias, lowered) for alias in aliases):
            matched_cities.append(canonical_name)
    return matched_cities


def build_location_pitch(text: str) -> str:
    """
    Build multi-city availability pitch if multiple locations or other cities are mentioned.
    """
    cities = extract_cities_from_context(text)
    non_blr = [c for c in cities if c != "Bengaluru"]
    if len(cities) >= 2 or non_blr:
        if len(cities) == 1:
            city_str = cities[0]
        elif len(cities) == 2:
            city_str = f"{cities[0]} and {cities[1]}"
        else:
            city_str = f"{', '.join(cities[:-1])}, and {cities[-1]}"
        return f"I am an immediate joiner based in Bengaluru, actively available for {city_str} (as well as Remote work / Relocation across India)."
    return "I am an immediate joiner based in Bengaluru, open to relocation across India and remote work."


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic template (used when LLM is unavailable)
# ─────────────────────────────────────────────────────────────────────────────

_COVER_TEMPLATE = """\
<html>
<body style="font-family: Arial, sans-serif; font-size: 14px; color: #222; line-height: 1.6;">

<p>Dear {poster_name},</p>

<p>
I'm <strong>{candidate_name}</strong>, a {candidate_headline} with hands-on experience in {top_skills}.
I came across your post {opportunity_phrase_html} and would like to apply for the same.
</p>

<p>
{skills_paragraph}
</p>

{candidate_overview_html}

<p>
{location_pitch}
</p>

<p>
Please find my resume attached. I would welcome the opportunity to discuss how my hands-on skills can contribute to your team.
</p>

{signature_html}

</body>
</html>
"""

_SKILLS_PARA_TEMPLATE = """\
My background specifically covers {skills_list}. I have worked on web application penetration testing
using OWASP Top 10 methodology, performed vulnerability assessments, and gained exposure to SOC alert
triage and threat monitoring. I build automation tools in Python that assist in security workflows.
"""

_PLAIN_TEXT_TEMPLATE = """\
Dear {poster_name},

I'm {candidate_name}, a cybersecurity-focused professional with {experience_text} of hands-on experience in
VAPT, OWASP methodology, Burp Suite, API security testing, and SOC workflows. I came across your post
{opportunity_phrase_plain} and would like to apply for the same.

{skills_paragraph_plain}

{candidate_overview_plain}

{location_pitch}

Please find my resume attached. I would welcome the opportunity to discuss how my hands-on skills can contribute to your team.

{signature_plain}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Composer class
# ─────────────────────────────────────────────────────────────────────────────

class CoverEmailComposer:
    """
    Generates a tailored cover email (HTML + plain) for a LinkedIn post email application.

    Uses Ollama LLM for personalization when available; falls back to the
    deterministic template which is still professional and concise.
    """

    # LLM system prompt — dynamically built from the loaded candidate profile at runtime.
    # This constant is the fallback template; _build_llm_system() uses profile data instead.
    _LLM_SYSTEM_FALLBACK = (
        "You are drafting a professional job application email on behalf of a candidate. "
        "Write emails that are concise (3-5 sentences), authentic, and professional. "
        "Never use clichéd phrases like 'dynamic individual', 'passionate learner', or "
        "'team player'. Mention specific skills relevant to the job post. "
        "Do not hallucinate experience or qualifications not listed in the profile."
    )

    @property
    def _LLM_SYSTEM(self) -> str:
        """Build a profile-aware LLM system prompt at runtime."""
        if self.profile:
            name = self.profile.name or "the candidate"
            email = self.profile.email or ""
            headline = self.profile.headline or "professional"
            skills = ", ".join((self.profile.skills or [])[:8]) or "relevant technical skills"
            exp = getattr(self.profile, "experience_years", 1)
            email_hint = f" ({email})" if email else ""
            return (
                f"You are drafting a job application email for {name}{email_hint}, "
                f"a {headline} with {exp} year(s) of hands-on experience in {skills}. "
                "Write emails that are concise (3-5 sentences), authentic, and professional. "
                "Never use clichéd phrases like 'dynamic individual', 'passionate learner', or "
                "'team player'. Mention specific skills from the job post. No hallucinated experience."
            )
        return self._LLM_SYSTEM_FALLBACK

    def __init__(self, ollama_client=None, profile=None) -> None:
        self.ollama_client = ollama_client
        if profile is None:
            try:
                from app.config import load_config
                from app.profile_loader import load_profile
                self.profile = load_profile(load_config().profile_path)
            except Exception:
                self.profile = None
        else:
            self.profile = profile

    def _get_signature_html(self) -> str:
        name = self.profile.name if self.profile and self.profile.name else "Candidate"
        headline = self.profile.headline if self.profile and self.profile.headline else "Cybersecurity Professional"
        phone = self.profile.phone if self.profile and self.profile.phone else ""
        email = self.profile.email if self.profile and self.profile.email else ""
        linkedin = self.profile.links.get("linkedin", "") if self.profile else ""
        github = self.profile.links.get("github", "") if self.profile else ""

        links_html = []
        if linkedin:
            clean_li = re.sub(r"^https?://", "", linkedin).rstrip("/")
            links_html.append(f'<a href="{linkedin}">{clean_li}</a>')
        if github:
            clean_gh = re.sub(r"^https?://", "", github).rstrip("/")
            links_html.append(f'<a href="{github}">{clean_gh}</a>')
        links_str = " | ".join(links_html)
        if links_str:
            links_str = f"<br>🔗 {links_str}"

        contact_parts = []
        if phone:
            contact_parts.append(f"📞 {phone}")
        if email:
            contact_parts.append(f"📧 {email}")
        contact_str = " | ".join(contact_parts)
        if contact_str:
            contact_str = f"<br>{contact_str}"

        return f"""<p>
Regards,<br>
<strong>{name}</strong><br>
{headline}{contact_str}{links_str}
</p>"""

    def _get_signature_plain(self) -> str:
        name = self.profile.name if self.profile and self.profile.name else "Candidate"
        headline = self.profile.headline if self.profile and self.profile.headline else "Cybersecurity Professional"
        phone = self.profile.phone if self.profile and self.profile.phone else ""
        email = self.profile.email if self.profile and self.profile.email else ""
        linkedin = self.profile.links.get("linkedin", "") if self.profile else ""
        github = self.profile.links.get("github", "") if self.profile else ""

        lines = ["Regards,", name, headline]
        contact = " | ".join(filter(None, [phone, email]))
        if contact:
            lines.append(contact)
        links = " | ".join(filter(None, [re.sub(r"^https?://", "", l).rstrip("/") for l in [linkedin, github] if l]))
        if links:
            lines.append(links)
        return "\n".join(lines)

    def compose(
        self,
        role: str,
        company: str,
        poster_name: str,
        skills_mentioned: list[str],
        job_context: str = "",
    ) -> tuple[str, str]:
        """
        Generate (html_body, plain_body) for the cover email.

        Parameters
        ----------
        role            : Job role title from the LinkedIn post
        company         : Company name
        poster_name     : Name of the person who posted (default: "Hiring Team")
        skills_mentioned: Skills extracted from the LinkedIn post
        job_context     : Raw snippet from the post for LLM context
        """
        display_poster = clean_poster_name(poster_name)
        display_company = clean_company_name(company)
        display_role = (role or "").strip()
        if not display_role or display_role.lower() in {"cybersecurity role", "role", "job", "opportunity"}:
            display_role = "Cybersecurity / VAPT Analyst"

        if self.ollama_client and job_context:
            try:
                return self._compose_with_llm(display_role, display_company, display_poster, skills_mentioned, job_context)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM cover email generation failed, using template: %s", exc)

        return self._compose_with_template(display_role, display_company, display_poster, skills_mentioned, job_context)

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _compose_with_llm(
        self,
        role: str,
        company: str,
        poster_name: str,
        skills_mentioned: list[str],
        job_context: str,
    ) -> tuple[str, str]:
        skills_str = ", ".join(skills_mentioned[:6]) if skills_mentioned else "VAPT, OWASP, Burp Suite, Python, SOC"
        candidate_name = self.profile.name if self.profile and self.profile.name else "Candidate"
        experience_text = f"{self.profile.experience_years:g} year" if self.profile and self.profile.experience_years else "1 year"
        location = self.profile.location if self.profile and self.profile.location else "Bengaluru"

        multi_cities = extract_cities_from_context(f"{role} {company} {job_context}")
        multi_city_note = ""
        if len(multi_cities) >= 2 or any("bengaluru" not in c.lower() for c in multi_cities):
            multi_city_note = f" The post mentions locations: {', '.join(multi_cities)}. Explicitly note that candidate is based in {location} and actively available for {', '.join(multi_cities)} as well as remote/relocation."

        prompt = (
            f"Write a short (4 sentences max) professional job application email body for {candidate_name}, "
            f"applying for the role of '{role}' at '{company}'. "
            f"Candidate saw this post on LinkedIn:\n\n\"{job_context[:400]}\"\n\n"
            f"Candidate relevant skills: {skills_str}. "
            f"Mention {experience_text} experience, immediate joiner based in {location}.{multi_city_note} "
            f"Start with 'Dear {poster_name},' — Keep it direct, human, and sincere. No buzzwords."
        )

        system_prompt = (
            f"You are drafting a job application email for {candidate_name}, "
            f"a cybersecurity specialist with {experience_text} of hands-on experience in VAPT, OWASP, Burp Suite, API security, and Python. "
            "Write emails that are concise (3-5 sentences), authentic, and professional. No corporate clichés or hallucinated experience."
        )

        raw = self.ollama_client.generate(prompt=prompt, system=system_prompt)
        # Trim fluff from LLM
        body_plain = raw.strip().strip('"\'')
        if len(body_plain.split()) < 20:
            raise ValueError("LLM output too short, falling back to template")

        # Wrap in HTML
        body_html = self._plain_to_html(body_plain, role, company)
        return body_html, body_plain

    # ------------------------------------------------------------------
    # Template path
    # ------------------------------------------------------------------

    def _compose_with_template(
        self,
        role: str,
        company: str,
        poster_name: str,
        skills_mentioned: list[str],
        job_context: str = "",
    ) -> tuple[str, str]:
        if skills_mentioned:
            top_skills = skills_mentioned[:5]
            skills_list = ", ".join(top_skills)
        else:
            skills_list = "VAPT, OWASP Top 10, Burp Suite, Python, API security testing, SOC workflows"

        candidate_name = self.profile.name if self.profile and self.profile.name else "Candidate"
        experience_text = f"{self.profile.experience_years:g} year" if self.profile and self.profile.experience_years else "1 year"

        skills_para = _SKILLS_PARA_TEMPLATE.format(skills_list=skills_list).strip()
        location_pitch = build_location_pitch(f"{role} {company} {job_context}")

        # Dynamic phrasing to never produce awkward "at Application" or "at your company"
        clean_company = (company or "").strip()
        if clean_company and clean_company.lower() not in {"your company", "the company", "unknown"}:
            opportunity_phrase_html = f"regarding the <strong>{html.escape(role)}</strong> opportunity at <strong>{html.escape(clean_company)}</strong>"
            opportunity_phrase_plain = f"regarding the {role} opportunity at {clean_company}"
        else:
            opportunity_phrase_html = f"regarding the <strong>{html.escape(role)}</strong> opportunity"
            opportunity_phrase_plain = f"regarding the {role} opportunity"

        # Candidate Overview block - dynamically assembled from profile data
        _p_location = ((self.profile.location if self.profile and self.profile.location else 'Your City') + ' (Open to Relocation & Remote)')
        _p_notice = getattr(self.profile, 'notice_period', None) or 'Available'
        _p_current_ctc = getattr(getattr(self.profile, 'compensation', None), 'current_salary', None) or 'Entry-Level / Negotiable'
        _p_expected_ctc = getattr(getattr(self.profile, 'compensation', None), 'expected_salary', None) or 'Competitive / Negotiable'
        _p_skills_summary = ', '.join((self.profile.skills or [])[:6]) if self.profile else skills_list

        candidate_overview_html = (
            "<p style='background: #f8f9fa; border-left: 3px solid #0066cc; padding: 10px 14px; margin: 14px 0;'>"
            "<strong>Candidate Overview:</strong><br>"
            f"• <strong>Total Experience:</strong> {experience_text}<br>"
            f"• <strong>Current Location:</strong> {html.escape(_p_location)}<br>"
            f"• <strong>Notice Period:</strong> {html.escape(_p_notice)}<br>"
            f"• <strong>Current CTC:</strong> {html.escape(_p_current_ctc)}<br>"
            f"• <strong>Expected CTC:</strong> {html.escape(_p_expected_ctc)}<br>"
            f"• <strong>Key Skills:</strong> {html.escape(_p_skills_summary)}"
            "</p>"
        )

        candidate_overview_plain = (
            "Candidate Overview:\n"
            f"• Total Experience: {experience_text}\n"
            f"• Current Location: {_p_location}\n"
            f"• Notice Period: {_p_notice}\n"
            f"• Current CTC: {_p_current_ctc}\n"
            f"• Expected CTC: {_p_expected_ctc}\n"
            f"• Key Skills: {_p_skills_summary}"
        )

        html_body = _COVER_TEMPLATE.format(
            poster_name=html.escape(poster_name),
            opportunity_phrase_html=opportunity_phrase_html,
            candidate_name=html.escape(candidate_name),
            experience_text=html.escape(experience_text),
            skills_paragraph=html.escape(skills_para),
            candidate_overview_html=candidate_overview_html,
            location_pitch=html.escape(location_pitch),
            signature_html=self._get_signature_html(),
        )

        plain_body = _PLAIN_TEXT_TEMPLATE.format(
            poster_name=poster_name,
            opportunity_phrase_plain=opportunity_phrase_plain,
            candidate_name=candidate_name,
            experience_text=experience_text,
            skills_paragraph_plain=skills_para,
            candidate_overview_plain=candidate_overview_plain,
            location_pitch=location_pitch,
            signature_plain=self._get_signature_plain(),
        )

        return html_body, plain_body

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _plain_to_html(self, plain: str, role: str, company: str) -> str:
        """Wrap plain LLM text in a styled HTML email with signature."""
        paragraphs = plain.split("\n\n")
        body_content = "\n".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs if p.strip())

        clean_comp = (company or "").strip()
        comp_str = f" at <strong>{html.escape(clean_comp)}</strong>" if clean_comp and clean_comp.lower() not in {"your company", "the company", "unknown"} else ""

        return f"""\
<html>
<body style="font-family: Arial, sans-serif; font-size: 14px; color: #222; line-height: 1.6;">

{body_content}

<p>
Please find my resume attached for the <strong>{html.escape(role)}</strong> position{comp_str}.
I look forward to your response.
</p>

{self._get_signature_html()}

</body>
</html>
"""

