"""Start FastAPI backend and Vue SPA (web/) for local dev."""
from __future__ import annotations

import argparse
import atexit
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

from backend.config import settings as be_settings

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
processes: list[subprocess.Popen] = []


def cleanup() -> None:
    print("Shutting down all services...")
    for process in processes:
        try:
            process.terminate()
        except Exception as e:
            print(f"Error during cleanup: {e}")


def start_backend(port: int = 8000, log_level: str = "info") -> subprocess.Popen:
    print(f"Starting backend on port {port}...")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        f"--port={port}",
        f"--log-level={log_level}",
        "--host=127.0.0.1",
    ]
    process = subprocess.Popen(cmd, cwd=str(ROOT))
    processes.append(process)
    return process


def start_frontend(port: int = 5173, api_url: str = "http://127.0.0.1:8000") -> subprocess.Popen:
    if not (WEB_DIR / "package.json").is_file():
        raise FileNotFoundError(f"Vue app missing: {WEB_DIR}")
    print(f"Starting Vue frontend on port {port} (proxy -> {api_url})...")
    env = os.environ.copy()
    env["VITE_PROXY_TARGET"] = api_url
    # npm on Windows
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    cmd = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)]
    process = subprocess.Popen(cmd, cwd=str(WEB_DIR), env=env)
    processes.append(process)
    return process


def start_frontend_separately() -> None:
    """CLI entry: Vue only (backend must already be up)."""
    atexit.register(cleanup)
    api = os.environ.get("API_URL", "http://127.0.0.1:8000")
    port = int(os.environ.get("FRONTEND_PORT", "5173"))
    start_frontend(port=port, api_url=api)
    print(f"Vue UI: http://127.0.0.1:{port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()
        sys.exit(0)


def is_backend_ready(api_url: str) -> bool:
    try:
        response = requests.get(f"{api_url.rstrip('/')}/ping", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        print("waiting for backend...")
        return False


def start_all(
    backend_port: int = 8000,
    frontend_port: int = 5173,
    log_level: str = "info",
) -> None:
    atexit.register(cleanup)
    api_url = f"http://127.0.0.1:{backend_port}"
    start_backend(port=backend_port, log_level=log_level)
    for _ in range(120):
        if is_backend_ready(api_url):
            break
        time.sleep(1)
    else:
        print("Backend did not become ready in time", file=sys.stderr)
        cleanup()
        sys.exit(1)

    start_frontend(port=frontend_port, api_url=api_url)
    print(f"Backend:  {api_url}")
    print(f"Frontend: http://127.0.0.1:{frontend_port}")
    print("Press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()
        sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start KB backend + Vue frontend")
    parser.add_argument("--backend-port", type=int, default=be_settings.SERVER_PORT)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument(
        "--log-level",
        default=getattr(be_settings, "SERVER_LOG_LEVEL", "info"),
        choices=["debug", "info", "warning", "error", "critical"],
    )
    args = parser.parse_args()
    start_all(
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
