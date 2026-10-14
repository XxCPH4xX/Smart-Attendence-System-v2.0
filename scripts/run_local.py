import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))


def healthy(port, backend=False):
    path = "/openapi.json" if backend else "/_stcore/health"
    try:
        with HTTP.open(f"http://127.0.0.1:{port}{path}", timeout=1) as response:
            content = response.read()
        if backend:
            document = json.loads(content)
            info = document.get("info") if isinstance(document, dict) else None
            return isinstance(info, dict) and info.get("title") == "Smart Attendance API"
        return content.strip() == b"ok"
    except (URLError, OSError, ValueError):
        return False


def port_in_use(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def run(api_port=8000, dashboard_port=8501):
    children = []
    api_url = f"http://127.0.0.1:{api_port}"
    dashboard_url = f"http://127.0.0.1:{dashboard_port}"
    environment = {
        **os.environ,
        "ATTENDANCE_API_URL": api_url,
        "ATTENDANCE_DASHBOARD_URL": dashboard_url,
    }
    services = [
        (
            "Backend",
            api_port,
            True,
            [
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
                "--workers",
                "1",
                "--no-access-log",
            ],
        ),
        (
            "Dashboard",
            dashboard_port,
            False,
            [
                "streamlit",
                "run",
                "frontend/app.py",
                "--server.address=127.0.0.1",
                f"--server.port={dashboard_port}",
                "--server.headless=true",
            ],
        ),
    ]
    try:
        for name, port, backend, command in services:
            if port_in_use(port):
                if not healthy(port, backend):
                    raise RuntimeError(
                        f"Port {port} is busy. Close the program using it and retry."
                    )
                print(f"{name} is already running.", flush=True)
                continue
            print(f"Starting {name.lower()}…", flush=True)
            process = subprocess.Popen(
                [sys.executable, "-m", *command],
                cwd=ROOT,
                env=environment,
                start_new_session=True,
            )
            children.append((name, process))
            deadline = time.monotonic() + 30
            while not healthy(port, backend):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} could not start. See the error above.")
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"{name} did not become ready within 30 seconds.")
                time.sleep(0.25)
        print(f"\nSmart Attendance: {dashboard_url}", flush=True)
        if not children:
            return 0
        print(
            "Keep this terminal open. Press Ctrl+C to stop the services started here.\n", flush=True
        )
        while True:
            for name, process in children:
                if process.poll() is not None:
                    raise RuntimeError(f"{name} stopped unexpectedly. Run ./run.sh to restart.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping Smart Attendance…", flush=True)
        return 0
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        for _, process in children:
            if process.poll() is None:
                process.terminate()
        for _, process in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description="Start Smart Attendance locally")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--port", type=int, default=8501, help="Dashboard port (default: 8501)")
    args = parser.parse_args()
    if not all(1 <= port <= 65535 for port in (args.api_port, args.port)):
        parser.error("Ports must be between 1 and 65535.")
    if args.api_port == args.port:
        parser.error("Backend and dashboard need different ports.")
    return run(args.api_port, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
