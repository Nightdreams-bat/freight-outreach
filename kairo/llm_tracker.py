"""Monthly Claude-call counter - the LLM spend guardrail.

Mirrors `kairo/send_tracker.py`: a tiny JSON dict keyed by calendar month
(`{"YYYY-MM": int}`), read/modified/written under `data_lock()`, pruned to the
last few months so the file never grows.

Nothing here calls Anthropic; callers record a call after it succeeds and check
`remaining_this_month()` before making the next one.
"""

import json
from datetime import date

from kairo.locking import data_lock
from kairo.paths import LLM_CALLS_PATH


def _month_key(d=None):
    return (d or date.today()).strftime("%Y-%m")


def _load():
    if LLM_CALLS_PATH.exists():
        return json.loads(LLM_CALLS_PATH.read_text(encoding="utf-8"))
    return {}


def _save(data):
    LLM_CALLS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def calls_this_month():
    return _load().get(_month_key(), 0)


def remaining_this_month(cap):
    return max(0, cap - calls_this_month())


def record_llm_call(n=1):
    with data_lock():
        data = _load()
        month = _month_key()
        data[month] = data.get(month, 0) + n
        if len(data) > 3:  # we only ever need the current month; keep a little history
            for old_month in sorted(data)[:-3]:
                del data[old_month]
        _save(data)
