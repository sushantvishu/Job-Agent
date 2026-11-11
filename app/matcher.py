from __future__ import annotations

from app.utils import (
    DISALLOWED_JOB_KEYWORDS,
    SENSITIVE_DATA_KEYWORDS,
    TARGET_ROLE_KEYWORDS,
    JobPosting,
    MatchResult,
    ProfileData,
    contains_any_keyword,
    contains_word,
    domain_from_url,
    extract_years_range,
    normalize_key,
    unique_list,
)

SKILL_SIGNAL_GROUPS = {
    "VAPT": {"vapt", "vulnerability assessment", "penetration testing", "pentest"},
    "OWASP": {"owasp", "owasp top 10"},
    "Burp Suite": {"burp", "burp suite", "burp suite professional", "burpsuite"},
    "API Security": {"api security", "owasp api", "rest api security"},
    "Nmap": {"nmap"},
    "Python": {"python", "automation scripting", "asyncio"},
    "FastAPI": {"fastapi", "rest api", "rest apis", "restful"},
    "Redis": {"redis"},
    "WebSockets": {"websocket", "websockets"},
    "AWS": {"aws", "amazon web services", "ec2"},
    "Docker": {"docker", "containerization"},
    "SQL": {"sql", "mysql", "postgresql", "sqlite"},
    "Git": {"git", "github", "gitlab"},
    "Wireshark": {"wireshark", "packet analysis"},
    "SIEM": {"siem", "splunk", "wazuh", "qradar", "microsoft sentinel"},
    "SOC": {"soc", "security operations center", "alert triage", "incident monitoring", "incident response"},
    "GRC": {"grc", "governance risk compliance", "iso 27001", "compliance"},
    "Bash": {"bash", "shell scripting"},
    "ZAP": {"zap", "owasp zap"},
    "Azure": {"azure", "microsoft azure"},
    "ServiceNow": {"service now", "servicenow"},
    "Bug Bounty": {"bug bounty", "responsible disclosure"},
}

ROLE_SIGNAL_GROUPS = {
    "python developer": {
        "python developer",
        "python engineer",
        "python backend developer",
        "python backend engineer",
        "backend developer",
        "software engineer",
        "software developer",
        "python programmer",
        "junior python developer",
        "python automation engineer",
    },
    "application security": {
        "application security",
        "appsec",
        "web app security",
        "web application security",
    },
    "soc analyst": {"soc analyst", "security operations center", "security monitoring", "l1 soc"},
    "cybersecurity analyst": {"cybersecurity analyst", "cyber security analyst", "information security analyst"},
    "grc analyst": {"grc analyst", "risk compliance", "governance risk compliance"},
    "vapt analyst": {"vapt analyst", "vapt", "penetration tester", "penetration testing", "vulnerability assessment"},
    "api security tester": {"api security tester", "api security", "owasp api"},
}

TECHNICAL_SUPPORT_FALLBACK_DECISION = "technical support fallback review"

OFFENSIVE_SECURITY_KEYWORDS = {
    "vapt",
    "penetration test",
    "penetration tester",
    "penetration testing",
    "pentest",
    "pentesting",
    "appsec",
    "application security",
    "red team",
    "red teaming",
    "offensive security",
    "owasp",
    "burp suite",
    "burpsuite",
    "ethical hacking",
    "ethical hacker",
    "web application security",
    "api security",
    "vulnerability assessment",
    "bug bounty",
}

TECHNICAL_SUPPORT_KEYWORDS = {
    "desktop support",
    "it support",
    "technical support",
    "technical support engineer",
    "technical support specialist",
}

NON_TECHNICAL_SUPPORT_KEYWORDS = {
    "bpo",
    "call center",
    "customer care",
    "customer service",
    "customer support",
    "inside sales",
    "sales",
    "telecaller",
    "telecalling",
    "voice process",
}

DISQUALIFYING_ROLE_KEYWORDS = {
    # Academic & Educational Drift
    "professor",
    "assistant professor",
    "associate professor",
    "lecturer",
    "faculty",
    "teacher",
    "academic",
    "curriculum",
    "phd scholar",
    "postdoc",
    "research fellow",
    "school teacher",
    "dean",
    # Non-technical / Sales / Operations Drift
    "telecaller",
    "telecalling",
    "bpo",
    "call center",
    "customer care",
    "customer service",
    "inside sales",
    "direct sales",
    "field sales",
    "sales executive",
    "business development",
    "recruiter",
    "talent acquisition",
    "human resources",
    "hr generalist",
    "hr executive",
    # Medical / Healthcare / Pharmaceutical (non-IT)
    "clinical",
    "pharmacist",
    "nursing",
    "medical officer",
}

INDIAN_LOCATIONS = {
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune", "delhi", "new delhi",
    "noida", "gurugram", "gurgaon", "chennai", "kolkata", "ahmedabad", "jaipur", "kochi",
    "cochin", "chandigarh", "indore", "coimbatore", "bhubaneswar", "nagpur", "thane",
    "navi mumbai", "karnataka", "maharashtra", "tamil nadu", "telangana", "haryana",
    "uttar pradesh", "kerala", "gujarat", "rajasthan", "west bengal", "punjab", "lucknow",
    "bhopal", "patna", "vadodara", "ghaziabad", "ludhiana", "agra", "nashik", "faridabad",
    "meerut", "rajkot", "kalyan", "vasai", "varanasi", "srinagar", "aurangabad", "dhanbad",
    "amritsar", "allahabad", "prayagraj", "ranchi", "howrah", "jabalpur", "gwalior",
    "vijayawada", "jodhpur", "madurai", "raipur", "kota", "guwahati", "solapur", "hubli",
    "dharwad", "mysore", "mysuru", "tiruchirappalli", "bareilly", "aligarh", "tiruppur",
    "moradabad", "jalandhar", "salem", "warangal", "guntur", "dehradun", "amravati",
    "bikaner", "nanded", "kolhapur", "ajmer", "akola", "gulbarga", "jamnagar", "ujjain",
    "siliguri", "jhansi", "ulhasnagar", "jammu", "sangli", "mangalore", "mangaluru",
    "erode", "belgaum", "belagavi", "kurnool", "secunderabad", "mohali", "trivandrum",
    "thiruvananthapuram", "andhra pradesh", "himachal pradesh", "uttarakhand", "goa", "odisha",
    "assam", "bihar", "jharkhand", "chhattisgarh"
}

FOREIGN_DOMAINS = {
    "uk.linkedin.com", "es.linkedin.com", "fr.linkedin.com", "de.linkedin.com", "pl.linkedin.com",
    "tw.linkedin.com", "pt.linkedin.com", "ca.linkedin.com", "au.linkedin.com", "sg.linkedin.com",
    "mx.linkedin.com", "al.linkedin.com", "vn.linkedin.com", "ro.linkedin.com", "nl.linkedin.com",
    "jp.linkedin.com", "kr.linkedin.com", "ie.linkedin.com", "br.linkedin.com", "ch.linkedin.com",
    "it.linkedin.com", "se.linkedin.com", "no.linkedin.com", "dk.linkedin.com", "fi.linkedin.com",
    "be.linkedin.com", "at.linkedin.com", "cz.linkedin.com", "nz.linkedin.com", "za.linkedin.com",
    "il.linkedin.com", "gr.linkedin.com", "hk.linkedin.com", "ae.linkedin.com", "ph.linkedin.com"
}

FOREIGN_LOCATION_SIGNALS = {
    "usa", "united states", "amerika serikat", "uk", "united kingdom", "inggris", "britania raya",
    "canada", "kanada", "australia", "germany", "jerman", "france", "prancis", "spain", "spanyol",
    "italy", "italia", "netherlands", "belanda", "poland", "polandia", "singapore", "singapura",
    "taiwan", "portugal", "vietnam", "ireland", "mexico", "meksiko", "japan", "jepang",
    "korea", "china", "switzerland", "swedia", "norway", "norwegia", "denmark", "finland", "brazil",
    "uae", "dubai", "philippines", "filipina", "malaysia", "indonesia", "albania", "romania",
    "rumania", "israel", "tel aviv", "amsterdam", "paris", "london", "toronto", "vancouver",
    "berlin", "munich", "barcelona", "madrid", "warsaw", "taipei", "seoul", "tokyo", "bangkok",
    "sydney", "melbourne", "auckland", "texas", "california", "virginia", "florida", "colorado",
    "georgia", "tennessee", "michigan", "ohio", "maryland", "illinois", "washington", "new york",
    "north carolina", "south carolina", "massachusetts", "pennsylvania", "new jersey", "arizona"
}


def is_india_location(location: str | None, url: str = "", source: str = "") -> bool:
    """Enforces target location policy: strictly apply to jobs located in India or remote in India."""
    u = (url or "").lower()
    loc = normalize_key(location or "")
    src = (source or "").lower()

    # Reject foreign country LinkedIn domains
    if any(d in u for d in FOREIGN_DOMAINS):
        return False

    # Reject explicit foreign location markers
    if any(sig in loc for sig in FOREIGN_LOCATION_SIGNALS):
        return False

    # Accept explicit Indian cities or states
    if any(city in loc for city in INDIAN_LOCATIONS):
        return True

    # Naukri is predominantly India-based
    if "naukri.com" in u or src == "naukri":
        # Ensure it does not mention Gulf/foreign location
        if any(sig in loc for sig in FOREIGN_LOCATION_SIGNALS):
            return False
        return True

    # Indian LinkedIn subdomain
    if "in.linkedin.com" in u:
        return True

    return False


class JobMatcher:
    def __init__(self, profile: ProfileData) -> None:
        self.profile = profile

    def score(self, job: JobPosting) -> MatchResult:
        # ── India-Only Location Enforcement (User Mandate) ─────────────
        if not is_india_location(job.location, job.url, job.source):
            return MatchResult(
                score=0,
                decision="skip",
                reasons=["Skipped: Requisition is outside India (User Mandate: India only)."],
                red_flags=["Location outside India (Mandate: India only)."],
                missing_skills=[],
                matched_skills=[],
                min_years_required=0,
                max_years_required=0,
                auto_submit_safe=False,
            )

        title = normalize_key(job.title)

        # ── Negative Role Disqualification (Academic, Medical, Sales Drift) ──
        for disq in DISQUALIFYING_ROLE_KEYWORDS:
            if contains_word(disq, title):
                return MatchResult(
                    score=0,
                    decision="skip",
                    reasons=[f"Disqualified: Title matched negative role keyword ('{disq}')."],
                    red_flags=[f"Negative role keyword: {disq}"],
                    missing_skills=[],
                    matched_skills=[],
                    min_years_required=0,
                    max_years_required=0,
                    auto_submit_safe=False,
                )

        description = normalize_key(job.description)
        combined = " ".join(
            [
                title,
                description,
                normalize_key(job.criteria_text),
                normalize_key(job.location),
                normalize_key(job.experience),
                " ".join(normalize_key(skill) for skill in job.skills),
            ]
        )

        score = 0
        reasons: list[str] = []
        red_flags: list[str] = []

        profile_signals = normalize_key(
            " ".join(
                [
                    self.profile.summary,
                    self.profile.resume_text,
                    " ".join(self.profile.target_roles),
                    " ".join(self.profile.skills),
                    " ".join(self.profile.derived_skills),
                ]
            )
        )

        target_keywords = TARGET_ROLE_KEYWORDS.union(set(map(normalize_key, self.profile.target_roles)))
        title_hits = [keyword for keyword in target_keywords if contains_word(keyword, title)]
        relevance_hits = [keyword for keyword in target_keywords if contains_word(keyword, combined)]
        grouped_role_hits = [
            label
            for label, aliases in ROLE_SIGNAL_GROUPS.items()
            if any(alias in combined for alias in aliases) and any(alias in profile_signals for alias in aliases)
        ]
        technical_support_fallback = self._is_technical_support_fallback(combined)

        if title_hits:
            score += 35
            reasons.append("Job title directly matches target technical / engineering roles.")
        elif relevance_hits or grouped_role_hits:
            score += 25
            reasons.append("Role matches target technical / engineering roles.")
        elif any(contains_word(keyword, combined) for keyword in ("security", "soc", "grc", "vapt", "owasp", "siem", "appsec", "python", "developer", "backend", "software engineer")):
            score += 15
            reasons.append("Role appears adjacent to the target technical stack.")

        min_years, max_years = extract_years_range(f"{job.experience} {job.criteria_text} {job.description}")
        junior_markers = ("fresher", "junior", "entry level", "associate", "trainee", "intern")
        # Allow 0-3 years without ANY penalty — target range covers fresher to 3 years
        # Only penalise if the job EXPLICITLY requires more than 3 years minimum
        max_allowed_min = 3
        if min_years is not None and min_years > max_allowed_min:
            score -= 50
            red_flags.append(f"Requires {min_years}+ years minimum experience (our limit is {max_allowed_min} yrs).")
        elif max_years and max_years <= 3:
            score += 22
            reasons.append("Experience range fits 0-3 years profile.")
        elif any(word in combined for word in junior_markers):
            score += 20
            reasons.append("Job language indicates fresher or junior fit.")
            
        is_remote = "remote" in combined or "work from home" in combined
        pref_locs = [l.lower() for l in self.profile.preferred_locations]
        if not is_remote and pref_locs:
            matched_loc = any(l in normalize_key(job.location) for l in pref_locs)
            if not matched_loc:
                score -= 30
                red_flags.append("Location mismatch.")

        matched_skills = self._match_profile_skills(profile_signals, combined, job.skills)
        missing_skills = self._find_missing_job_skills(profile_signals, job.skills)
        skill_target = max(1, min(6, len(job.skills) or 4))
        score += min(25, round(25 * len(matched_skills) / skill_target))
        if matched_skills:
            reasons.append(f"Matched skills: {', '.join(matched_skills[:5])}.")
        elif any(keyword in profile_signals for keyword in ("cybersecurity", "vapt", "soc", "burp", "owasp")):
            reasons.append("Profile shows security background, but the post exposes few searchable skills.")

        normalized_location = normalize_key(job.location)
        preferred_locations = [normalize_key(item) for item in self.profile.preferred_locations]
        profile_location = normalize_key(self.profile.location)
        if "remote" in normalized_location or any(
            location and location in normalized_location
            for location in preferred_locations + [profile_location]
        ):
            score += 10
            reasons.append("Location is remote or aligned with preferred locations.")

        if not contains_any_keyword(domain_from_url(job.url), {"telegram", "whatsapp", "bit.ly"}):
            score += 10
            reasons.append("Application source looks legitimate.")
        else:
            red_flags.append("Suspicious short-link or messaging-based application source.")

        lowered_url = job.url.lower()
        if job.source == "linkedin" and "linkedin.com" in lowered_url and "/jobs/view/" not in lowered_url:
            score -= 35
            red_flags.append("LinkedIn URL is not a direct job-detail page.")
        if job.source == "naukri" and "naukri.com" in lowered_url and "job-listings-" not in lowered_url:
            score -= 35
            red_flags.append("Naukri URL is not a direct job-detail page.")

        if sum(keyword in combined for keyword in ("owasp", "api", "soc", "siem", "burp", "incident response")) >= 2:
            score += 10
            reasons.append("Role offers useful cybersecurity learning scope.")

        # Offensive Security Domain Weighting (+10 Boost)
        offensive_hits = [
            kw for kw in OFFENSIVE_SECURITY_KEYWORDS
            if contains_word(kw, title) or contains_word(kw, combined)
        ]
        if offensive_hits:
            score += 10
            reasons.append(f"Offensive Security domain boost (+10): matched {', '.join(offensive_hits[:3])}.")

        # Core Cybersecurity vs Generic Support Classification (75% Core Focus Quota Guard)
        is_core_cybersecurity = bool(
            title_hits
            or grouped_role_hits
            or offensive_hits
            or any(
                contains_word(kw, combined)
                for kw in (
                    "security",
                    "vapt",
                    "penetration",
                    "appsec",
                    "application security",
                    "soc",
                    "siem",
                    "cybersecurity",
                    "cyber security",
                    "information security",
                    "incident response",
                    "threat",
                    "grc",
                    "malware",
                    "network security",
                    "python",
                    "backend",
                    "software engineer",
                )
            )
        )

        if technical_support_fallback:
            if is_core_cybersecurity:
                score += 12
                reasons.append("Technical Support role with security focus kept as fallback option.")
            else:
                # Quota Guard: generic/adjacent IT support requires strict threshold >= 75
                if score < 75:
                    red_flags.append("Core Focus Quota Guard: Non-core IT support role score below 75 threshold (enforcing 75% core cybersecurity focus).")

        # Second-pass hard stop: 5+ years is an absolute disqualifier
        if max_years >= 5 or (min_years is not None and min_years >= 5):
            score -= 35
            red_flags.append("Mandatory experience appears to be 5+ years.")

        disallowed_hits = {keyword for keyword in DISALLOWED_JOB_KEYWORDS if contains_word(keyword, combined)}
        if technical_support_fallback:
            disallowed_hits -= {"support executive"}
        if disallowed_hits:
            score -= 40
            red_flags.append("Role looks unrelated, sales-focused, or non-technical support.")

        if contains_any_keyword(
            combined,
            {"backdoor experience", "fake experience", "proxy interview", "show experience", "fake documents"},
        ):
            score -= 100
            red_flags.append("Posting suggests fake experience or dishonest hiring flow.")

        if contains_any_keyword(combined, SENSITIVE_DATA_KEYWORDS):
            score -= 50
            red_flags.append("Posting requests suspicious sensitive data too early.")

        if technical_support_fallback and not any(
            fatal in " ".join(red_flags).lower()
            for fatal in ("5+ years", "suspicious", "fake experience", "sensitive data", "non-technical support", "quota guard")
        ):
            if is_core_cybersecurity:
                score = max(score, 45)
                if not (title_hits or relevance_hits or grouped_role_hits):
                    score = min(score, 49)

        score = max(0, min(100, score))

        if score >= 80:
            decision = "strong apply"
        elif score >= 65:
            decision = "apply after review"
        elif score >= 50:
            decision = "save only / ask user"
        elif technical_support_fallback and is_core_cybersecurity and score >= 40:
            decision = TECHNICAL_SUPPORT_FALLBACK_DECISION
        else:
            decision = "skip"

        # Automated Quota Allocation Guard: generic IT support strictly skipped if score < 75
        if technical_support_fallback and not is_core_cybersecurity and score < 75:
            decision = "skip"

        auto_submit_safe = (
            score >= 80
            and max_years <= 3
            and not any("suspicious" in flag.lower() for flag in red_flags)
            and not any("fake experience" in flag.lower() for flag in red_flags)
            and (is_core_cybersecurity or score >= 85)
        )

        return MatchResult(
            score=score,
            decision=decision,
            reasons=reasons,
            red_flags=red_flags,
            missing_skills=missing_skills,
            matched_skills=matched_skills,
            min_years_required=min_years,
            max_years_required=max_years,
            auto_submit_safe=auto_submit_safe,
        )

    @staticmethod
    def _is_technical_support_fallback(combined: str) -> bool:
        if contains_any_keyword(combined, NON_TECHNICAL_SUPPORT_KEYWORDS):
            return False
        return contains_any_keyword(combined, TECHNICAL_SUPPORT_KEYWORDS)

    def _match_profile_skills(self, profile_signals: str, combined: str, job_skills: list[str]) -> list[str]:
        matched: list[str] = []
        job_skill_text = " ".join(normalize_key(skill) for skill in job_skills)

        for label, aliases in SKILL_SIGNAL_GROUPS.items():
            if any(alias in profile_signals for alias in aliases) and any(
                alias in combined or alias in job_skill_text for alias in aliases
            ):
                matched.append(label)

        explicit_profile_skills = unique_list(self.profile.skills + self.profile.derived_skills)
        for skill in explicit_profile_skills:
            normalized = normalize_key(skill)
            if normalized and (normalized in combined or normalized in job_skill_text):
                matched.append(skill)

        return unique_list(matched)

    def _find_missing_job_skills(self, profile_signals: str, job_skills: list[str]) -> list[str]:
        missing: list[str] = []
        for skill in unique_list(job_skills):
            normalized = normalize_key(skill)
            if not normalized:
                continue
            aliases = self._aliases_for_skill(normalized)
            if any(alias in profile_signals for alias in aliases):
                continue
            missing.append(skill)
        return unique_list(missing)

    @staticmethod
    def _aliases_for_skill(skill: str) -> set[str]:
        for aliases in SKILL_SIGNAL_GROUPS.values():
            if skill in aliases:
                return aliases
        return {skill}
