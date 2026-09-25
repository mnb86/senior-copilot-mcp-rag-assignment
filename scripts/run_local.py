"""One-command local runner (Windows, macOS, Linux) - no PYTHONPATH or env setup needed.

    python scripts/run_local.py              # simulator :8000, MCP servers :9000 + :9100, backend :8080
    python scripts/run_local.py --frontend   # ...plus the Vite dev GUI on :5173 (needs Node.js / npm)

Then open http://localhost:8080 - the backend serves a pre-built GUI, so Node.js is optional.

Press Ctrl+C to stop everything.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_PATHS = [
    ROOT,
    ROOT / "apps" / "backend",
    ROOT / "mcp-servers" / "alarm-management",
    ROOT / "mcp-servers" / "optional-secondary-server",
]
# Local development defaults only (override via environment variables)
API_TOKEN = os.getenv("ALARM_API_TOKEN", "demo-token")
MCP_TOKEN = os.getenv("MCP_SERVER_TOKEN", "dev-mcp-token")
DOCS_MCP_TOKEN = os.getenv("DOCS_MCP_SERVER_TOKEN", "dev-docs-mcp-token")
INDEX_PATH = str(ROOT / "rag" / "retrieval" / ".index")

SERVICES = [
    (
        "alarm-api",
        ["-m", "alarm_simulator"],
        "http://127.0.0.1:8000/health",
        {
            "ALARM_API_TOKEN": API_TOKEN,
            "SIM_PORT": "8000",
            "SIM_FAULTS": "POST /alarms/correlation=503x1",
            "SIM_FAULT_CLIENTS": "alarm-mcp-server,alarm-copilot",
        },
    ),
    (
        "alarm-mcp",
        ["-m", "alarm_mcp"],
        "http://127.0.0.1:9000/healthz",
        {
            "ALARM_API_BASE_URL": "http://127.0.0.1:8000",
            "ALARM_API_TOKEN": API_TOKEN,
            "MCP_PORT": "9000",
            "MCP_SERVER_TOKEN": MCP_TOKEN,
        },
    ),
    (
        "docs-mcp",
        ["-m", "document_mcp"],
        "http://127.0.0.1:9100/healthz",
        {
            "DOCUMENT_PATH": str(ROOT / "rag" / "documents"),
            "RAG_INDEX_PATH": INDEX_PATH,
            "DOCS_MCP_PORT": "9100",
            "DOCS_MCP_SERVER_TOKEN": DOCS_MCP_TOKEN,
        },
    ),
    (
        "backend",
        ["-m", "copilot"],
        "http://127.0.0.1:8080/api/health",
        {
            "MCP_SERVER_URL": "http://127.0.0.1:9000/mcp",
            "MCP_SERVER_TOKEN": MCP_TOKEN,
            "DOCUMENT_PATH": str(ROOT / "rag" / "documents"),
            "RAG_INDEX_PATH": INDEX_PATH,
            "COPILOT_PORT": "8080",
        },
    ),
]


def check_dependencies() -> None:
    missing = []
    for mod in (
        "mcp",
        "starlette",
        "uvicorn",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "jsonschema",
        "numpy",
        "yaml",
        "pypdf",
    ):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        sys.exit(
            f"Missing Python packages: {', '.join(missing)}\nRun:  {sys.executable} -m pip install -r apps/backend/requirements.txt"
        )
    import importlib.metadata as md

    if md.version("mcp").split(".")[0] != "1":
        sys.exit('This project needs the MCP SDK v1. Run:  pip install "mcp>=1.27,<2"')


def pump(name: str, proc: subprocess.Popen[str]) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"[{name}] {line.rstrip()}", flush=True)


def wait_healthy(name: str, url: str, proc: subprocess.Popen[str], timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{name} exited with code {proc.returncode} (see its log lines above)")
        try:
            with urllib.request.urlopen(url, timeout=2):  # noqa: S310 - fixed localhost URL
                print(f"[runner] {name} is up: {url}", flush=True)
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"{name} did not become healthy at {url} within {timeout}s")


def start(name: str, cmd: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
    proc = subprocess.Popen(  # noqa: S603 - fixed local commands
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    threading.Thread(target=pump, args=(name, proc), daemon=True).start()
    return proc


def check_ports_free() -> None:
    """Fail fast if a port is taken: an old instance would otherwise answer the health checks."""
    busy = []
    for name, _, health, _ in SERVICES:
        port = int(health.split(":")[2].split("/")[0])
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(f"{port} ({name})")
    if busy:
        sys.exit(f"Port(s) already in use: {', '.join(busy)}. Stop the other instance (e.g. an earlier run) first.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the alarm copilot stack locally")
    parser.add_argument("--frontend", action="store_true", help="also start the Vite GUI (needs npm)")
    args = parser.parse_args()
    check_dependencies()
    check_ports_free()

    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = os.pathsep.join(str(p) for p in PYTHON_PATHS)
    base_env["PYTHONUNBUFFERED"] = "1"
    base_env.setdefault("LOG_LEVEL", "WARNING")
    procs: list[subprocess.Popen[str]] = []
    try:
        for name, argv, health, extra in SERVICES:
            proc = start(name, [sys.executable, *argv], {**base_env, **extra}, ROOT)
            procs.append(proc)
            wait_healthy(name, health, proc)
        if args.frontend:
            npm = shutil.which("npm")
            if not npm:
                print("[runner] npm not found - install Node.js LTS from https://nodejs.org to run the GUI", flush=True)
            else:
                web = ROOT / "apps" / "frontend"
                if not (web / "node_modules").exists():
                    print("[runner] installing frontend dependencies (first run only)...", flush=True)
                    subprocess.run([npm, "install"], cwd=web, check=True)  # noqa: S603
                procs.append(start("gui", [npm, "run", "dev"], base_env, web))
                print("[runner] GUI starting on http://localhost:5173", flush=True)
        print(
            "\n[runner] All services running.\n[runner] >>> Open the app: http://localhost:8080 <<<"
            + ("   (Vite dev GUI: http://localhost:5173)" if args.frontend else "")
            + "\n[runner] Press Ctrl+C to stop.\n",
            flush=True,
        )
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("[runner] a service stopped unexpectedly; shutting down", flush=True)
        return 1
    except KeyboardInterrupt:
        print("\n[runner] stopping...", flush=True)
        return 0
    except RuntimeError as exc:
        print(f"[runner] ERROR: {exc}", flush=True)
        return 1
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    raise SystemExit(main())
