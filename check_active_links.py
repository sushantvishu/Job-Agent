"""
Lightning-fast job expiry checker using requests.
Naukri uses a 301/302 redirect for expired jobs, adding '?expJD=true' to the URL.
This script checks the final redirected URL and page text to determine expiry.
"""
import sqlite3
import requests
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}

EXPIRY_SIGNALS = [
    "job you are looking for is expired",
    "this job is no longer available",
    "job is no longer accepting",
    "position has been filled",
    "job has been closed",
    "no longer available",
    "job has expired",
    "listing has expired",
]

def check_url(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        final_url = resp.url.lower()
        
        # 1. Check for Naukri redirect parameter
        if "expjd=true" in final_url:
            return "expired", "Redirected to expJD=true"
            
        # 2. Check HTTP status
        if resp.status_code == 404:
            return "expired", "HTTP 404 Not Found"
            
        # 3. Check text signals
        body_lower = resp.text.lower()[:5000]
        for signal in EXPIRY_SIGNALS:
            if signal in body_lower:
                return "expired", f"Found text: '{signal}'"
                
        return "active", "No expiry signals detected"
    except Exception as e:
        return "error", str(e)[:60]

def main():
    c = sqlite3.connect("d:/job-agent/jobs.db")
    c.row_factory = sqlite3.Row

    rows = c.execute(
        "SELECT title, company, url, score FROM jobs WHERE status='filled_pending_submit' ORDER BY score DESC"
    ).fetchall()

    print(f"Checking {len(rows)} URLs...\n")

    active = []
    expired = []

    for idx, row in enumerate(rows, 1):
        url = row["url"]
        title = (row["title"] or "Unknown")[:45]
        company = (row["company"] or "Unknown")[:25]
        score = row["score"]
        
        print(f"[{idx:02}/{len(rows)}] Checking: {title} @ {company}")
        status, reason = check_url(url)
        
        if status == "expired":
            print(f"        -> EXPIRED: {reason}")
            expired.append(dict(row))
        else:
            print(f"        -> ACTIVE")
            active.append(dict(row))
            
        time.sleep(0.3)

    # Purge expired from DB
    if expired:
        c.executemany(
            "UPDATE jobs SET status='skipped', reason='Confirmed expired via URL redirect' WHERE url=?",
            [(r["url"],) for r in expired]
        )
        c.commit()
        print(f"\nPurged {len(expired)} expired jobs from DB.")

    # Generate updated HTML
    now = time.strftime("%d %b %Y %I:%M %p")
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Active Pending Applications</title>
<style>
body {{ font-family: Arial, sans-serif; padding: 20px; max-width: 950px; margin: auto; background: #f8fafc; }}
h1 {{ color: #1e293b; margin-bottom: 4px; }}
.ts {{ color: #64748b; font-size: 13px; margin-bottom: 16px; }}
.stats {{ display: flex; gap: 16px; margin: 16px 0 24px; }}
.stat {{ padding: 14px 24px; border-radius: 10px; font-weight: bold; text-align: center; min-width: 120px; }}
.stat.active  {{ background: #dcfce7; color: #166534; }}
.stat.expired {{ background: #fee2e2; color: #991b1b; }}
.section {{ font-size: 17px; font-weight: bold; margin: 20px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #e2e8f0; }}
.job {{ background: white; border: 1px solid #e2e8f0; padding: 14px 16px; margin: 7px 0; border-radius: 10px; display: flex; align-items: center; gap: 14px; box-shadow: 0 1px 3px rgba(0,0,0,.04); }}
.job.high  {{ border-left: 5px solid #22c55e; }}
.job.mid   {{ border-left: 5px solid #f59e0b; }}
.job.low   {{ border-left: 5px solid #94a3b8; }}
.job.dead  {{ border-left: 5px solid #ef4444; opacity: 0.55; }}
.score {{ background: #1e40af; color: white; padding: 4px 10px; border-radius: 20px; font-size: 12px; min-width: 52px; text-align: center; white-space: nowrap; }}
.info {{ flex: 1; min-width: 0; }}
.info strong {{ font-size: 15px; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.info .co {{ color: #475569; font-size: 13px; }}
.info .url {{ color: #94a3b8; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }}
a.btn {{ background: #2563eb; color: white; padding: 8px 18px; border-radius: 7px; text-decoration: none; font-size: 13px; font-weight: 600; white-space: nowrap; }}
a.btn:hover {{ background: #1d4ed8; }}
.tag-exp {{ color: #dc2626; font-weight: bold; font-size: 13px; white-space: nowrap; }}
</style></head><body>
<h1>Pending Applications</h1>
<p class="ts">Checked on {now} — Redirect analysis</p>
<div class="stats">
  <div class="stat active">{len(active)} ACTIVE</div>
  <div class="stat expired">{len(expired)} EXPIRED</div>
</div>
<div class="section">✅ Active Jobs — Click to Open & Submit</div>
"""
    for r in sorted(active, key=lambda x: x["score"], reverse=True):
        sc = r["score"]
        cls = "high" if sc >= 50 else ("mid" if sc >= 20 else "low")
        html += f"""
<div class="job {cls}">
  <span class="score">{sc} pts</span>
  <div class="info">
    <strong>{r['title'] or 'Unknown Role'}</strong>
    <span class="co">{r['company'] or 'Unknown'}</span>
    <span class="url">{r['url']}</span>
  </div>
  <a class="btn" href="{r['url']}" target="_blank">Open &amp; Apply ↗</a>
</div>"""

    if expired:
        html += f'\n<div class="section" style="color:#dc2626">❌ Expired / Closed ({len(expired)} purged)</div>'
        for r in sorted(expired, key=lambda x: x["score"], reverse=True):
            html += f"""
<div class="job dead">
  <span class="score" style="background:#dc2626">{r['score']}</span>
  <div class="info">
    <strong>{r['title'] or 'Unknown'}</strong>
    <span class="co">{r['company'] or 'Unknown'}</span>
  </div>
  <span class="tag-exp">EXPIRED</span>
</div>"""

    html += "\n</body></html>"

    with open("d:/job-agent/pending_applications.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n{'='*60}")
    print(f"ACTIVE : {len(active)}")
    print(f"EXPIRED: {len(expired)}")
    print(f"HTML updated → d:/job-agent/pending_applications.html")

if __name__ == "__main__":
    main()
