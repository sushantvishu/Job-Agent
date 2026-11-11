"""
src/java_runner.py — Seamless Python-to-Java Subprocess Execution Engine.

Discovers system JDK/JRE installations, auto-compiles .java source files on demand
when .class bytecode is missing, and invokes Java routines safely with timeouts and JSON parsing.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add root directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import settings

logger = logging.getLogger("src.java_runner")


class JavaRunner:
    """Manages compilation and subprocess execution of Java components."""

    def __init__(self, src_dir: Path | None = None) -> None:
        self.src_dir = Path(src_dir or (BASE_DIR / "src"))
        self.java_source_file = self.src_dir / "JavaBridge.java"
        self.java_class_file = self.src_dir / "JavaBridge.class"
        self._java_cmd = self._find_executable("java")
        self._javac_cmd = self._find_executable("javac")

    def _find_executable(self, name: str) -> Optional[str]:
        """Locates the java/javac binary on system PATH or JAVA_HOME."""
        if settings.java_home:
            candidate = Path(settings.java_home) / "bin" / (f"{name}.exe" if sys.platform == "win32" else name)
            if candidate.exists():
                return str(candidate)

        # Fall back to shutil.which in current environment PATH
        return shutil.which(name)

    def is_java_available(self) -> bool:
        """Checks if a valid Java runtime environment is accessible."""
        if not self._java_cmd:
            return False
        try:
            res = subprocess.run(
                [self._java_cmd, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    def compile_if_needed(self) -> bool:
        """
        Auto-compilation hook:
        If JavaBridge.class does not exist or JavaBridge.java is newer,
        invokes javac to compile the bytecode cleanly.
        """
        if not self.java_source_file.exists():
            logger.warning("Java source file not found: %s", self.java_source_file)
            return False

        needs_compile = False
        if not self.java_class_file.exists():
            needs_compile = True
        elif self.java_source_file.stat().st_mtime > self.java_class_file.stat().st_mtime:
            needs_compile = True

        if not needs_compile:
            return True

        if not self._javac_cmd:
            logger.warning("javac compiler not found. Cannot compile JavaBridge.java. Ensure JDK is installed.")
            return False

        logger.info("Compiling %s with javac...", self.java_source_file.name)
        try:
            cmd = [self._javac_cmd, "-encoding", "UTF-8", str(self.java_source_file)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
            if res.returncode == 0:
                logger.info("Java compilation succeeded: %s", self.java_class_file.name)
                return True
            logger.error("Java compilation failed:\n%s", res.stderr)
            return False
        except Exception as exc:
            logger.error("Exception during Java compilation: %s", exc)
            return False

    def run_bridge(self, action: str, args: List[str] | None = None, timeout: int = 10) -> Dict[str, Any]:
        """
        Executes JavaBridge with specified arguments and parses the JSON stdout.
        Falls back to native Python calculation if Java is unavailable.
        """
        if not settings.java_enabled or not self.is_java_available():
            logger.debug("Java execution disabled or runtime missing. Using Python fallback logic.")
            return self._python_fallback(action, args or [])

        # Ensure class file is compiled
        self.compile_if_needed()

        cmd = [self._java_cmd, "-cp", str(self.src_dir), "JavaBridge", action] + (args or [])
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if res.returncode == 0:
                try:
                    return json.loads(res.stdout.strip())
                except json.JSONDecodeError:
                    return {"status": "success", "raw_output": res.stdout.strip()}
            else:
                logger.warning("Java execution exited with code %s: %s", res.returncode, res.stderr)
                return self._python_fallback(action, args or [])
        except Exception as exc:
            logger.warning("Failed to invoke Java subprocess (%s). Falling back to Python.", exc)
            return self._python_fallback(action, args or [])

    def _python_fallback(self, action: str, args: List[str]) -> Dict[str, Any]:
        """Zero-dependency pure Python fallback implementation for JavaBridge operations."""
        import hashlib

        if action == "hash":
            company = args[0] if len(args) > 0 else ""
            title = args[1] if len(args) > 1 else ""
            location = args[2] if len(args) > 2 else ""
            raw = f"{company.strip().lower()}|{title.strip().lower()}|{location.strip().lower()}"
            key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            return {"status": "success", "canonical_key": key, "engine": "python_fallback"}

        if action == "score":
            skills = [s.strip().lower() for s in (args[0].split(",") if args else []) if s.strip()]
            desc = args[1].lower() if len(args) > 1 else ""
            if not skills:
                return {"status": "success", "score": 0, "engine": "python_fallback"}
            matched = sum(1 for s in skills if s in desc)
            score = int(round((matched / len(skills)) * 100))
            return {"status": "success", "score": score, "engine": "python_fallback"}

        if action == "ping":
            return {"status": "pong", "engine": "python_fallback"}

        return {"status": "error", "message": f"Unsupported action: {action}"}


# Global runner instance
java_runner = JavaRunner()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing Java Subprocess Integration:")
    print(f"Java Available: {java_runner.is_java_available()}")
    res_ping = java_runner.run_bridge("ping")
    print(f"Ping Result: {res_ping}")
    res_hash = java_runner.run_bridge("hash", ["Google", "Senior Software Engineer", "Remote"])
    print(f"Hash Result: {res_hash}")
    res_score = java_runner.run_bridge("score", ["python,sql,docker,aws", "Looking for a Python engineer with SQL and Docker experience."])
    print(f"Score Result: {res_score}")
