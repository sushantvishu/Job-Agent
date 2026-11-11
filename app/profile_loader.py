from __future__ import annotations

import os
import re
from pathlib import Path
from zipfile import ZipFile

from app.utils import (
    ProfileData,
    extract_skills_from_text,
    fuzzy_match_key,
    load_json,
    normalize_key,
    save_json,
    unique_list,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def list_available_profiles() -> list[str]:
    """Scan and list all configured persona profiles."""
    profiles = ["default"]
    profiles_dir = PROJECT_ROOT / "profiles"
    if profiles_dir.exists():
        for entry in sorted(profiles_dir.iterdir()):
            if entry.is_dir() and (entry / "profile.json").exists():
                profiles.append(entry.name)
    return profiles


def resolve_profile_path(profile_path_or_name: Path | str | None = None) -> Path:
    """Resolve a profile path or profile name (e.g. 'vapt', 'soc') to its JSON file path."""
    if profile_path_or_name is None:
        env_profile = os.getenv("JOB_AGENT_PROFILE")
        if env_profile:
            profile_path_or_name = env_profile
        else:
            return PROJECT_ROOT / "profile" / "profile.json"

    if isinstance(profile_path_or_name, str):
        if profile_path_or_name.endswith(".json"):
            resolved = Path(profile_path_or_name)
            return resolved if resolved.is_absolute() else PROJECT_ROOT / resolved
        # Name-based lookup
        candidate = PROJECT_ROOT / "profiles" / profile_path_or_name / "profile.json"
        if candidate.exists():
            return candidate
        default_candidate = PROJECT_ROOT / "profile" / "profile.json"
        if default_candidate.exists():
            return default_candidate
        return candidate

    return profile_path_or_name


def load_resume_text(profile_path: Path) -> str:
    profile_dir = profile_path.parent
    docx_path = profile_dir / "resume.docx"
    if docx_path.exists():
        try:
            with ZipFile(docx_path) as archive:
                data = archive.read("word/document.xml").decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", data)
            return re.sub(r"\s+", " ", text).strip()
        except Exception:  # noqa: BLE001
            return ""

    for fallback_name in ("resume.txt", "resume.md"):
        text_path = profile_dir / fallback_name
        if text_path.exists():
            try:
                return text_path.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                return ""

    return ""


def load_profile(profile_path: Path | str | None = None) -> ProfileData:
    resolved_path = resolve_profile_path(profile_path)
    payload = load_json(resolved_path)
    if not payload:
        raise FileNotFoundError(
            f"Profile not found at {resolved_path}. Update profile/profile.json before running the agent."
        )
    profile = ProfileData.model_validate(payload)
    resume_text = load_resume_text(resolved_path)
    derived_skills = extract_skills_from_text(resume_text)
    profile.resume_text = resume_text[:20000]
    profile.derived_skills = derived_skills
    profile.skills = unique_list(profile.skills + derived_skills)
    return profile


def load_answer_templates(path: Path) -> dict:
    payload = load_json(path, default={"custom_answers": {}, "templates": {}})
    payload.setdefault("custom_answers", {})
    payload.setdefault("templates", {})
    return payload


def save_answer_templates(path: Path, templates: dict) -> None:
    save_json(path, templates)


def lookup_saved_answer(label: str, templates: dict, profile: ProfileData) -> str | None:
    normalized = normalize_key(label)
    for key, value in profile.custom_answers.items():
        if normalize_key(key) == normalized:
            return value
    for key, value in templates.get("custom_answers", {}).items():
        if normalize_key(key) == normalized:
            return value
    return None


def lookup_saved_answer_fuzzy(label: str, templates: dict, profile: ProfileData) -> tuple[str, str] | None:
    """Returns (answer, matched_question_key) or None. profile.json takes precedence, mirroring lookup_saved_answer's order."""
    normalized_label = normalize_key(label)
    profile_keys = {normalize_key(k): v for k, v in profile.custom_answers.items()}
    template_keys = {normalize_key(k): v for k, v in templates.get("custom_answers", {}).items()}
    for source in (profile_keys, template_keys):
        match = fuzzy_match_key(normalized_label, list(source.keys()))
        if match:
            return source[match], match
    return None
