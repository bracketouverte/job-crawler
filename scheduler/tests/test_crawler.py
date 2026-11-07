import subprocess

import config
import crawler
import state


def test_run_crawler_success_records_run_and_does_not_notify(monkeypatch, runs_file):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    notified = []
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(crawler, "send_failure_notification", lambda msg: notified.append(msg))

    crawler.run_crawler()

    assert captured["cmd"] == [
        "docker",
        "compose",
        "-f",
        f"{config.PROJECT_DIR}/docker-compose.yml",
        "--project-directory",
        config.PROJECT_DIR,
        "run",
        "--rm",
        config.CRAWLER_SERVICE_NAME,
    ]
    assert notified == []
    assert len(state.read_runs()) == 1


def test_run_crawler_failure_logs_and_notifies_but_still_records_run(monkeypatch, runs_file):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr="boom: stack trace")

    notified = []
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(crawler, "send_failure_notification", lambda msg: notified.append(msg))

    crawler.run_crawler()

    assert notified == ["boom: stack trace"]
    assert len(state.read_runs()) == 1


def test_run_crawler_timeout_is_caught_and_notifies(monkeypatch, runs_file):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=3600)

    notified = []
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(crawler, "send_failure_notification", lambda msg: notified.append(msg))

    crawler.run_crawler()  # must not raise

    assert len(notified) == 1
    assert "timed out" in notified[0]
    assert len(state.read_runs()) == 1


def test_run_crawler_missing_docker_binary_is_caught_and_notifies(monkeypatch, runs_file):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "docker")

    notified = []
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(crawler, "send_failure_notification", lambda msg: notified.append(msg))

    crawler.run_crawler()  # must not raise — FileNotFoundError is an OSError

    assert len(notified) == 1
    assert "Could not invoke docker" in notified[0]
    assert len(state.read_runs()) == 1
