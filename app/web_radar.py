from __future__ import annotations

import json
import logging
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import AppConfig, load_config
from app.tracker import JobTracker

logger = logging.getLogger("web_radar")

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Job Agent — Mission Control</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-dim: #94a3b8;
      --accent: #38bdf8;
      --success: #34d399;
      --warning: #fbbf24;
      --danger: #f87171;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      padding: 24px;
      line-height: 1.5;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
    }
    h1 { font-size: 24px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 10px; }
    .badge {
      font-size: 12px;
      background: #0284c7;
      color: #fff;
      padding: 4px 10px;
      border-radius: 9999px;
      text-transform: uppercase;
      font-weight: 600;
    }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
    }
    .card h3 { font-size: 13px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
    .card .value { font-size: 32px; font-weight: 700; color: var(--text); }
    .section-title { font-size: 18px; margin: 24px 0 12px 0; color: var(--accent); display: flex; justify-content: space-between; align-items: center; }
    table { width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 10px; overflow: hidden; border: 1px solid var(--border); }
    th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); }
    th { background: #182234; color: var(--text-dim); font-size: 12px; text-transform: uppercase; }
    tr:hover { background: #243247; }
    .btn {
      background: #0284c7;
      color: #fff;
      border: none;
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      text-decoration: none;
      display: inline-block;
    }
    .btn:hover { background: #0369a1; }
    .btn-success { background: #059669; }
    .btn-success:hover { background: #047857; }
    .btn-danger { background: #dc2626; }
    .btn-danger:hover { background: #b91c1c; }
    .link { color: var(--accent); text-decoration: none; }
    .link:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <header>
    <h1>🛡️ Job Agent — Mission Control <span class="badge" id="profile-badge">DEFAULT</span></h1>
    <div>
      <span id="timestamp" style="color: var(--text-dim); font-size: 13px;"></span>
      <button class="btn" onclick="fetchData()" style="margin-left: 12px;">🔄 Refresh</button>
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <h3>Total Sourced</h3>
      <div class="value" id="stat-total">—</div>
    </div>
    <div class="card">
      <h3>Applications Submitted</h3>
      <div class="value" id="stat-applied" style="color: var(--success);">—</div>
    </div>
    <div class="card">
      <h3>Daily Email Quota</h3>
      <div class="value" id="stat-quota" style="color: var(--warning);">—</div>
    </div>
    <div class="card">
      <h3>Active Interviews</h3>
      <div class="value" id="stat-interviews" style="color: var(--accent);">—</div>
    </div>
  </div>

  <div class="section-title">
    <span>🚨 Inbound Recruiter Triage & Interview Radar</span>
  </div>
  <table id="interviews-table">
    <thead>
      <tr>
        <th>Company</th>
        <th>Intent</th>
        <th>Recruiter</th>
        <th>Action / Link</th>
        <th>Recorded At</th>
      </tr>
    </thead>
    <tbody id="interviews-body">
      <tr><td colspan="5" style="text-align:center; color: var(--text-dim);">Loading interviews...</td></tr>
    </tbody>
  </table>

  <div class="section-title">
    <span>📋 Applications Pipeline & Manual Review Queue</span>
  </div>
  <table id="jobs-table">
    <thead>
      <tr>
        <th>ID</th>
        <th>Company</th>
        <th>Title</th>
        <th>Score</th>
        <th>Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="jobs-body">
      <tr><td colspan="6" style="text-align:center; color: var(--text-dim);">Loading pipeline jobs...</td></tr>
    </tbody>
  </table>

  <script>
    async function fetchData() {
      document.getElementById('timestamp').innerText = 'Last updated: ' + new Date().toLocaleTimeString();
      try {
        const statsRes = await fetch('/api/stats');
        const stats = await statsRes.json();
        document.getElementById('stat-total').innerText = stats.total || 0;
        document.getElementById('stat-applied').innerText = stats.applied || 0;
        document.getElementById('stat-quota').innerText = (stats.email_sent_today || 0) + ' / 30';
        document.getElementById('profile-badge').innerText = (stats.active_profile || 'DEFAULT').toUpperCase();

        const itvRes = await fetch('/api/interviews');
        const interviews = await itvRes.json();
        document.getElementById('stat-interviews').innerText = interviews.length;
        const itvBody = document.getElementById('interviews-body');
        if (!interviews.length) {
          itvBody.innerHTML = '<tr><td colspan="5" style="text-align:center; color: var(--text-dim);">No active inbound interviews yet.</td></tr>';
        } else {
          itvBody.innerHTML = interviews.map(i => `
            <tr>
              <td><strong>${i.company || 'Direct'}</strong></td>
              <td><span class="badge" style="background:#059669;">${i.intent}</span></td>
              <td>${i.recruiter_email || '—'}</td>
              <td>
                ${i.meeting_link ? `<a class="btn" href="${i.meeting_link}" target="_blank">📅 Open Meeting</a>` : (i.assessment_link ? `<a class="btn" href="${i.assessment_link}" target="_blank">📝 Assessment</a>` : 'Awaiting Link')}
              </td>
              <td style="color:var(--text-dim); font-size:12px;">${i.created_at || '—'}</td>
            </tr>
          `).join('');
        }

        const jobsRes = await fetch('/api/jobs');
        const jobs = await jobsRes.json();
        const jobsBody = document.getElementById('jobs-body');
        if (!jobs.length) {
          jobsBody.innerHTML = '<tr><td colspan="6" style="text-align:center; color: var(--text-dim);">No jobs found.</td></tr>';
        } else {
          jobsBody.innerHTML = jobs.map(j => `
            <tr>
              <td>#${j.id}</td>
              <td><strong>${j.company || '—'}</strong></td>
              <td><a class="link" href="${j.url}" target="_blank">${j.title || 'Job Listing'}</a></td>
              <td><strong>${j.score || '—'}</strong></td>
              <td><span class="badge" style="background:${j.status === 'applied' ? '#059669' : (j.status === 'needs_review' ? '#d97706' : '#475569')}">${j.status}</span></td>
              <td>
                <button class="btn btn-success" onclick="takeAction(${j.id}, 'mark_applied')">✓ Mark Applied</button>
                <button class="btn btn-danger" onclick="takeAction(${j.id}, 'mark_skipped')">✕ Skip</button>
              </td>
            </tr>
          `).join('');
        }
      } catch (err) {
        console.error('Failed to load dashboard telemetry:', err);
      }
    }

    async function takeAction(jobId, action) {
      await fetch('/api/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, action: action })
      });
      fetchData();
    }

    fetchData();
    setInterval(fetchData, 10000);
  </script>
</body>
</html>
"""


class WebRadarHandler(BaseHTTPRequestHandler):
    config: AppConfig | None = None
    tracker: JobTracker | None = None

    def log_message(self, format: str, *args: Any) -> None:
        # Silence default terminal request spam
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
            return

        if path == "/api/stats":
            trk = self.tracker or JobTracker(self.config.db_path)
            stats = trk.stats()
            # Email quota check
            quota_file = self.config.project_root / "logs" / "email_quota.json"
            sent_today = 0
            if quota_file.exists():
                try:
                    q = json.loads(quota_file.read_text(encoding="utf-8"))
                    sent_today = len(q.get("recipients", []))
                except Exception:
                    pass
            payload = {
                **stats,
                "email_sent_today": sent_today,
                "active_profile": getattr(self.config, "active_profile", "default"),
            }
            self._send_json(payload)
            return

        if path == "/api/interviews":
            trk = self.tracker or JobTracker(self.config.db_path)
            interviews = trk.list_interviews(limit=25)
            self._send_json(interviews)
            return

        if path == "/api/jobs":
            trk = self.tracker or JobTracker(self.config.db_path)
            query = parse_qs(parsed.query)
            status = query.get("status", [None])[0]
            jobs = trk.list_jobs(limit=20, status=status)
            self._send_json(jobs)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/action":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            try:
                data = json.loads(body)
                job_id = int(data.get("job_id"))
                action = data.get("action")
                trk = self.tracker or JobTracker(self.config.db_path)
                with trk._connect() as conn:
                    if action == "mark_applied":
                        conn.execute("UPDATE jobs SET status = 'applied', notes = 'Marked applied via Web Radar' WHERE id = ?", (job_id,))
                    elif action == "mark_skipped":
                        conn.execute("UPDATE jobs SET status = 'skipped', notes = 'Skipped via Web Radar' WHERE id = ?", (job_id,))
                    conn.commit()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        self.send_response(404)
        self.end_headers()

    def _send_json(self, data: Any, status: int = 200) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def run_web_dashboard(port: int = 8765, profile_name: str | None = None) -> None:
    """Launch the local HTTP Web Command Center."""
    cfg = load_config(profile_name=profile_name)
    trk = JobTracker(cfg.db_path)
    trk.init_db()

    WebRadarHandler.config = cfg
    WebRadarHandler.tracker = trk

    server = ThreadingHTTPServer(("127.0.0.1", port), WebRadarHandler)
    logger.info("Web Radar Mission Control active at http://127.0.0.1:%d", port)
    print(f"\n🚀 [Job Agent Mission Control] Dashboard live at: http://127.0.0.1:{port}")
    print("Press Ctrl+C to terminate.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Web Radar server...")
        server.server_close()
