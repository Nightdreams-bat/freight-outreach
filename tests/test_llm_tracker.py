"""Wave A: monthly Claude-call counter (outreach/llm_tracker.py)."""

import contextlib
import datetime

import pytest

from outreach import llm_tracker


class FakeDate(datetime.date):
    _today = datetime.date(2026, 8, 15)

    @classmethod
    def today(cls):
        return cls._today


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_tracker, "LLM_CALLS_PATH", tmp_path / "llm_calls.json")
    monkeypatch.setattr(llm_tracker, "data_lock", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(llm_tracker, "date", FakeDate)
    FakeDate._today = datetime.date(2026, 8, 15)


def _set_today(y, m, d):
    FakeDate._today = datetime.date(y, m, d)


def test_records_and_counts_within_a_month():
    assert llm_tracker.calls_this_month() == 0
    llm_tracker.record_llm_call()
    llm_tracker.record_llm_call(3)
    assert llm_tracker.calls_this_month() == 4


def test_month_rollover_resets_the_visible_count():
    llm_tracker.record_llm_call(5)
    assert llm_tracker.calls_this_month() == 5
    _set_today(2026, 9, 1)
    assert llm_tracker.calls_this_month() == 0
    llm_tracker.record_llm_call(2)
    assert llm_tracker.calls_this_month() == 2


def test_remaining_this_month_math():
    llm_tracker.record_llm_call(7)
    assert llm_tracker.remaining_this_month(10) == 3
    assert llm_tracker.remaining_this_month(7) == 0
    assert llm_tracker.remaining_this_month(5) == 0  # never negative


def test_prune_keeps_only_last_three_months():
    for month in range(1, 7):  # Jan..Jun 2026
        _set_today(2026, month, 10)
        llm_tracker.record_llm_call()
    import json

    data = json.loads((llm_tracker.LLM_CALLS_PATH).read_text(encoding="utf-8"))
    assert sorted(data) == ["2026-04", "2026-05", "2026-06"]
