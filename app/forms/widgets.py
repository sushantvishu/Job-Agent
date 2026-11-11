"""
app/forms/widgets.py — Strategy Pattern Hierarchy for Form Input Widgets.

Encapsulates element interaction, DOM event dispatch, and option matching
for diverse web form controls (native selects, ARIA listboxes, radio groups, numbers).
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from playwright.sync_api import Locator, Page

from app.utils import FillResult, compact_whitespace, normalize_key

logger = logging.getLogger("forms.widgets")


class BaseWidget(ABC):
    """Abstract Strategy for interacting with specific DOM form control types."""

    @abstractmethod
    def can_handle(self, field: dict[str, Any]) -> bool:
        """Return True if this widget strategy can interact with the given field metadata."""
        ...

    @abstractmethod
    def fill(
        self,
        locator: Locator,
        field: dict[str, Any],
        answer: str,
        label: str,
        result: FillResult,
        page: Page | None = None,
    ) -> bool:
        """Fill or select the control with the given answer value. Returns True on success."""
        ...


class NumberInputWidget(BaseWidget):
    """Interacts with input[type='number'] fields, extracting pure digits/floats."""

    def can_handle(self, field: dict[str, Any]) -> bool:
        return field.get("type") == "number"

    def fill(
        self,
        locator: Locator,
        field: dict[str, Any],
        answer: str,
        label: str,
        result: FillResult,
        page: Page | None = None,
    ) -> bool:
        numeric = self._extract_numeric(answer)
        if numeric:
            locator.fill(numeric, timeout=8000)
            result.filled_fields.append(label)
            logger.info("NumberWidget: filled %s -> %s", label, numeric)
            return True
        logger.warning("NumberWidget: could not extract number from '%s' for %s", answer, label)
        return False

    @staticmethod
    def _extract_numeric(answer: str) -> str:
        stripped = str(answer).strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
            return stripped
        lower = stripped.lower()
        if any(k in lower for k in ("immediate", "immediately", "fresher", "currently 0", "0 lpa")) or re.search(r"\b0\s*days?\b", lower):
            return "0"
        m = re.search(r"\b(\d+(?:\.\d+)?)\b", stripped)
        return m.group(1) if m else ""


class CheckboxWidget(BaseWidget):
    """Interacts with checkbox inputs (consent, privacy, declarations)."""

    def can_handle(self, field: dict[str, Any]) -> bool:
        return field.get("type") == "checkbox"

    def fill(
        self,
        locator: Locator,
        field: dict[str, Any],
        answer: str,
        label: str,
        result: FillResult,
        page: Page | None = None,
    ) -> bool:
        try:
            locator.check(force=True, timeout=5000)
            result.filled_fields.append(label)
            logger.info("CheckboxWidget: checked %s", label)
            return True
        except Exception as exc:
            result.errors.append(f"{label}: {exc}")
            return False


class TextInputWidget(BaseWidget):
    """Interacts with text, email, tel, url, and textarea inputs."""

    def can_handle(self, field: dict[str, Any]) -> bool:
        return field.get("tag") in ("textarea",) or field.get("type") in (
            "text", "email", "tel", "url", "password"
        )

    def fill(
        self,
        locator: Locator,
        field: dict[str, Any],
        answer: str,
        label: str,
        result: FillResult,
        page: Page | None = None,
    ) -> bool:
        try:
            locator.fill(str(answer), timeout=8000)
            result.filled_fields.append(label)
            display = str(answer)[:30] + "..." if len(str(answer)) > 30 else str(answer)
            logger.info("TextInputWidget: filled %s -> %s", label, display)
            return True
        except Exception as exc:
            result.errors.append(f"{label}: {exc}")
            return False


class SelectWidget(BaseWidget):
    """Interacts with standard HTML <select> dropdowns."""

    def can_handle(self, field: dict[str, Any]) -> bool:
        return field.get("tag") == "select"

    def fill(
        self,
        locator: Locator,
        field: dict[str, Any],
        answer: str,
        label: str,
        result: FillResult,
        page: Page | None = None,
    ) -> bool:
        options = field.get("options", [])
        norm_answer = normalize_key(str(answer))
        
        # 1. Exact value or text match
        for opt in options:
            if norm_answer == normalize_key(opt.get("text", "")) or norm_answer == normalize_key(opt.get("value", "")):
                try:
                    locator.select_option(value=opt.get("value"))
                    result.filled_fields.append(label)
                    logger.info("SelectWidget: matched %s -> %s", label, opt.get("text"))
                    return True
                except Exception:
                    pass

        # 2. Substring match
        for opt in options:
            opt_text = normalize_key(opt.get("text", ""))
            if norm_answer in opt_text or opt_text in norm_answer:
                try:
                    locator.select_option(value=opt.get("value"))
                    result.filled_fields.append(label)
                    logger.info("SelectWidget: fuzzy matched %s -> %s", label, opt.get("text"))
                    return True
                except Exception:
                    pass

        # Fallback to first non-empty option if required
        if field.get("required") and options:
            first_valid = next((o for o in options if o.get("value")), options[0])
            try:
                locator.select_option(value=first_valid.get("value"))
                result.filled_fields.append(label)
                logger.info("SelectWidget: applied required fallback for %s -> %s", label, first_valid.get("text"))
                return True
            except Exception:
                pass

        return False
