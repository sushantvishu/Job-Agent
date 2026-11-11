"""
app/shutdown.py — Graceful shutdown and resource cleanup for Job Agent.

Registers OS signal handlers (SIGINT, SIGTERM, and on Windows CTRL_BREAK)
so that any open resources are released cleanly whether the agent exits
normally, is interrupted by Ctrl-C, or crashes.

Usage (call once at process start-up, e.g. in auto_apply_all.py or main.py):

    from app.shutdown import ShutdownManager
    sm = ShutdownManager(logger)
    sm.register()                        # installs signal handlers
    sm.register_browser(browser_session) # optional — track a BrowserSession
    sm.register_db_connection(conn)      # optional — track a raw sqlite3.Connection

    # Then in your finally / cleanup block:
    sm.cleanup()
"""
from __future__ import annotations

import atexit
import logging
import signal
import sqlite3
import sys
import threading
from typing import Any

_logger = logging.getLogger(__name__)


class ShutdownManager:
    """Central resource registry that guarantees cleanup on exit or crash.

    Tracks:
    - BrowserSession instances (Playwright browser + context)
    - Raw sqlite3.Connection objects
    - Any custom callable registered via ``register_cleanup``

    Thread-safe: cleanup is guarded by a lock and can only run once.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or _logger
        self._lock = threading.Lock()
        self._cleaned_up = False

        self._browser_sessions: list[Any] = []   # BrowserSession instances
        self._db_connections: list[sqlite3.Connection] = []
        self._custom_hooks: list[tuple[str, Any]] = []  # (label, callable)

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def register_browser(self, session: Any) -> None:
        """Track a BrowserSession so it is closed on shutdown."""
        if session not in self._browser_sessions:
            self._browser_sessions.append(session)

    def unregister_browser(self, session: Any) -> None:
        """Stop tracking a BrowserSession (e.g. after it was already closed)."""
        try:
            self._browser_sessions.remove(session)
        except ValueError:
            pass

    def register_db_connection(self, conn: sqlite3.Connection) -> None:
        """Track a raw sqlite3.Connection so it is closed on shutdown."""
        if conn not in self._db_connections:
            self._db_connections.append(conn)

    def unregister_db_connection(self, conn: sqlite3.Connection) -> None:
        try:
            self._db_connections.remove(conn)
        except ValueError:
            pass

    def register_cleanup(self, label: str, fn: Any) -> None:
        """Register any zero-argument callable to be called during cleanup.

        Example::

            sm.register_cleanup("close redis", redis_client.close)
        """
        self._custom_hooks.append((label, fn))

    # ------------------------------------------------------------------
    # Signal handler registration
    # ------------------------------------------------------------------

    def register(self) -> None:
        """Install OS-level signal handlers and an atexit hook."""
        # atexit covers normal interpreter exit (sys.exit, end of script)
        atexit.register(self.cleanup)

        # SIGINT  → Ctrl-C
        # SIGTERM → kill / system shutdown / daemon termination
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle_signal)
            except (OSError, ValueError):
                # signal() can fail if not called from the main thread
                pass

        # Windows-only: CTRL_BREAK_EVENT sent by taskkill /F, plus Windows Disconnection events
        if sys.platform == "win32":
            try:
                signal.signal(signal.SIGBREAK, self._handle_signal)  # type: ignore[attr-defined]
            except (OSError, AttributeError, ValueError):
                pass

            # Register Windows low-level console control handler for terminal closure,
            # user logoff, Windows remote session disconnection, or OS shutdown
            try:
                import ctypes

                HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)

                def _win_ctrl_handler(ctrl_type: int) -> bool:
                    events = {
                        0: "CTRL_C_EVENT",
                        1: "CTRL_BREAK_EVENT",
                        2: "CTRL_CLOSE_EVENT (Windows Console Closed)",
                        5: "CTRL_LOGOFF_EVENT (Windows Session Disconnected / Logoff)",
                        6: "CTRL_SHUTDOWN_EVENT (Windows System Shutdown)",
                    }
                    event_name = events.get(ctrl_type, f"CTRL_EVENT_{ctrl_type}")
                    self._logger.warning(
                        "Windows event detected: %s. Initiating emergency fail-safe cleanup sequence...",
                        event_name,
                    )
                    print(f"\n[Job Agent Emergency Fail-Safe] Windows event: {event_name}")
                    self.cleanup()
                    return True

                self._win_handler_ref = HandlerRoutine(_win_ctrl_handler)
                ctypes.windll.kernel32.SetConsoleCtrlHandler(self._win_handler_ref, True)
                self._logger.info("ShutdownManager: Windows console/disconnection handler registered.")
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Could not register Windows SetConsoleCtrlHandler: %s", exc)

        self._logger.info("ShutdownManager: signal handlers registered.")

    def _handle_signal(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        self._logger.warning(
            "Job Agent: received %s — performing graceful shutdown. Please wait...", sig_name
        )
        print(f"\n[Job Agent] Signal {sig_name} received — cleaning up resources, please wait...")
        self.cleanup()
        # Re-raise as KeyboardInterrupt so any outer try/except sees it
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        sys.exit(0)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Close all tracked resources exactly once, in a safe order.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        with self._lock:
            if self._cleaned_up:
                return
            self._cleaned_up = True

        self._logger.info("ShutdownManager: starting cleanup of all tracked resources...")
        print("\n[Job Agent] Closing all resources (browser, database, connections)...")

        # 1. Custom hooks first (highest-level, e.g. flush queues)
        for label, fn in reversed(self._custom_hooks):
            self._safe_call(label, fn)

        # 2. Browser sessions (Playwright is heavy — close before DB)
        for session in list(self._browser_sessions):
            self._close_browser(session)
        self._browser_sessions.clear()

        # 3. Raw SQLite connections
        for conn in list(self._db_connections):
            self._close_db(conn)
        self._db_connections.clear()

        # 4. Stop local Ollama process to release system RAM
        self._stop_ollama()

        self._logger.info("ShutdownManager: all resources released.")
        print("[Job Agent] ✓ All resources released cleanly (RAM conserved).")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _stop_ollama(self) -> None:
        try:
            import requests

            # Unload active Ollama models cleanly to free GPU/RAM without terminating external system processes
            requests.post("http://127.0.0.1:11434/api/generate", json={"keep_alive": 0}, timeout=2)
            self._logger.info("ShutdownManager: unloaded Ollama models to conserve RAM.")
        except Exception:
            pass

    def _close_browser(self, session: Any) -> None:
        try:
            if hasattr(session, "close"):
                session.close()
                self._logger.info("ShutdownManager: browser session closed.")
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("ShutdownManager: error closing browser session: %s", exc)

        # Fail-safe: release any lingering SingletonLock in browser profile directory
        try:
            import glob
            import os
            profile_dir = getattr(session, "profile_dir", None) or os.path.join(os.getcwd(), "browser-profile")
            if os.path.isdir(profile_dir):
                for lock in glob.glob(os.path.join(profile_dir, "Singleton*")):
                    try:
                        os.remove(lock)
                        self._logger.debug("ShutdownManager: removed lingering browser lockfile: %s", lock)
                    except Exception:
                        pass
        except Exception:
            pass

    def _close_db(self, conn: sqlite3.Connection) -> None:
        try:
            conn.close()
            self._logger.info("ShutdownManager: database connection closed.")
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("ShutdownManager: error closing DB connection: %s", exc)

    def _safe_call(self, label: str, fn: Any) -> None:
        try:
            fn()
            self._logger.info("ShutdownManager: cleanup hook '%s' completed.", label)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("ShutdownManager: cleanup hook '%s' failed: %s", label, exc)

