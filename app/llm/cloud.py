from __future__ import annotations

import json
import logging
from typing import Any
import requests

from app.llm.base import LLMProvider
from app.utils import JobPosting, ProfileData


class OpenAICompatibleProvider(LLMProvider):
    """Cloud LLM provider utilizing OpenAI-compatible chat completion endpoints (Gemini, Groq, OpenAI)."""

    def __init__(
        self,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
        api_key: str = "",
        model: str = "gemini-2.0-flash",
        logger: logging.Logger | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.logger = logger or logging.getLogger("llm.cloud")
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, system: str | None = None) -> str:
        if not self.api_key:
            return ""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            self.logger.warning("Cloud LLM response %s: %s", resp.status_code, resp.text[:200])
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Cloud LLM request failed: %s", exc)
        return ""

    def answer_question(self, job: JobPosting, profile: ProfileData, question: str) -> str:
        prompt = (
            f"Candidate: {profile.name}, Experience: {profile.experience_years} years, "
            f"Skills: {', '.join(profile.skills[:10])}. Job: {job.title} at {job.company}.\n"
            f"Question: {question}\n"
            f"Provide a concise, direct answer in 1-2 sentences:"
        )
        return self.generate(prompt)

    def generate_application_material(self, job: JobPosting, profile: ProfileData) -> dict[str, Any]:
        prompt = (
            f"Candidate: {profile.name}, Skills: {', '.join(profile.skills[:10])}\n"
            f"Job: {job.title} at {job.company}\n"
            f"Generate a professional, short cover letter (100 words) and 3 bullet points."
        )
        ans = self.generate(prompt)
        return {
            "cover_letter": ans,
            "experience_summary": f"Hands-on experience in {', '.join(profile.skills[:4])}",
            "used_fallback": False,
        }
