"""Wave 3: schedule_task generalised for both the reminder and reply scans."""

from types import SimpleNamespace

import pytest

from kairo import schedule_task, win_subprocess


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return SimpleNamespace(returncode=0, stdout="OK", stderr="")

    # Patch the underlying subprocess.run so win_subprocess still injects
    # its no-window creationflags on the way through.
    monkeypatch.setattr(win_subprocess.subprocess, "run", fake_run)
    # Deterministic command string regardless of the machine running the test.
    monkeypatch.setattr(schedule_task, "_task_command", lambda flag: f"RUN {flag}")
    return calls


def _tr_value(cmd):
    return cmd[cmd.index("/TR") + 1]


def _tn_value(cmd):
    return cmd[cmd.index("/TN") + 1]


def test_register_reminder_task_defaults(captured):
    ok, _ = schedule_task.register_task(3)
    assert ok
    cmd = captured[0]["cmd"]
    assert _tn_value(cmd) == schedule_task.REMINDER_TASK_NAME
    assert _tr_value(cmd) == "RUN --reminders"
    assert cmd[cmd.index("/MO") + 1] == "3"
    # Scheduling calls route through win_subprocess, which suppresses the
    # console flash by OR-ing in NO_WINDOW.
    assert captured[0]["kwargs"]["creationflags"] & win_subprocess.NO_WINDOW == win_subprocess.NO_WINDOW


def test_register_reply_task(captured):
    ok, _ = schedule_task.register_task(
        1, schedule_task.REPLY_TASK_NAME, "--replies"
    )
    assert ok
    cmd = captured[0]["cmd"]
    assert _tn_value(cmd) == schedule_task.REPLY_TASK_NAME
    assert _tr_value(cmd) == "RUN --replies"


def test_unregister_named_task(captured):
    schedule_task.unregister_task(schedule_task.REPLY_TASK_NAME)
    cmd = captured[0]["cmd"]
    assert cmd[:2] == ["schtasks", "/Delete"]
    assert _tn_value(cmd) == schedule_task.REPLY_TASK_NAME


def test_task_status_none_when_missing(monkeypatch):
    monkeypatch.setattr(
        win_subprocess.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="ERROR"),
    )
    assert schedule_task.task_status(schedule_task.REPLY_TASK_NAME) is None


def test_task_status_parses_list_output(monkeypatch):
    out = "TaskName: x\nStatus: Ready\nNext Run Time: 1/1/2030 9:00:00 AM\n"
    monkeypatch.setattr(
        win_subprocess.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=out, stderr=""),
    )
    status = schedule_task.task_status()
    assert status["registered"] and status["status"] == "Ready"
    assert status["next_run"].startswith("1/1/2030")


def test_backcompat_alias():
    assert schedule_task.TASK_NAME == schedule_task.REMINDER_TASK_NAME


def test_task_command_source_checkout_uses_pythonw(monkeypatch):
    monkeypatch.setattr(schedule_task.sys, "frozen", False, raising=False)
    cmd = schedule_task._task_command("--reminders")
    assert cmd.endswith("-m kairo --reminders")


def test_task_command_frozen_uses_hidden_wrapper(monkeypatch, tmp_path):
    monkeypatch.setattr(schedule_task.sys, "frozen", True, raising=False)
    monkeypatch.setattr(schedule_task.sys, "executable", str(tmp_path / "Kairo.exe"))
    monkeypatch.setattr("kairo.paths.data_dir", lambda: tmp_path)

    cmd = schedule_task._task_command("--replies")

    vbs = tmp_path / "run-hidden.vbs"
    assert vbs.exists()
    assert cmd.startswith("wscript.exe //nologo //B ")
    assert str(vbs) in cmd
    assert cmd.endswith("--replies")
    body = vbs.read_text(encoding="utf-8")
    assert "WScript.Shell" in body and ", 0, False" in body
