"""Rules-based lead priority.

When the daily send cap can't fit every queued lead, the ones with the highest
score go out first. There is no AI here and nothing is written back to the sheet.

Precedence:
  1. A numeric value in the lead's own "Priority" column (if their sheet has one)
     is used verbatim - the client's explicit call always wins.
  2. Otherwise a small score is computed from `scoring_rules` / `scoring_keywords`
     in config.json.
"""

from outreach.config import get as cfg_get

_DEFAULT_RULES = {"has_company": 2, "has_phone": 1, "keyword_hit": 3}


def _as_number(value):
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def score_lead(row, cfg):
    """Return a comparable priority number for a lead row (higher = send sooner)."""
    manual = _as_number(row.get("Priority"))
    if manual is not None:
        return manual

    try:
        rules = cfg_get(cfg, "scoring_rules") or {}
    except KeyError:
        rules = {}
    rules = {**_DEFAULT_RULES, **rules}
    try:
        keywords = cfg_get(cfg, "scoring_keywords") or []
    except KeyError:
        keywords = []

    score = 0.0
    if str(row.get("Company") or "").strip():
        score += rules.get("has_company", 0)
    if str(row.get("Phone") or "").strip():
        score += rules.get("has_phone", 0)

    notes = str(row.get("Notes") or "").lower()
    if notes and any(str(kw).strip().lower() in notes for kw in keywords if str(kw).strip()):
        score += rules.get("keyword_hit", 0)

    return score


def is_manual(row):
    """True if the lead's Priority came from a number in their own sheet."""
    return _as_number(row.get("Priority")) is not None
