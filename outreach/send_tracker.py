import json
from datetime import date, datetime
from pathlib import Path

TRACKER_PATH = Path(__file__).resolve().parent.parent / "send_log.json"
HISTORY_PATH = Path(__file__).resolve().parent.parent / "send_history.jsonl"
HISTORY_MAX_ENTRIES = 500


def _load():
    if TRACKER_PATH.exists():
        return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
    return {}


def _save(data):
    TRACKER_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def sent_today():
    return _load().get(str(date.today()), 0)


def remaining_today(daily_cap):
    return max(0, daily_cap - sent_today())


def record_sent(count=1):
    data = _load()
    today = str(date.today())
    data[today] = data.get(today, 0) + count
    if len(data) > 14:  # keep the file small, we only ever need "today"
        for old_day in sorted(data)[:-14]:
            del data[old_day]
    _save(data)


def record_send_history(kind, email, name, company, subject):
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "email": email,
        "name": name,
        "company": company,
        "subject": subject,
    }
    lines = []
    if HISTORY_PATH.exists():
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    lines.append(json.dumps(entry))
    lines = lines[-HISTORY_MAX_ENTRIES:]
    HISTORY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def recent_history(limit=100):
    if not HISTORY_PATH.exists():
        return []
    lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines if line.strip()]
    return list(reversed(entries))[:limit]
