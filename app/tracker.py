from __future__ import annotations

import sqlite3
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.utils import JobPosting, MatchResult
from app.utils import detect_source_from_url, fuzzy_match_key, normalize_key


class JobTracker:
    def __init__(self, db_path: Path, logger: Any = None) -> None:
        self.db_path = db_path
        self.logger = logger or logging.getLogger("tracker")
        self._handled_cache: dict[str, dict[str, Any]] | None = None
        self._applied_cache: list[dict[str, Any]] | None = None
        self._checked_search_pages: set[tuple[str, str, str]] | None = None

    def warm_cache(self, limit: int = 1500) -> None:
        """Pre-warm in-memory sets with recent jobs for instant O(1) deduplication without excessive RAM usage."""
        self._handled_cache = {}
        self._applied_cache = []
        self._checked_search_pages = set()
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT id, source, company, title, url, canonical_key, score, status, reason, applied_at, location
                    FROM jobs
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    if d.get("url"):
                        self._handled_cache[d["url"]] = d
                    if d.get("canonical_key"):
                        self._handled_cache[d["canonical_key"]] = d
                    if d.get("status") == "applied":
                        self._applied_cache.append(d)

                page_rows = connection.execute(
                    """
                    SELECT source, search_key, page_key
                    FROM search_page_log
                    WHERE status = 'checked'
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit * 2,),
                ).fetchall()
                for pr in page_rows:
                    self._checked_search_pages.add((pr["source"], pr["search_key"], pr["page_key"]))
            self.logger.info(
                "Tracker cache warmed (bounded): %d jobs, %d applied, %d search pages cached in RAM",
                len(self._handled_cache),
                len(self._applied_cache),
                len(self._checked_search_pages),
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Tracker warm_cache warning: %s", exc)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 30000")
        except Exception:
            pass
        return connection

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from app.migrations import MigrationRunner
            project_root = Path(__file__).resolve().parent.parent
            migrations_dir = project_root / "migrations"
            MigrationRunner(self.db_path, migrations_dir=migrations_dir if migrations_dir.exists() else None).run_migrations()
        except Exception as exc:
            self.logger.debug("MigrationRunner notice: %s", exc)

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    company TEXT,
                    title TEXT,
                    url TEXT NOT NULL UNIQUE,
                    canonical_key TEXT,
                    score INTEGER,
                    status TEXT NOT NULL,
                    reason TEXT,
                    criteria_text TEXT,
                    expansion_audit TEXT,
                    red_flags TEXT,
                    missing_skills TEXT,
                    applied_at TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
            if "canonical_key" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN canonical_key TEXT")
            if "criteria_text" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN criteria_text TEXT")
            if "expansion_audit" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN expansion_audit TEXT")
            if "location" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN location TEXT")
                connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_location ON jobs(location)")
            rows = connection.execute("SELECT id, source, company, title, url FROM jobs WHERE canonical_key IS NULL OR canonical_key = ''").fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE jobs SET canonical_key = ? WHERE id = ?",
                    (
                        self.canonical_key(
                            source=row["source"],
                            url=row["url"],
                            company=row["company"] or "",
                            title=row["title"] or "",
                        ),
                        row["id"],
                    ),
                )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_canonical_key ON jobs(canonical_key)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source_status ON jobs(source, status)")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS search_company_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    search_key TEXT NOT NULL,
                    company_key TEXT NOT NULL,
                    company TEXT,
                    title TEXT,
                    url TEXT,
                    status TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(source, search_key, company_key)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_search_company_log_lookup "
                "ON search_company_log(source, search_key, company_key)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS search_page_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    search_key TEXT NOT NULL,
                    page_key TEXT NOT NULL,
                    page_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    candidates_found INTEGER NOT NULL DEFAULT 0,
                    selected_count INTEGER NOT NULL DEFAULT 0,
                    skipped_seen_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(source, search_key, page_key)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_search_page_log_lookup "
                "ON search_page_log(source, search_key, page_key, status)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS interviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    company TEXT NOT NULL,
                    role TEXT,
                    intent TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'needs_action',
                    recruiter_name TEXT,
                    recruiter_email TEXT,
                    meeting_link TEXT,
                    assessment_link TEXT,
                    deadline_or_time TEXT,
                    raw_snippet TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_interviews_company ON interviews(company)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_interviews_intent ON interviews(intent)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_interviews_status ON interviews(status)")
            connection.commit()
        self.logger.info("Initialized SQLite tracker at %s", self.db_path)

    @staticmethod
    def canonical_key(source: str, url: str, company: str = "", title: str = "", location: str = "") -> str:
        parsed = urlparse(url)
        lowered_url = unquote(url).lower()
        resolved_source = source if source and source != "unknown" else detect_source_from_url(url)

        linkedin_match = re.search(r"/jobs/view/(\d+)", lowered_url)
        if linkedin_match:
            return f"linkedin:{linkedin_match.group(1)}"

        query = parse_qs(parsed.query)
        if "linkedin.com" in lowered_url:
            for key in ("currentJobId", "jobId", "referenceJobId"):
                job_id = query.get(key, [""])[0]
                if job_id and job_id.isdigit():
                    return f"linkedin:{job_id}"

        naukri_match = re.search(r"job-listings-[^?#]*-(\d{8,})", lowered_url)
        if naukri_match:
            return f"naukri:{naukri_match.group(1)}"

        file_id = query.get("file", [""])[0]
        if "naukri.com" in lowered_url and file_id:
            return f"naukri:{file_id}"

        compact_company = normalize_key(company)
        compact_title = normalize_key(title)
        compact_location = normalize_key(location)
        if compact_company and compact_title and compact_location:
            return f"{resolved_source}:{compact_company}:{compact_title}:{compact_location}"
        if compact_company and compact_title:
            return f"{resolved_source}:{compact_company}:{compact_title}"

        normalized_path = normalize_key(f"{parsed.netloc} {parsed.path}")
        return f"{resolved_source}:{normalized_path or normalize_key(url)}"

    def find_existing(self, job: JobPosting) -> dict[str, Any] | None:
        key = self.canonical_key(job.source, job.url, job.company, job.title, job.location)
        if self._handled_cache is not None:
            if job.url and job.url in self._handled_cache:
                return self._handled_cache[job.url]
            if key and key in self._handled_cache:
                return self._handled_cache[key]
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, source, company, title, url, canonical_key, score, status, reason, applied_at, location
                FROM jobs
                WHERE url = ? OR canonical_key = ?
                ORDER BY
                    CASE status
                        WHEN 'applied' THEN 0
                        WHEN 'filled_pending_submit' THEN 1
                        WHEN 'needs_manual_input' THEN 2
                        ELSE 3
                    END,
                    id DESC
                LIMIT 1
                """,
                (job.url, key),
            ).fetchone()
        res = dict(row) if row else None
        if res and self._handled_cache is not None:
            if job.url:
                self._handled_cache[job.url] = res
            if key:
                self._handled_cache[key] = res
        return res

    def is_already_applied(self, job: JobPosting, recency_days: int = 14) -> dict[str, Any] | None:
        existing = self.find_existing(job)
        if not existing or existing.get("status") != "applied":
            return None

        # Multi-location check: if existing location and new location are different,
        # it is an independent requisition in another location — allow applying!
        existing_loc = normalize_key(existing.get("location") or "")
        current_loc = normalize_key(job.location or "")
        if existing_loc and current_loc and existing_loc != current_loc:
            self.logger.info(
                "Different location detected for %s at %s (applied=%s, new=%s) — eligible to apply.",
                job.title, job.company, existing_loc, current_loc
            )
            return None

        # Rolling 14-day recency window: if applied > 14 days ago, allow re-application
        applied_at = existing.get("applied_at")
        if applied_at:
            try:
                applied_dt = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
                if applied_dt.tzinfo is not None:
                    applied_dt = applied_dt.replace(tzinfo=None)
                days_since = (datetime.now() - applied_dt).days
                if days_since > recency_days:
                    self.logger.info(
                        "Application for %s at %s was %d days ago (>%d days) — eligible for re-application.",
                        job.title, job.company, days_since, recency_days
                    )
                    return None
            except Exception:
                pass

        return existing

    def find_possible_duplicate_applied(
        self, company: str, title: str, location: str = "", recency_days: int = 14
    ) -> dict[str, Any] | None:
        """Non-blocking near-duplicate check against already-applied jobs:
        Checks exact-normalized company + fuzzy title + location + 14-day recency window.
        If location is different, it is NOT considered a duplicate.
        If older than 14 days, it is NOT considered a duplicate.
        """
        normalized_company = normalize_key(company)
        normalized_title = normalize_key(title)
        normalized_location = normalize_key(location)
        if not normalized_company or not normalized_title:
            return None
        if self._applied_cache is not None:
            rows = self._applied_cache
        else:
            with self._connect() as connection:
                raw_rows = connection.execute(
                    "SELECT company, title, url, applied_at, location FROM jobs WHERE status = 'applied'"
                ).fetchall()
                rows = [dict(r) for r in raw_rows]
                self._applied_cache = rows
        same_company = [row for row in rows if normalize_key(row["company"] or "") == normalized_company]
        if not same_company:
            return None

        # If location is provided, only match if same location (allow different locations!)
        if normalized_location:
            same_loc = [row for row in same_company if normalize_key(row["location"] or "") == normalized_location]
            if not same_loc:
                return None
            same_company = same_loc

        # Filter by 14-day rolling recency window
        recent_matches = []
        now_dt = datetime.now()
        for row in same_company:
            applied_at = row["applied_at"]
            if applied_at:
                try:
                    applied_dt = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
                    if applied_dt.tzinfo is not None:
                        applied_dt = applied_dt.replace(tzinfo=None)
                    if (now_dt - applied_dt).days <= recency_days:
                        recent_matches.append(row)
                except Exception:
                    recent_matches.append(row)
            else:
                recent_matches.append(row)

        if not recent_matches:
            return None

        title_map = {normalize_key(row["title"] or ""): row for row in recent_matches}
        matched_key = fuzzy_match_key(normalized_title, list(title_map.keys()))
        if matched_key is None:
            return None
        return dict(title_map[matched_key])

    def find_handled_job(self, job: JobPosting) -> dict[str, Any] | None:
        existing = self.find_existing(job)
        if existing and existing["status"] in {
            "applied",
            "discovered",
            "failed",
            "filled_pending_submit",
            "needs_manual_input",
            "shortlisted",
            "skipped",
            "skipped_seen_company",
        }:
            return existing
        return None

    def has_seen_company_for_source(self, source: str, company: str) -> bool:
        company_key = normalize_key(company)
        if not source or not company_key:
            return False
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM search_company_log
                WHERE source = ? AND company_key = ?
                LIMIT 1
                """,
                (source, company_key),
            ).fetchone()
        return row is not None

    def has_seen_company_for_search(self, source: str, search_key: str, company: str) -> bool:
        company_key = normalize_key(company)
        if not source or not search_key or not company_key:
            return False
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM search_company_log
                WHERE source = ? AND search_key = ? AND company_key = ?
                LIMIT 1
                """,
                (source, search_key, company_key),
            ).fetchone()
        return row is not None

    def mark_company_seen_for_search(
        self,
        source: str,
        search_key: str,
        company: str,
        title: str = "",
        url: str = "",
        status: str = "",
    ) -> None:
        company_key = normalize_key(company)
        if not source or not search_key or not company_key:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO search_company_log (
                    source, search_key, company_key, company, title, url, status,
                    first_seen_at, last_seen_at, seen_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), 1)
                ON CONFLICT(source, search_key, company_key) DO UPDATE SET
                    company=excluded.company,
                    title=CASE WHEN excluded.title <> '' THEN excluded.title ELSE search_company_log.title END,
                    url=CASE WHEN excluded.url <> '' THEN excluded.url ELSE search_company_log.url END,
                    status=CASE WHEN excluded.status <> '' THEN excluded.status ELSE search_company_log.status END,
                    last_seen_at=datetime('now'),
                    seen_count=search_company_log.seen_count + 1
                """,
                (source, search_key, company_key, company, title, url, status),
            )
            connection.commit()

    def list_seen_companies(self, source: str | None = None, search_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = (
            "SELECT source, search_key, company, title, url, status, seen_count, first_seen_at, last_seen_at "
            "FROM search_company_log"
        )
        params: list[Any] = []
        filters: list[str] = []
        if source:
            filters.append("source = ?")
            params.append(source)
        if search_key:
            filters.append("search_key = ?")
            params.append(search_key)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY last_seen_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def search_page_key(page_url: str) -> str:
        parsed = urlparse(page_url)
        query = parse_qs(parsed.query)
        keep_query: list[str] = []
        for key in sorted(query):
            if key.lower() in {"trackingid", "origin", "refid", "trk", "position", "pagenum", "currentjobid", "refresh"}:
                continue
            values = ",".join(sorted(value for value in query[key] if value))
            keep_query.append(f"{key}={values}")
        normalized = normalize_key(f"{parsed.netloc} {parsed.path} {' '.join(keep_query)}")
        return normalized or normalize_key(page_url)

    def has_checked_search_page(self, source: str, search_key: str, page_url: str) -> bool:
        if not source or not search_key or not page_url:
            return False
        page_key = self.search_page_key(page_url)
        if self._checked_search_pages is not None:
            return (source, search_key, page_key) in self._checked_search_pages
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM search_page_log
                WHERE source = ? AND search_key = ? AND page_key = ? AND status = 'checked'
                LIMIT 1
                """,
                (source, search_key, page_key),
            ).fetchone()
        return row is not None

    def mark_search_page(
        self,
        source: str,
        search_key: str,
        page_url: str,
        status: str,
        candidates_found: int = 0,
        selected_count: int = 0,
        skipped_seen_count: int = 0,
    ) -> None:
        if not source or not search_key or not page_url:
            return
        page_key = self.search_page_key(page_url)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO search_page_log (
                    source, search_key, page_key, page_url, status, candidates_found,
                    selected_count, skipped_seen_count, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(source, search_key, page_key) DO UPDATE SET
                    page_url=excluded.page_url,
                    status=excluded.status,
                    candidates_found=excluded.candidates_found,
                    selected_count=excluded.selected_count,
                    skipped_seen_count=excluded.skipped_seen_count,
                    last_seen_at=datetime('now')
                """,
                (
                    source,
                    search_key,
                    page_key,
                    page_url,
                    status,
                    candidates_found,
                    selected_count,
                    skipped_seen_count,
                ),
            )
            connection.commit()
        if self._checked_search_pages is not None and status == "checked":
            self._checked_search_pages.add((source, search_key, page_key))

    def list_seen_pages(self, source: str | None = None, search_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = (
            "SELECT source, search_key, status, candidates_found, selected_count, skipped_seen_count, page_url, last_seen_at "
            "FROM search_page_log"
        )
        params: list[Any] = []
        filters: list[str] = []
        if source:
            filters.append("source = ?")
            params.append(source)
        if search_key:
            filters.append("search_key = ?")
            params.append(search_key)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY last_seen_at DESC LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_seen_search_keys(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT DISTINCT search_key FROM search_page_log").fetchall()
        return {row[0] for row in rows if row[0]}

    def upsert_job(
        self,
        job: JobPosting,
        match: MatchResult | None,
        status: str,
        reason: str = "",
        notes: str = "",
        applied_at: str = "",
    ) -> None:
        match = match or MatchResult(score=0, decision="skip")
        canonical_key = self.canonical_key(job.source, job.url, job.company, job.title, job.location)
        with self._connect() as connection:
            resolved_applied_at = applied_at or (datetime.now().isoformat(timespec="seconds") if status == "applied" else "")
            existing = connection.execute(
                """
                SELECT id, status, applied_at, location
                FROM jobs
                WHERE url = ? OR canonical_key = ?
                ORDER BY
                    CASE status
                        WHEN 'applied' THEN 0
                        WHEN 'filled_pending_submit' THEN 1
                        WHEN 'needs_manual_input' THEN 2
                        ELSE 3
                    END,
                    id DESC
                LIMIT 1
                """,
                (job.url, canonical_key),
            ).fetchone()
            if existing:
                if existing["status"] == "applied" and status != "applied":
                    self.logger.info("Preserved applied job | url=%s | requested_status=%s", job.url, status)
                    return
                try:
                    connection.execute(
                        """
                        UPDATE jobs SET
                            source = ?,
                            company = ?,
                            title = ?,
                            url = ?,
                            canonical_key = ?,
                            score = ?,
                            status = ?,
                            reason = ?,
                            criteria_text = ?,
                            expansion_audit = ?,
                            red_flags = ?,
                            missing_skills = ?,
                            location = CASE
                                WHEN ? <> '' THEN ?
                                ELSE location
                            END,
                            applied_at = CASE
                                WHEN ? <> '' THEN ?
                                ELSE applied_at
                            END,
                            notes = CASE
                                WHEN ? <> '' THEN ?
                                ELSE notes
                            END
                        WHERE id = ?
                        """,
                        (
                            job.source,
                            job.company,
                            job.title,
                            job.url,
                            canonical_key,
                            match.score,
                            status,
                            reason,
                            job.criteria_text,
                            job.expansion_audit,
                            ", ".join(match.red_flags),
                            ", ".join(match.missing_skills),
                            job.location,
                            job.location,
                            resolved_applied_at,
                            resolved_applied_at,
                            notes,
                            notes,
                            existing["id"],
                        ),
                    )
                except sqlite3.IntegrityError:
                    connection.execute(
                        """
                        UPDATE jobs SET
                            source = ?,
                            company = ?,
                            title = ?,
                            canonical_key = ?,
                            score = ?,
                            status = ?,
                            reason = ?,
                            criteria_text = ?,
                            expansion_audit = ?,
                            red_flags = ?,
                            missing_skills = ?,
                            location = CASE
                                WHEN ? <> '' THEN ?
                                ELSE location
                            END,
                            applied_at = CASE
                                WHEN ? <> '' THEN ?
                                ELSE applied_at
                            END,
                            notes = CASE
                                WHEN ? <> '' THEN ?
                                ELSE notes
                            END
                        WHERE id = ?
                        """,
                        (
                            job.source,
                            job.company,
                            job.title,
                            canonical_key,
                            match.score,
                            status,
                            reason,
                            job.criteria_text,
                            job.expansion_audit,
                            ", ".join(match.red_flags),
                            ", ".join(match.missing_skills),
                            job.location,
                            job.location,
                            resolved_applied_at,
                            resolved_applied_at,
                            notes,
                            notes,
                            existing["id"],
                        ),
                    )
                connection.commit()
            else:
                connection.execute(
                """
                INSERT INTO jobs (
                    source, company, title, url, canonical_key, score, status, reason, criteria_text, expansion_audit, red_flags,
                    missing_skills, location, applied_at, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(url) DO UPDATE SET
                    source=excluded.source,
                    company=excluded.company,
                    title=excluded.title,
                    canonical_key=excluded.canonical_key,
                    score=excluded.score,
                    status=excluded.status,
                    reason=excluded.reason,
                    criteria_text=excluded.criteria_text,
                    expansion_audit=excluded.expansion_audit,
                    red_flags=excluded.red_flags,
                    missing_skills=excluded.missing_skills,
                    location=CASE
                        WHEN excluded.location <> '' THEN excluded.location
                        ELSE jobs.location
                    END,
                    applied_at=CASE
                        WHEN excluded.applied_at <> '' THEN excluded.applied_at
                        ELSE jobs.applied_at
                    END,
                    notes=CASE
                        WHEN excluded.notes <> '' THEN excluded.notes
                        ELSE jobs.notes
                    END,
                    created_at=jobs.created_at
                """,
                (
                    job.source,
                    job.company,
                    job.title,
                    job.url,
                    canonical_key,
                    match.score,
                    status,
                    reason,
                    job.criteria_text,
                    job.expansion_audit,
                    ", ".join(match.red_flags),
                    ", ".join(match.missing_skills),
                    job.location,
                    resolved_applied_at,
                    notes,
                ),
                )
                connection.commit()
        if self._handled_cache is not None:
            cached_val = {
                "id": None,
                "source": job.source,
                "company": job.company,
                "title": job.title,
                "url": job.url,
                "canonical_key": canonical_key,
                "score": match.score,
                "status": status,
                "reason": reason,
                "applied_at": resolved_applied_at,
                "location": job.location or "",
            }
            if job.url:
                self._handled_cache[job.url] = cached_val
            if canonical_key:
                self._handled_cache[canonical_key] = cached_val
        if status == "applied" and self._applied_cache is not None:
            self._applied_cache.append({
                "company": job.company,
                "title": job.title,
                "url": job.url,
                "applied_at": resolved_applied_at,
                "location": job.location or "",
            })
        self.logger.info(
            "Tracker updated | url=%s | status=%s | score=%s | reason=%s",
            job.url,
            status,
            match.score,
            reason,
        )

    def list_jobs(self, limit: int = 50, status: str | None = None, order_by_score: bool = False) -> list[dict[str, Any]]:
        query = (
            "SELECT id, source, company, title, url, score, status, reason, criteria_text, expansion_audit, created_at, applied_at, location "
            "FROM jobs"
        )
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        if order_by_score:
            query += " ORDER BY score DESC, id DESC LIMIT ?"
        else:
            query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status ORDER BY status"
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()
        data = {row["status"]: row["count"] for row in rows}
        data["total"] = total["count"] if total else 0
        return data

    def platform_stats(self) -> dict[str, dict[str, int]]:
        """Return per-platform application counts and remaining queue sizes.

        Returns a dict keyed by platform (naukri, linkedin, company, unknown),
        each containing:
            applied           — successfully submitted applications
            pending_submit    — filled but awaiting final submit
            needs_manual      — requires human input
            shortlisted       — in queue, not yet attempted
            failed            — failed/skipped
            error             — processing errors
            total             — all rows for this platform
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT source, status, COUNT(*) AS cnt FROM jobs GROUP BY source, status"
            ).fetchall()

        platforms: dict[str, dict[str, int]] = {}
        for row in rows:
            src = row["source"] or "unknown"
            stat = row["status"]
            cnt = row["cnt"]
            if src not in platforms:
                platforms[src] = {
                    "applied": 0,
                    "pending_submit": 0,
                    "needs_manual": 0,
                    "shortlisted": 0,
                    "failed": 0,
                    "error": 0,
                    "total": 0,
                }
            bucket_map = {
                "applied": "applied",
                "filled_pending_submit": "pending_submit",
                "needs_manual_input": "needs_manual",
                "shortlisted": "shortlisted",
                "failed": "failed",
                "skipped": "failed",
                "error": "error",
            }
            bucket = bucket_map.get(stat, "failed")
            platforms[src][bucket] = platforms[src].get(bucket, 0) + cnt
            platforms[src]["total"] = platforms[src].get("total", 0) + cnt

        # Aggregate "external" = company + unknown
        external_keys = [k for k in platforms if k not in ("naukri", "linkedin")]
        if external_keys:
            ext: dict[str, int] = {
                "applied": 0, "pending_submit": 0, "needs_manual": 0,
                "shortlisted": 0, "failed": 0, "error": 0, "total": 0,
            }
            for k in external_keys:
                for field in ext:
                    ext[field] += platforms[k].get(field, 0)
            platforms["external"] = ext

        return platforms

    # ──────────────────────────────────────────────────────────────────────────
    # LinkedIn Post Email Table
    # ──────────────────────────────────────────────────────────────────────────

    def init_linkedin_post_email_table(self) -> None:
        """Create the linkedin_post_emails tracking table if it doesn't exist."""
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS linkedin_post_emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_url TEXT NOT NULL UNIQUE,
                    poster_name TEXT,
                    company TEXT,
                    role TEXT,
                    email_to TEXT,
                    email_subject TEXT,
                    sent_at TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            # Add index for fast dedup lookups
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_linkedin_post_emails_url "
                "ON linkedin_post_emails(post_url)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_linkedin_post_emails_email "
                "ON linkedin_post_emails(email_to)"
            )
            connection.commit()
        self.logger.info("Initialized linkedin_post_emails table.")

    def is_post_already_sent(self, post_url: str, email_to: str) -> bool:
        """Return True if this (post_url, email_to) pair was already successfully sent."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM linkedin_post_emails
                WHERE post_url = ? AND email_to = ? AND status = 'sent'
                LIMIT 1
                """,
                (post_url, email_to.lower()),
            ).fetchone()
        return row is not None

    def upsert_linkedin_post_email(
        self,
        post_url: str,
        poster_name: str = "",
        company: str = "",
        role: str = "",
        email_to: str = "",
        email_subject: str = "",
        status: str = "pending",
        reason: str = "",
        sent_at: str = "",
    ) -> None:
        """Insert or update a linkedin_post_emails record."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO linkedin_post_emails (
                    post_url, poster_name, company, role, email_to,
                    email_subject, sent_at, status, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(post_url) DO UPDATE SET
                    poster_name = CASE WHEN excluded.poster_name <> '' THEN excluded.poster_name ELSE linkedin_post_emails.poster_name END,
                    company = CASE WHEN excluded.company <> '' THEN excluded.company ELSE linkedin_post_emails.company END,
                    role = CASE WHEN excluded.role <> '' THEN excluded.role ELSE linkedin_post_emails.role END,
                    email_to = CASE WHEN excluded.email_to <> '' THEN excluded.email_to ELSE linkedin_post_emails.email_to END,
                    email_subject = CASE WHEN excluded.email_subject <> '' THEN excluded.email_subject ELSE linkedin_post_emails.email_subject END,
                    sent_at = CASE WHEN excluded.sent_at <> '' THEN excluded.sent_at ELSE linkedin_post_emails.sent_at END,
                    status = excluded.status,
                    reason = CASE WHEN excluded.reason <> '' THEN excluded.reason ELSE linkedin_post_emails.reason END
                """,
                (
                    post_url, poster_name, company, role,
                    email_to.lower(), email_subject, sent_at,
                    status, reason,
                ),
            )
            connection.commit()
        self.logger.debug(
            "linkedin_post_emails upserted | post_url=%s | status=%s | email_to=%s",
            post_url, status, email_to,
        )

    def list_linkedin_post_emails(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        """List linkedin_post_emails records, optionally filtered by status."""
        query = (
            "SELECT id, post_url, poster_name, company, role, email_to, "
            "email_subject, sent_at, status, reason, created_at "
            "FROM linkedin_post_emails"
        )
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def export_rows(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source, company, title, url, score, status, reason, criteria_text, expansion_audit, red_flags,
                       missing_skills, applied_at, notes, created_at
                FROM jobs
                ORDER BY id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def backup_database(self, backup_dir: Path | None = None) -> Path:
        """Create a point-in-time online SQLite backup using SQLite's backup API."""
        target_dir = backup_dir or (self.db_path.parent / "backups")
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = target_dir / f"jobs_backup_{stamp}.db"
        with self._connect() as src:
            with sqlite3.connect(backup_path) as dst:
                src.backup(dst)
        self.logger.info("Successfully created online database backup: %s", backup_path)
        return backup_path

    def record_interview(
        self,
        company: str,
        intent: str,
        role: str | None = None,
        job_id: int | None = None,
        status: str = "needs_action",
        recruiter_name: str | None = None,
        recruiter_email: str | None = None,
        meeting_link: str | None = None,
        assessment_link: str | None = None,
        deadline_or_time: str | None = None,
        raw_snippet: str | None = None,
    ) -> int:
        """Record an inbound recruiter response, interview invitation, or technical assessment."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO interviews (
                    job_id, company, role, intent, status,
                    recruiter_name, recruiter_email, meeting_link,
                    assessment_link, deadline_or_time, raw_snippet
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    company,
                    role,
                    intent,
                    status,
                    recruiter_name,
                    recruiter_email,
                    meeting_link,
                    assessment_link,
                    deadline_or_time,
                    raw_snippet,
                ),
            )
            connection.commit()
            interview_id = cursor.lastrowid

            # If associated with a job, update job status
            if job_id:
                new_status = "interview_scheduled" if "INTERVIEW" in intent.upper() else "assessment_received"
                connection.execute(
                    "UPDATE jobs SET status = ?, notes = ? WHERE id = ?",
                    (new_status, f"Inbound {intent} recorded via triage (Interview ID #{interview_id})", job_id),
                )
                connection.commit()
            return int(interview_id or 0)

    def list_interviews(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List recorded interviews and inbound recruiter engagements."""
        query = (
            "SELECT id, job_id, company, role, intent, status, recruiter_name, "
            "recruiter_email, meeting_link, assessment_link, deadline_or_time, "
            "raw_snippet, created_at FROM interviews"
        )
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_interview_summary(self) -> dict[str, int]:
        """Get counts grouped by intent and status."""
        summary: dict[str, int] = {}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT intent, COUNT(*) as count FROM interviews GROUP BY intent"
            ).fetchall()
            for r in rows:
                summary[r["intent"]] = r["count"]
        return summary

    def find_job_by_company(self, company_name: str) -> dict[str, Any] | None:
        """Find the most recent job matching a company name."""
        norm = normalize_key(company_name)
        if not norm:
            return None
        with self._connect() as connection:
            # First try exact normalized match
            rows = connection.execute(
                "SELECT id, company, title, url, status, applied_at FROM jobs ORDER BY id DESC LIMIT 200"
            ).fetchall()
            for row in rows:
                c = normalize_key(row["company"] or "")
                if c and (c == norm or norm in c or c in norm):
                    return dict(row)
        return None
