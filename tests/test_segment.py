"""outreach.segment - static carrier/shipper classification of a lead row."""

from outreach import segment

CFG = {
    "segment_keywords_carrier": ["trucking", "owner operator", "reefer"],
    "segment_keywords_shipper": ["manufacturing", "warehouse"],
}


def test_carrier_keyword_in_company():
    assert segment.lead_segment({"Company": "Blue Line Trucking", "Notes": ""}, CFG) == "carrier"


def test_shipper_keyword_in_notes():
    assert segment.lead_segment({"Company": "Acme Co", "Notes": "big warehouse operation"}, CFG) == "shipper"


def test_carrier_wins_a_tie():
    row = {"Company": "Acme Manufacturing", "Notes": "runs its own reefer fleet"}
    assert segment.lead_segment(row, CFG) == "carrier"


def test_default_is_shipper():
    assert segment.lead_segment({"Company": "Nondescript LLC", "Notes": ""}, CFG) == "shipper"


def test_empty_cfg_uses_default_keyword_lists():
    # cfg_get falls back to config DEFAULTS, which include "trucking".
    assert segment.lead_segment({"Company": "Blue Line Trucking"}, {}) == "carrier"
    assert segment.lead_segment({"Company": "Plain Co"}, {}) == "shipper"
