"""outreach/scoring.py - rules-based lead priority."""

from outreach.core import apply_daily_cap, priority_sort_key
from outreach.scoring import is_manual, score_lead

CFG = {
    "scoring_rules": {"has_company": 2, "has_phone": 1, "keyword_hit": 3},
    "scoring_keywords": ["urgent", "lane"],
}


def test_manual_priority_wins():
    row = {"Priority": "9", "Company": "", "Phone": "", "Notes": ""}
    assert score_lead(row, CFG) == 9
    assert is_manual(row) is True


def test_non_numeric_priority_falls_back_to_computed():
    row = {"Priority": "high", "Company": "Acme", "Phone": "555", "Notes": ""}
    assert score_lead(row, CFG) == 3  # 2 + 1
    assert is_manual(row) is False


def test_each_rule_contributes():
    assert score_lead({"Company": "Acme"}, CFG) == 2
    assert score_lead({"Phone": "555"}, CFG) == 1
    assert score_lead({"Notes": "this is URGENT"}, CFG) == 3
    assert score_lead({"Company": "A", "Phone": "5", "Notes": "new lane"}, CFG) == 6


def test_missing_everything_is_zero():
    assert score_lead({}, CFG) == 0


def test_defaults_used_when_config_lacks_scoring_keys():
    # cfg without scoring_rules/keywords -> falls back to config.DEFAULTS
    assert score_lead({"Company": "Acme", "Notes": "need a quote"}, {}) == 5  # 2 + 3


def test_priority_sort_key_orders_high_first_through_cap(monkeypatch):
    monkeypatch.setattr("outreach.core.remaining_today", lambda cap: cap)
    cands = [
        (2, {"Company": "", "Phone": ""}),          # score 0
        (3, {"Priority": "10"}),                    # score 10
        (4, {"Company": "X", "Phone": "1"}),        # score 3
    ]
    kept, _, deferred = apply_daily_cap(cands, daily_cap=2, sort_key=priority_sort_key(CFG))
    assert [c[0] for c in kept] == [3, 4]
    assert deferred == 1
