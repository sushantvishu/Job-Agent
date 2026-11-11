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
