"""notifier.py — Summary report writer for autorun pipeline runs.

No external dependencies. Writes a markdown summary of a completed autorun
cycle to exports/autorun_summary_<timestamp>.md and logs the path.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def write_autorun_summary(
    output_dir: Path,
    scouted: int,
    shortlisted: int,
    filled: list[dict[str, Any]],
    needs_manual: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    logger=None,
) -> Path:
    """Write a markdown summary of an autorun cycle and return the output path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"autorun_summary_{timestamp}.md"

    lines: list[str] = [
        "# Autorun Summary",
        "",
        f"**Run time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Jobs scouted / inspected:** {scouted}",
        f"**Jobs shortlisted:** {shortlisted}",
        f"**Forms filled (pending your review + submit):** {len(filled)}",
        f"**Needs manual input (CAPTCHA / OTP / unknown field):** {len(needs_manual)}",
        f"**Failed:** {len(failed)}",
        "",
    ]

    if filled:
        lines += [
            "## Filled — open browser and submit when ready",
            "",
            "| # | Title | Company | Source | Score | URL |",
            "|---|-------|---------|--------|-------|-----|",
        ]
        for i, row in enumerate(filled, start=1):
            title = _safe(row.get("title"))
            company = _safe(row.get("company"))
            source = _safe(row.get("source"))
            score = str(row.get("score") or "")
            url = _safe(row.get("url"))
            url_cell = f"[link]({url})" if url else ""
            lines.append(f"| {i} | {title} | {company} | {source} | {score} | {url_cell} |")
        lines.append("")

    if needs_manual:
        lines += [
            "## Needs manual input",
            "",
            "These jobs were blocked by a CAPTCHA, OTP, login gate, or an unknown form field.",
            "Re-run `python app/main.py resume-manual` to attempt them again after you handle the blocker in the browser.",
            "",
            "| # | Title | Company | Reason | URL |",
            "|---|-------|---------|--------|-----|",
        ]
        for i, row in enumerate(needs_manual, start=1):
            title = _safe(row.get("title"))
            company = _safe(row.get("company"))
            reason = _safe(row.get("reason"))
            url = _safe(row.get("url"))
            url_cell = f"[link]({url})" if url else ""
            lines.append(f"| {i} | {title} | {company} | {reason} | {url_cell} |")
        lines.append("")

    if failed:
        lines += [
            "## Failed",
            "",
            "| # | Title | Company | Reason | URL |",
            "|---|-------|---------|--------|-----|",
        ]
        for i, row in enumerate(failed, start=1):
            title = _safe(row.get("title"))
            company = _safe(row.get("company"))
            reason = _safe(row.get("reason"))
            url = _safe(row.get("url"))
            url_cell = f"[link]({url})" if url else ""
            lines.append(f"| {i} | {title} | {company} | {reason} | {url_cell} |")
        lines.append("")

    lines += [
        "---",
        "",
        "**Next steps:**",
        "1. Open Chrome: `python app/main.py open`",
        "2. Go to each filled job URL above and click Submit.",
        "3. After submitting, mark it done: `python app/main.py mark-applied --url <url>`",
        "4. Check follow-up emails: `python app/main.py check-followups --days 30`",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    if logger:
        logger.info("Autorun summary written: %s", path)
    return path


def _safe(value: Any) -> str:
    return str(value or "").replace("|", "\\|").strip()

