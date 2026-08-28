"""Carrier vs shipper classification for a lead row.

Static keyword match, no AI and nothing written back to the sheet - mirrors
`scoring.score_lead`. Used to pick which opening-line hook snippet to drop into
the cold intro.

Precedence: lowercase `Company` + `Notes`, substring-match against
`segment_keywords_carrier` first, then `segment_keywords_shipper` (a carrier hit
wins a tie); default `"shipper"` when nothing matches.
"""

from outreach.config import get as cfg_get


def _keywords(cfg, key):
    try:
        return cfg_get(cfg, key) or []
    except KeyError:
        return []


def lead_segment(row, cfg):
    """Return "carrier" or "shipper" for a lead row."""
    haystack = " ".join(
        str(row.get(field) or "") for field in ("Company", "Notes")
    ).lower()

    for kw in _keywords(cfg, "segment_keywords_carrier"):
        if str(kw).strip() and str(kw).strip().lower() in haystack:
            return "carrier"
    for kw in _keywords(cfg, "segment_keywords_shipper"):
        if str(kw).strip() and str(kw).strip().lower() in haystack:
            return "shipper"
    return "shipper"
