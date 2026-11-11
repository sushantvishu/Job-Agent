from __future__ import annotations

import csv
from pathlib import Path

from app.utils import safe_timestamp


class Exporter:
    def __init__(self, exports_dir: Path, logger) -> None:
        self.exports_dir = exports_dir
        self.logger = logger

    def export_jobs(self, rows: list[dict]) -> Path:
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.exports_dir / f"jobs_export_{safe_timestamp()}.csv"
        fieldnames = [
            "id",
            "source",
            "company",
            "title",
            "url",
            "score",
            "status",
            "reason",
            "criteria_text",
            "expansion_audit",
            "red_flags",
            "missing_skills",
            "applied_at",
            "notes",
            "created_at",
        ]
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        self.logger.info("Exported %s jobs to %s", len(rows), output_path)
        return output_path
