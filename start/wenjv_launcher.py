"""Helpers for start-wenjv.bat: pick free port, write frontend.env API_URL, wait health."""
from __future__ import annotations

import argparse
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def pick_port(host: str, start: int, count: int = 30) -> int:
    last_err: Exception | None = None
    for port in range(int(start), int(start) + int(count)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Do NOT set SO_REUSEADDR here: on Windows it can make bind succeed
            # on a port that is not actually free for a new listener.
            s.bind((host, port))
            chosen = port
            s.close()
            return chosen
        except OSError as e:
            last_err = e
            try:
                s.close()
            except Exception:
                pass
    raise OSError(
        f"No free TCP port in {start}..{start + count - 1} on {host}: {last_err}"
    )


def get_config_dir() -> Path:
    """Same resolution rules as backend.core.paths.resolve_base_dir."""
    try:
        from backend.core.paths import resolve_base_dir

        return Path(resolve_base_dir())
    except Exception:
        # Extremely defensive: mirror A+ rules with stdlib only
        base = Path(os.path.expanduser("~")) / ".config"
        primary = base / "wenjv"
        fallback = base / "inquisitive"

        def _has(p: Path) -> bool:
            if not p.is_dir():
                return False
            for name in (
                "wenjv.db",
                "inquisitive.db",
                "backend.env",
                "frontend.env",
                "cache.db",
                "lance_db",
                "uploads",
            ):
                c = p / name
                if c.is_file() and c.stat().st_size > 0:
                    return True
                if c.is_dir():
                    try:
                        next(c.iterdir())
                        return True
                    except StopIteration:
                        pass
            return False

        if _has(primary):
            return primary
        if _has(fallback):
            return fallback
        return primary


def write_frontend_api_url(api_url: str) -> Path:
    home = get_config_dir()
    # mkdir only after resolve — never create empty wenjv while legacy has data
    home.mkdir(parents=True, exist_ok=True)
    path = home / "frontend.env"
    lines: list[str] = []
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
    out: list[str] = []
    seen = False
    for line in lines:
        if line.strip().startswith("API_URL="):
            out.append(f"API_URL={api_url}")
            seen = True
        else:
            out.append(line)
    if not seen:
        if out and out[-1].strip():
            out.append("")
        out.append(f"API_URL={api_url}")
    if not out or not out[0].lstrip().startswith("#"):
        out.insert(0, "# Frontend environment variables for wenjv (问据)")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def wait_health(url: str, timeout: float = 45.0, interval: float = 0.75) -> int:
    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.5) as resp:
                code = int(getattr(resp, "status", 200) or 200)
                if 200 <= code < 500:
                    print(f"OK {url} -> {code}")
                    return 0
                last_err = f"HTTP {code}"
        except urllib.error.HTTPError as e:
            if e.code in (200, 503):
                print(f"OK {url} -> {e.code}")
                return 0
            last_err = f"HTTPError {e.code}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(interval)
    print(f"FAIL wait_health {url} last={last_err}", file=sys.stderr)
    return 1


def prepare(host: str, start: int, count: int, out_file: Path) -> int:
    """Write KEY=value lines for cmd.exe `set /p` / for /f friendly file."""
    try:
        port = pick_port(host, start, count)
    except OSError as e:
        print(str(e), file=sys.stderr)
        return 1
    api_url = f"http://{host}:{port}"
    write_frontend_api_url(api_url)
    # ASCII-only, one key per line, no spaces around =
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(
        f"BACKEND_PORT={port}\nAPI_URL={api_url}\n",
        encoding="ascii",
        newline="\n",
    )
    print(f"BACKEND_PORT={port}")
    print(f"API_URL={api_url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_pick = sub.add_parser("pick-port")
    p_pick.add_argument("--host", default="127.0.0.1")
    p_pick.add_argument("--start", type=int, default=8000)
    p_pick.add_argument("--count", type=int, default=30)

    p_write = sub.add_parser("write-api-url")
    p_write.add_argument("--url", required=True)

    p_wait = sub.add_parser("wait-health")
    p_wait.add_argument("--url", required=True)
    p_wait.add_argument("--timeout", type=float, default=60.0)

    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("--host", default="127.0.0.1")
    p_prep.add_argument("--start", type=int, default=8000)
    p_prep.add_argument("--count", type=int, default=30)
    p_prep.add_argument(
        "--out",
        required=True,
        help="Path to write BACKEND_PORT= / API_URL= lines",
    )

    args = p.parse_args(argv)
    if args.cmd == "pick-port":
        try:
            print(pick_port(args.host, args.start, args.count))
            return 0
        except OSError as e:
            print(str(e), file=sys.stderr)
            return 1
    if args.cmd == "write-api-url":
        path = write_frontend_api_url(args.url)
        print(str(path))
        return 0
    if args.cmd == "wait-health":
        return wait_health(args.url, timeout=args.timeout)
    if args.cmd == "prepare":
        return prepare(args.host, args.start, args.count, Path(args.out))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
