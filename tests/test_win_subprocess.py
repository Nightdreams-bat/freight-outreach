"""win_subprocess injects no-window flags without disturbing the call."""

from types import SimpleNamespace

from kairo import win_subprocess


def test_no_window_is_int():
    assert isinstance(win_subprocess.NO_WINDOW, int)


def test_run_forwards_cmd_and_injects_creationflags(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(win_subprocess.subprocess, "run", fake_run)

    win_subprocess.run(["schtasks", "/Query"], text=True)

    assert seen["cmd"] == ["schtasks", "/Query"]
    assert seen["kwargs"]["text"] is True
    assert seen["kwargs"]["creationflags"] & win_subprocess.NO_WINDOW == win_subprocess.NO_WINDOW


def test_run_preserves_caller_creationflags(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        win_subprocess.subprocess, "run",
        lambda cmd, **kwargs: seen.update(kwargs) or SimpleNamespace(returncode=0),
    )

    win_subprocess.run(["x"], creationflags=0x1)

    assert seen["creationflags"] & 0x1
    assert seen["creationflags"] & win_subprocess.NO_WINDOW == win_subprocess.NO_WINDOW


def test_popen_forwards_cmd_and_injects_creationflags(monkeypatch):
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(win_subprocess.subprocess, "Popen", fake_popen)

    win_subprocess.popen(["msedge", "--app=x"])

    assert seen["cmd"] == ["msedge", "--app=x"]
    assert seen["kwargs"]["creationflags"] & win_subprocess.NO_WINDOW == win_subprocess.NO_WINDOW
