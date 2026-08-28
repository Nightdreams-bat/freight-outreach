"""outreach.send_tracker warm-up ramp - effective_daily_cap / ensure_warmup_started."""

from datetime import date, timedelta

from outreach import send_tracker


def _cfg(**over):
    base = {
        "daily_send_cap": 100,
        "warmup_enabled": True,
        "warmup_start": 10,
        "warmup_step_per_day": 5,
        "warmup_started_on": "",
    }
    base.update(over)
    return base


def test_disabled_returns_raw_cap():
    assert send_tracker.effective_daily_cap(_cfg(warmup_enabled=False)) == 100


def test_not_started_returns_start():
    assert send_tracker.effective_daily_cap(_cfg()) == 10


def test_ramps_by_step_per_day():
    started = str(date.today() - timedelta(days=4))
    assert send_tracker.effective_daily_cap(_cfg(warmup_started_on=started)) == 30  # 10 + 5*4


def test_never_exceeds_ceiling():
    started = str(date.today() - timedelta(days=999))
    assert send_tracker.effective_daily_cap(_cfg(warmup_started_on=started)) == 100


def test_bad_started_on_falls_back_to_start():
    assert send_tracker.effective_daily_cap(_cfg(warmup_started_on="not-a-date")) == 10


def test_ensure_warmup_started_stamps_today(monkeypatch):
    saved = {}
    monkeypatch.setattr(send_tracker, "save_config", lambda c: saved.update(c))
    cfg = _cfg()
    send_tracker.ensure_warmup_started(cfg)
    assert cfg["warmup_started_on"] == str(date.today())
    assert saved["warmup_started_on"] == str(date.today())


def test_ensure_warmup_started_noop_when_already_set(monkeypatch):
    calls = []
    monkeypatch.setattr(send_tracker, "save_config", lambda c: calls.append(1))
    cfg = _cfg(warmup_started_on="2026-01-01")
    send_tracker.ensure_warmup_started(cfg)
    assert cfg["warmup_started_on"] == "2026-01-01"
    assert calls == []


def test_warmup_note_hidden_when_complete():
    started = str(date.today() - timedelta(days=999))
    assert send_tracker.warmup_note(_cfg(warmup_started_on=started)) == ""
    assert send_tracker.warmup_note(_cfg(warmup_enabled=False)) == ""


def test_warmup_note_shows_progress():
    note = send_tracker.warmup_note(_cfg())
    assert "10/day" in note and "100" in note
