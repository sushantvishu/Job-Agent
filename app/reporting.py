from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from app.apply_path import review_group_for_row
from app.browser import BrowserSession


def write_shortlist_report(rows: list[dict], output_dir: Path, timestamped: bool = True) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / (f"shortlist_{stamp}.csv" if timestamped else "shortlist_latest.csv")
    md_path = output_dir / "shortlist_latest.md"

    fieldnames = [
        "score",
        "decision",
        "status",
        "apply_path",
        "source",
        "company",
        "title",
        "location",
        "experience",
        "matched_skills",
        "red_flags",
        "skip_reason",
        "contact_methods",
        "expansion_audit",
        "criteria_excerpt",
        "possible_duplicate",
        "url",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})

    lines = ["# Latest Job Shortlist", ""]
    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"## {index}. {row['title'] or 'Unknown title'}",
                "",
                f"- Score: {row['score']} ({row['decision']})",
                f"- Status: {row['status']}",
                f"- Apply path: {row['apply_path']}",
                f"- Company: {row['company'] or 'Unknown'}",
                f"- Source: {row['source']}",
                f"- Location: {row['location'] or 'Unknown'}",
                f"- Experience: {row['experience'] or 'Unknown'}",
                f"- Matched skills: {row['matched_skills'] or '-'}",
                f"- Red flags: {row['red_flags'] or '-'}",
                f"- Skip reason: {row.get('skip_reason') or '-'}",
                f"- Contact methods: {row.get('contact_methods') or '-'}",
                f"- Expansion audit: {row.get('expansion_audit') or '-'}",
                f"- Criteria excerpt: {row.get('criteria_excerpt') or '-'}",
                f"- Possible duplicate: {row.get('possible_duplicate') or '-'}",
                f"- URL: {row['url']}",
                "",
            ]
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    write_review_shortlist_report(rows, output_dir)
    return csv_path, md_path


def write_review_shortlist_report(rows: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "shortlist_review_latest.md"
    shortlist_rows = [row for row in rows if row.get("status") == "shortlisted"]
    grouped: dict[str, list[dict]] = {}
    for row in shortlist_rows:
        grouped.setdefault(review_group_for_row(row), []).append(row)

    group_order = [
        "LinkedIn Easy Apply",
        "Apply On Company Website",
        "Direct Apply",
        "Manual Review",
        "Technical Support Fallback",
    ]
    lines = ["# Review Shortlist", ""]
    if not shortlist_rows:
        lines.append("No shortlisted jobs yet.")
    for group in group_order:
        items = sorted(grouped.get(group, []), key=lambda item: int(item.get("score") or 0), reverse=True)
        if not items:
            continue
        lines.extend([f"## {group}", ""])
        for index, row in enumerate(items, start=1):
            lines.extend(
                [
                    f"{index}. {row.get('title') or 'Unknown title'}",
                    f"   - Company: {row.get('company') or 'Unknown'}",
                    f"   - Score: {row.get('score') or 0}",
                    f"   - Source: {row.get('source') or '-'}",
                    f"   - Experience: {row.get('experience') or 'Unknown'}",
                    f"   - Matched skills: {row.get('matched_skills') or '-'}",
                    f"   - Contact methods: {row.get('contact_methods') or '-'}",
                    f"   - URL: {row.get('url') or '-'}",
                    "",
                ]
            )
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def save_live_shortlist(rows: list[dict], output_dir: Path) -> None:
    ordered = sorted(rows, key=lambda item: int(item.get("score") or 0), reverse=True)
    write_shortlist_report(ordered, output_dir, timestamped=False)


def note_noise_link_once(output_dir: Path, url: str, source: str, reason: str, job_url: str = "") -> None:
    if not url:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "noise_links_review_latest.md"
    key = BrowserSession.normalized_url_key(url)
    existing = output.read_text(encoding="utf-8") if output.exists() else "# Noise Links For Review\n\n"
    if key and key in existing:
        return
    lines = [
        existing.rstrip(),
        "",
        f"## {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- URL: {url}",
        f"- Normalized key: {key or '-'}",
        f"- Source: {source or '-'}",
        f"- Reason: {reason or '-'}",
    ]
    if job_url:
        lines.append(f"- Seen while checking: {job_url}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
