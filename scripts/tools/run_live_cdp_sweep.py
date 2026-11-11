"""
Runner script for LinkedIn Post Email Applier via Chrome Remote Debugging (CDP).
Monitors for Chrome to close, relaunches it with --remote-debugging-port=9222,
and immediately triggers the live 24-query x 3-page sweep.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Force UTF-8 on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9222


def is_port_open(port: int = CDP_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_chrome_running() -> bool:
    try:
        out = subprocess.check_output(
            ["powershell", "-Command", "Get-Process chrome -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return bool(out)
    except Exception:
        return False


def wait_and_launch() -> None:
    print("=" * 72, flush=True)
    print("  [LAUNCHER] LinkedIn Post Email Applier - CDP Remote Debugging", flush=True)
    print("=" * 72, flush=True)

    if is_port_open(CDP_PORT):
        print(f"[OK] Port {CDP_PORT} is already open! Proceeding directly to sweep...", flush=True)
    else:
        if is_chrome_running():
            print("[INFO] Google Chrome is currently open without remote debugging.", flush=True)
            print("[ACTION REQUIRED] Please close your Chrome browser window (click 'X').", flush=True)
            print("   The script is actively waiting and will relaunch Chrome automatically...", flush=True)

            wait_secs = 0
            while is_chrome_running() and wait_secs < 180:
                time.sleep(1)
                wait_secs += 1
                if wait_secs % 10 == 0:
                    print(f"   Waiting for Chrome to close... ({wait_secs}s / 180s)", flush=True)

            if is_chrome_running():
                print("[TIMEOUT] Chrome was not closed within 180 seconds. Please close Chrome and run again.", flush=True)
                sys.exit(1)

        print("\n[RELAUNCH] Chrome closed. Relaunching Chrome with --remote-debugging-port=9222...", flush=True)
        # Give Windows 1.5s to release file locks
        time.sleep(1.5)

        cmd = [
            CHROME_PATH,
            f"--remote-debugging-port={CDP_PORT}",
            "--restore-last-session",
            "https://www.linkedin.com/feed/",
        ]
        subprocess.Popen(cmd)

        # Wait for port 9222 to open
        print(f"[WAIT] Waiting for CDP port {CDP_PORT} to become ready...", flush=True)
        ready = False
        for _ in range(20):
            if is_port_open(CDP_PORT):
                ready = True
                break
            time.sleep(1)

        if not ready:
            print("[ERROR] Failed to connect to CDP port 9222 after launching Chrome.", flush=True)
            sys.exit(1)

        print("[SUCCESS] Chrome relaunched successfully with CDP port 9222 active!", flush=True)
        print("[WAIT] Giving Chrome 5 seconds to load LinkedIn feed...", flush=True)
        time.sleep(5)

    # Now launch the full live sweep
    print("\n" + "=" * 72, flush=True)
    print("🚀 Launching Full Live Sweep: linkedin_post_applier.py --live --pages 3", flush=True)
    print("=" * 72, flush=True)

    applier_cmd = [
        sys.executable,
        "linkedin_post_applier.py",
        "--live",
        "--pages",
        "3",
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(applier_cmd, env=env)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    wait_and_launch()
