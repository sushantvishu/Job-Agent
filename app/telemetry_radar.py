from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table

from app.config import AppConfig, load_config
from app.tracker import JobTracker


def render_radar_dashboard(config: AppConfig | None = None, tracker: JobTracker | None = None) -> Panel:
    """Renders a comprehensive, executive Rich terminal telemetry dashboard."""
    cfg = config or load_config()
    trk = tracker or JobTracker(cfg.db_path)

    # 1. Pipeline Funnel Stats
    stats = trk.stats()
    total = stats.get("total", 0)
    applied = stats.get("applied", 0)
    needs_review = stats.get("needs_review", 0)
    failed = stats.get("failed", 0)
    skipped = stats.get("skipped", 0)
    conversion_rate = (applied / total * 100) if total > 0 else 0.0

    funnel_table = Table(box=None, expand=True)
    funnel_table.add_column("Stage", style="bold cyan")
    funnel_table.add_column("Count", justify="right", style="bold green")
    funnel_table.add_column("Share", justify="right", style="dim")
    funnel_table.add_row("Total Sourced", str(total), "100%")
    funnel_table.add_row("Applied / Submitted", str(applied), f"{conversion_rate:.1f}%")
    funnel_table.add_row("Needs Manual Review", str(needs_review), f"{(needs_review / total * 100) if total else 0:.1f}%")
    funnel_table.add_row("Pruned / Skipped", str(skipped), f"{(skipped / total * 100) if total else 0:.1f}%")
    funnel_table.add_row("Terminal Failures", str(failed), f"{(failed / total * 100) if total else 0:.1f}%")

    # 2. Email Quota Stats
    quota_file = cfg.project_root / "logs" / "email_quota.json"
    sent_today = 0
    quota_limit = 30
    if quota_file.exists():
        try:
            q_data = json.loads(quota_file.read_text(encoding="utf-8"))
            sent_today = len(q_data.get("recipients", []))
        except Exception:
            pass

    quota_table = Table(box=None, expand=True)
    quota_table.add_column("Metric", style="bold yellow")
    quota_table.add_column("Status", justify="right")
    quota_table.add_row("Daily Limit", f"{quota_limit} emails/day")
    quota_table.add_row("Dispatched Today", f"{sent_today} / {quota_limit}")
    quota_table.add_row("Remaining Allowance", f"[bold green]{max(0, quota_limit - sent_today)}[/bold green]")
    quota_table.add_row("Active Profile", f"[bold cyan]{cfg.active_profile.upper()}[/bold cyan]")
    quota_table.add_row("Engine / Stealth", f"{cfg.browser_channel or cfg.browser_engine} (Stealth ON)")

    # 3. Inbound Interviews Summary
    try:
        interviews = trk.list_interviews(limit=5)
        interview_summary = trk.get_interview_summary()
    except Exception:
        interviews = []
        interview_summary = {}

    interview_table = Table(box=None, expand=True)
    interview_table.add_column("Company", style="bold magenta")
    interview_table.add_column("Intent", style="bold green")
    interview_table.add_column("Meeting / Status")
    if not interviews:
        interview_table.add_row("No inbound triage records yet", "Run sync-inbox", "—")
    else:
        for itv in interviews[:4]:
            link_display = "[cyan]Meeting Link Ready[/cyan]" if itv.get("meeting_link") else itv.get("status", "pending")
            interview_table.add_row(
                (itv.get("company") or "Unknown")[:20],
                itv.get("intent", "INVITE"),
                link_display,
            )

    # 4. Recent Jobs Table
    recent_jobs = trk.list_jobs(limit=5)
    recent_table = Table(title="Recent Automated Pipeline Jobs", expand=True)
    recent_table.add_column("ID", style="dim", width=6)
    recent_table.add_column("Company", style="bold white", width=22)
    recent_table.add_column("Title", width=28)
    recent_table.add_column("Score", justify="right", width=7)
    recent_table.add_column("Status", justify="center", width=16)

    status_styles = {
        "applied": "[bold green]APPLIED[/bold green]",
        "needs_review": "[bold yellow]NEEDS REVIEW[/bold yellow]",
        "failed": "[bold red]FAILED[/bold red]",
        "skipped": "[dim]SKIPPED[/dim]",
        "interview_scheduled": "[bold magenta]INTERVIEW[/bold magenta]",
    }

    for job in recent_jobs:
        st = status_styles.get(job.get("status", ""), job.get("status", ""))
        recent_table.add_row(
            str(job.get("id")),
            (job.get("company") or "")[:20],
            (job.get("title") or "")[:26],
            str(job.get("score") or "—"),
            st,
        )

    # Outer Layout
    layout = Layout()
    layout.split_column(
        Layout(name="top", size=9),
        Layout(name="bottom", size=10),
    )
    layout["top"].split_row(
        Layout(Panel(funnel_table, title="[bold cyan]Pipeline Funnel Telemetry[/bold cyan]")),
        Layout(Panel(quota_table, title="[bold yellow]Operational Quota & Profile[/bold yellow]")),
        Layout(Panel(interview_table, title="[bold magenta]Inbound Interview Radar[/bold magenta]")),
    )
    layout["bottom"].update(Panel(recent_table, title="[bold white]Real-Time Submission Stream[/bold white]"))

    return Panel(
        layout,
        title=f"[bold green]JOB AGENT ENTERPRISE RADAR — [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][/bold green]",
        subtitle="[dim]Principal Secretary Operations Dashboard | Uncompromising Quality & Autonomy[/dim]",
    )
