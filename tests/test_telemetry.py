from pathlib import Path
from app.config import load_config
from app.tracker import JobTracker
from app.telemetry import calculate_funnel_metrics, log_event


def test_funnel_metrics_calculation():
    cfg = load_config()
    tracker = JobTracker(cfg.db_path)
    metrics = calculate_funnel_metrics(tracker)

    assert "total_jobs_tracked" in metrics
    assert "funnel" in metrics
    assert "platforms" in metrics
    assert "recruiter_outreach" in metrics
    assert metrics["funnel"]["applied"] >= 0
    assert 0.0 <= metrics["funnel"]["conversion_rate_percent"] <= 100.0


def test_structured_event_logging(tmp_path: Path):
    event_dir = tmp_path / "logs"
    log_event("agent_started", logs_dir=event_dir, run_mode="auto", worker_id=1)
    
    event_file = event_dir / "events.jsonl"
    assert event_file.exists()
    content = event_file.read_text(encoding="utf-8")
    assert "agent_started" in content
    assert "worker_id" in content
