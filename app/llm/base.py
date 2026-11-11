from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.utils import JobPosting, ProfileData


class LLMProvider(ABC):
    """Abstract interface for all LLM inference backends (Ollama, Gemini, OpenAI, Groq)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend model provider is reachable."""
        ...

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None) -> str:
        """Generate raw text response from a prompt and optional system prompt."""
        ...

    @abstractmethod
    def answer_question(self, job: JobPosting, profile: ProfileData, question: str) -> str:
        """Answer a job application form question using candidate background."""
        ...

    @abstractmethod
    def generate_application_material(self, job: JobPosting, profile: ProfileData) -> dict[str, Any]:
        """Generate cover letter and experience summary customized for the role."""
        ...
