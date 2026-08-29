"""The `python -m kairo` / frozen-exe entry point (kairo/__main__.py)."""

from kairo import __main__ as entry


def test_scheduled_run_is_quiet_when_not_configured(monkeypatch, capsys):
    """An hourly --replies / --reminders task on a PC where Kairo was removed (no
    config.json) must NOT touch the data folder - it should just exit clean."""
    monkeypatch.setattr(entry, "_is_configured", lambda: False)

    def boom():
        raise AssertionError("ensure_data_dir() must not run for an unconfigured scheduled task")

    monkeypatch.setattr("kairo.paths.ensure_data_dir", boom)

    entry.main(["--replies"])
    entry.main(["--reminders"])
    assert "not configured" in capsys.readouterr().out


def test_scheduled_run_proceeds_when_configured(monkeypatch):
    monkeypatch.setattr(entry, "_is_configured", lambda: True)
    calls = []
    monkeypatch.setattr("kairo.paths.ensure_data_dir", lambda: calls.append("ensured"))
    monkeypatch.setattr("kairo.process_replies.main", lambda: calls.append("replies"))

    entry.main(["--replies"])
    assert calls == ["ensured", "replies"]
