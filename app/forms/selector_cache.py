from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.utils import normalize_key

logger = logging.getLogger("selector_cache")

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "templates" / "selector_cache.json"


class SelectorCache:
    """
    Self-healing selector cache for DOM form elements across ATS and corporate career sites.
    Maps: domain -> normalized_question_key -> { selector: str, hits: int, last_used: str }
    """

    def __init__(self, cache_path: Path | None = None) -> None:
        self.cache_path = cache_path or DEFAULT_CACHE_PATH
        self._cache: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("Could not read selector_cache.json: %s", exc)
                self._cache = {}
        else:
            self._cache = {}

    def save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Could not write selector_cache.json: %s", exc)

    def get_selector(self, domain: str, question: str) -> str | None:
        domain_key = normalize_key(domain)
        q_key = normalize_key(question)
        domain_cache = self._cache.get(domain_key, {})
        entry = domain_cache.get(q_key)
        if entry and isinstance(entry, dict):
            entry["hits"] = entry.get("hits", 0) + 1
            return entry.get("selector")
        return None

    def record_selector(self, domain: str, question: str, selector: str) -> None:
        if not domain or not question or not selector:
            return
        domain_key = normalize_key(domain)
        q_key = normalize_key(question)
        if domain_key not in self._cache:
            self._cache[domain_key] = {}

        self._cache[domain_key][q_key] = {
            "selector": selector,
            "hits": self._cache[domain_key].get(q_key, {}).get("hits", 0) + 1,
        }
        self.save()

    def clear(self) -> None:
        self._cache = {}
        self.save()
