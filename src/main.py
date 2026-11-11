"""
src/main.py — Primary CLI Entry Point for the Clean Job Agent Framework.

Provides terminal commands to initialize the database, execute URL queues,
inspect SQLite analytics, and export logs cleanly.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import settings
from database.init_db import db_manager
from src.agent import JobAgent
from src.browser import create_driver
from src.java_runner import java_runner
from src.tracker import tracker

app = typer.Typer(
    help="Autonomous, Open-Source Job Search & Application Framework.",
    rich_markup_mode="markdown",
)
console = Console()


@app.command()
def init() -> None:
    """
    Run self-healing database initialization and verify system dependencies.
    """
    console.print(Panel("[bold green]Job Agent Framework — Self-Healing System Audit[/bold green]"))

    # 1. Database check
    with console.status("[bold cyan]Initializing SQLite database...[/bold cyan]"):
        db_manager.initialize_database()
        health = db_manager.check_health()

    table = Table(title="Database Health Check", show_header=True, header_style="bold magenta")
    table.add_column("Table Name", style="dim")
    table.add_column("Record Count", justify="right")
    for tbl, cnt in health.items():
        table.add_row(tbl, str(cnt))
    console.print(table)

    # 2. Java Subprocess check
    with console.status("[bold cyan]Checking Java Runtime environment...[/bold cyan]"):
        java_ok = java_runner.is_java_available()
        ping_res = java_runner.run_bridge("ping") if java_ok else {"engine": "python_fallback"}

    if java_ok:
        rprint(f"[green]✓[/green] Java runtime detected: [bold]{ping_res.get('java_version', 'active')}[/bold]")
    else:
        rprint("[yellow]![/yellow] Java runtime not found. Python fallback active for hash/score routines.")

    # 3. Environment & Configuration Check
    rprint(f"[green]✓[/green] Active Candidate: [bold]{settings.candidate_name}[/bold] ({settings.candidate_email})")
    rprint(f"[green]✓[/green] Target Role: [bold]{settings.target_role}[/bold]")
    rprint(f"[green]✓[/green] Browser Engine: [bold]{settings.browser_type.upper()}[/bold] (Headless: {settings.headless})")
    rprint(f"[green]✓[/green] Log Directory: [dim]{settings.logs_dir}[/dim]")

    console.print("\n[bold green]System is ready to execute automation queues.[/bold green]")


@app.command()
def run(
    input_file: Path = typer.Option(
        BASE_DIR / "jobs" / "urls.example.txt",
        "--input",
        "-i",
        help="Path to text file containing job URLs (one per line).",
    ),
    headless: Optional[bool] = typer.Option(
        None,
        "--headless/--visible",
        help="Override headless browser mode.",
    ),
) -> None:
    """
    Execute the job scraping and scoring pipeline over a seed list of URLs.
    """
    if headless is not None:
        settings.headless = headless

    if not input_file.exists():
        console.print(f"[bold red]Error:[/bold red] URL file not found at: {input_file}")
        raise typer.Exit(code=1)

    urls = [line.strip() for line in input_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    if not urls:
        console.print(f"[bold yellow]Warning:[/bold yellow] No active URLs found in {input_file}.")
        raise typer.Exit(code=0)

    console.print(Panel(f"[bold cyan]Launching Job Agent Queue — {len(urls)} URLs Loaded[/bold cyan]"))
    agent = JobAgent()
    agent.run_queue(urls)


@app.command()
def stats() -> None:
    """
    Display SQLite application metrics and breakdown.
    """
    summary = tracker.get_summary_stats()
    table = Table(title="Job Tracking Overview", show_header=True, header_style="bold cyan")
    table.add_column("Application Status", style="bold")
    table.add_column("Count", justify="right")

    if not summary:
        console.print("[dim]No job listings currently in database.[/dim]")
        return

    for status, count in summary.items():
        color = "green" if status == "applied" else "yellow" if status == "scored" else "dim"
        table.add_row(f"[{color}]{status.upper()}[/{color}]", str(count))
    console.print(table)


@app.command(name="dashboard")
@app.command(name="ui")
def dashboard(
    port: int = typer.Option(8765, help="Port to bind the Mission Control web server."),
    profile_name: str = typer.Option("default", "--profile", "-p", help="Active profile name."),
) -> None:
    """
    Launch the local browser-based Mission Control dashboard.
    """
    from app.web_radar import run_web_dashboard
    console.print(f"[bold cyan]Launching Mission Control at http://127.0.0.1:{port}...[/bold cyan]")
    run_web_dashboard(port=port, profile_name=profile_name)


@app.command(name="apply-posts")
def apply_posts(
    live: bool = typer.Option(False, "--live", help="Send actual emails via SMTP (default is dry-run preview)."),
    pages: int = typer.Option(5, "--pages", min=1, max=20, help="Max search result pages to scan per query."),
    headful: bool = typer.Option(False, "--headful", help="Run browser in headful mode (visible window)."),
) -> None:
    """
    Scan LinkedIn recruiter hiring posts, generate tailored cover emails, and apply.
    """
    import subprocess
    script_path = str(BASE_DIR / "linkedin_post_applier.py")
    cmd = [sys.executable, script_path, "--pages", str(pages)]
    if live:
        cmd.append("--live")
    if headful:
        cmd.append("--headful")
    console.print(f"[bold cyan]Launching LinkedIn Post Email Applier...[/bold cyan] (live={live}, pages={pages})")
    subprocess.run(cmd, check=False)


@app.command(name="sync-inbox")
def sync_inbox(
    max_messages: int = typer.Option(20, min=1, max=100, help="Max recent emails to inspect from IMAP."),
) -> None:
    """
    Scan IMAP inbox for inbound recruiter responses, interview invites, and status updates.
    """
    from app.inbound_sync import InboundSyncManager
    console.print(f"[bold cyan]Syncing IMAP inbox for recruiter triage (max={max_messages})...[/bold cyan]")
    mgr = InboundSyncManager()
    results = mgr.sync_imap_inbox(max_messages=max_messages)
    if not results:
        console.print("[yellow]No new recruiter interview invitations or assessments detected in inbox.[/yellow]")
    else:
        console.print(f"[bold green]✓ Succeeded:[/bold green] Triaged {len(results)} recruiter engagements. Alerts logged to exports/interview_alerts.md.")


@app.command(name="compile-resume")
def compile_resume(
    role: str = typer.Option("Software Engineer", "--role", "-r", help="Target job role title."),
    company: str = typer.Option("Target Company", "--company", "-c", help="Target company name."),
    profile_name: str = typer.Option("default", "--profile", "-p", help="Persona profile name."),
    jd: str = typer.Option("", help="Optional snippet of target job description."),
) -> None:
    """
    Dynamically compile an ATS-compliant tailored PDF resume.
    """
    import re
    from app.profile_loader import load_profile
    from app.resume_compiler import DynamicResumeCompiler
    profile = load_profile(profile_name)
    compiler = DynamicResumeCompiler()
    prefix = f"{profile_name}_{re.sub(r'[^a-zA-Z0-9]', '_', company)}_{re.sub(r'[^a-zA-Z0-9]', '_', role)}"
    pdf_path = compiler.compile_tailored_pdf(
        profile=profile,
        job_title=role,
        company=company,
        job_description=jd,
        filename_prefix=prefix,
    )
    console.print(f"[bold green]✓ ATS Tailored Resume compiled successfully:[/bold green] {pdf_path}")


@app.command(name="export")
def export(
    output_path: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Custom export destination CSV path.",
    ),
) -> None:
    """
    Export SQLite tracking records to a clean CSV file.
    """
    import csv
    dest = output_path or (settings.logs_dir / "job_applications_export.csv")
    with tracker._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, source, company, title, url, status, score, timestamp FROM jobs ORDER BY id DESC")
        rows = cursor.fetchall()
    with open(dest, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Source", "Company", "Title", "URL", "Status", "Score", "Timestamp"])
        writer.writerows(rows)
    console.print(f"[bold green]✓ Exported {len(rows)} records to:[/bold green] {dest}")


@app.command(name="stop-ai")
def stop_ai() -> None:
    """
    Unload Ollama models and terminate background AI processes to free 100% of RAM.
    """
    import subprocess
    import urllib.request
    console.print("[cyan]Unloading Ollama models and freeing system RAM...[/cyan]")
    try:
        req = urllib.request.Request(
            f"{settings.ai_base_url}/api/generate",
            data=f'{{"model": "{settings.ai_model}", "keep_alive": 0}}'.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass
    if sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True)
    console.print("[bold green]✓ Local AI (Ollama) stopped and RAM released.[/bold green]")


@app.command()
def open_browser() -> None:
    """
    Launch an interactive visible browser window to verify site connectivity or perform manual login.
    """
    console.print("[bold yellow]Launching interactive browser session... Close browser window when finished.[/bold yellow]")
    driver = create_driver(headless=False)
    try:
        driver.get("https://www.google.com")
        console.print("[green]Browser loaded. Waiting until window is closed...[/green]")
        while True:
            try:
                _ = driver.title
                import time
                time.sleep(1.0)
            except Exception:
                break
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    console.print("[green]Browser session finished.[/green]")


if __name__ == "__main__":
    app()
