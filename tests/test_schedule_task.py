"""Wave 3: schedule_task generalised for both the reminder and reply scans."""

from types import SimpleNamespace

import pytest

from outreach import schedule_task


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return SimpleNamespace(returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(schedule_task.subprocess, "run", fake_run)
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
        schedule_task.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="ERROR"),
    )
    assert schedule_task.task_status(schedule_task.REPLY_TASK_NAME) is None


def test_task_status_parses_list_output(monkeypatch):
    out = "TaskName: x\nStatus: Ready\nNext Run Time: 1/1/2030 9:00:00 AM\n"
    monkeypatch.setattr(
        schedule_task.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=out, stderr=""),
    )
    status = schedule_task.task_status()
    assert status["registered"] and status["status"] == "Ready"
    assert status["next_run"].startswith("1/1/2030")


def test_backcompat_alias():
    assert schedule_task.TASK_NAME == schedule_task.REMINDER_TASK_NAME
