import os
import signal
import socket
import subprocess
import time
from io import BytesIO

import pytest

from scripts import run_local


@pytest.mark.parametrize("content", [b"[]", b'{"info": null}', b'{"info": {"title": "Other API"}}'])
def test_health_check_rejects_unrelated_services(content, monkeypatch):
    monkeypatch.setattr(run_local.HTTP, "open", lambda *args, **kwargs: BytesIO(content))
    assert not run_local.healthy(8000, backend=True)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def launch(tmp_path, api_port, dashboard_port, log):
    return subprocess.Popen(
        [
            str(run_local.ROOT / "run.sh"),
            "--api-port",
            str(api_port),
            "--port",
            str(dashboard_port),
        ],
        cwd=tmp_path,
        env={**os.environ, "ATTENDANCE_DATABASE_URL": f"sqlite:///{tmp_path / 'launcher.db'}"},
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def stop(process):
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    process.wait(timeout=15)


@pytest.mark.skipif(os.name == "nt", reason="The shell entry point is for macOS and Linux")
def test_launcher_starts_reuses_and_stops_services_from_another_directory(tmp_path):
    api_port, dashboard_port = free_port(), free_port()
    log_path = tmp_path / "launch.log"
    with log_path.open("w") as log:
        process = launch(tmp_path, api_port, dashboard_port, log)
        try:
            deadline = time.monotonic() + 40
            while (
                f"Smart Attendance: http://127.0.0.1:{dashboard_port}" not in log_path.read_text()
            ):
                assert process.poll() is None, log_path.read_text()
                assert time.monotonic() < deadline, log_path.read_text()
                time.sleep(0.2)
            assert run_local.healthy(api_port, backend=True)
            assert run_local.healthy(dashboard_port)
            reused = launch(tmp_path, api_port, dashboard_port, log)
            try:
                assert reused.wait(timeout=10) == 0, log_path.read_text()
            finally:
                stop(reused)
            assert "Backend is already running." in log_path.read_text()
            assert "Dashboard is already running." in log_path.read_text()
            assert process.poll() is None
        finally:
            stop(process)
    assert process.returncode == 0, log_path.read_text()
    assert not run_local.port_in_use(api_port)
    assert not run_local.port_in_use(dashboard_port)


@pytest.mark.skipif(os.name == "nt", reason="The shell entry point is for macOS and Linux")
def test_dashboard_port_conflict_cleans_up_only_the_started_backend(tmp_path):
    with socket.socket() as other_service:
        other_service.bind(("127.0.0.1", 0))
        other_service.listen()
        dashboard_port = other_service.getsockname()[1]
        api_port = free_port()
        log_path = tmp_path / "conflict.log"
        with log_path.open("w") as log:
            process = launch(tmp_path, api_port, dashboard_port, log)
            try:
                assert process.wait(timeout=40) == 1, log_path.read_text()
            finally:
                stop(process)
        assert f"Port {dashboard_port} is busy" in log_path.read_text()
        assert not run_local.port_in_use(api_port)
        assert other_service.fileno() >= 0


@pytest.mark.parametrize("arguments", [["--port", "0"], ["--port", "8000"]])
def test_invalid_ports_fail_before_starting_services(arguments, monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_local", *arguments])
    monkeypatch.setattr(run_local, "run", lambda *args: pytest.fail("Must not start services"))
    with pytest.raises(SystemExit) as error:
        run_local.main()
    assert error.value.code == 2
