"""Read inbound replies from Gmail so they can be classified and acted on.

Read-only counterpart to `mailer.py`. Needs the `gmail.readonly` scope (added to
`gmail_oauth.SCOPES`). Never sends anything.

Which messages have already been handled is tracked in a small JSON file next to
config.json, keyed by Gmail message id - so a reply is classified exactly once
even though the scan runs hourly.
"""

import base64
import html
import json
import re
from datetime import datetime

from googleapiclient.discovery import build

from outreach.gmail_oauth import get_credentials
from outreach.logging_setup import get_logger
from outreach.paths import PROCESSED_REPLIES_PATH

log = get_logger("gmail_read")

MAX_PROCESSED = 2000  # keep the file small; we only need "have I seen this id"


# --- processed-message tracking -----------------------------------------------

def _load_processed():
    if PROCESSED_REPLIES_PATH.exists():
        try:
            data = json.loads(PROCESSED_REPLIES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(x) for x in data]
        except (ValueError, OSError):
            log.warning("processed_replies.json unreadable - treating as empty")
    return []


def _save_processed(ids):
    PROCESSED_REPLIES_PATH.write_text(
        json.dumps(ids[-MAX_PROCESSED:], indent=0), encoding="utf-8"
    )


def is_processed(message_id):
    return str(message_id) in set(_load_processed())


def mark_processed(message_ids):
    if not message_ids:
        return
    seen = _load_processed()
    known = set(seen)
    for mid in message_ids:
        mid = str(mid)
        if mid not in known:
            seen.append(mid)
            known.add(mid)
    _save_processed(seen)


# --- message parsing ---------------------------------------------------------

def _header(message, name):
    name = name.lower()
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name:
            return h.get("value", "") or ""
    return ""


def _decode_body(data):
    # Gmail uses URL-safe base64 with padding stripped.
    return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")


_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)


def _strip_html(markup):
    markup = _STYLE_RE.sub(" ", markup)
    markup = re.sub(r"<br\s*/?>", "\n", markup, flags=re.I)
    markup = re.sub(r"</p\s*>", "\n\n", markup, flags=re.I)
    text = _TAG_RE.sub("", markup)
    return html.unescape(text)


def _find_text(payload):
    """Depth-first search of a message payload for a usable text body.

    Prefers text/plain; falls back to text/html (tags stripped). Bodies delivered
    as attachments (body.attachmentId, no inline data) are skipped - rare for a
    typed reply and not worth a second round-trip here.
    """
    plain = _collect(payload, "text/plain")
    if plain:
        return plain
    markup = _collect(payload, "text/html")
    if markup:
        return _strip_html(markup)
    return ""


def _collect(payload, mime):
    if payload.get("mimeType") == mime:
        data = payload.get("body", {}).get("data")
        if data:
            return _decode_body(data)
    for part in payload.get("parts", []) or []:
        got = _collect(part, mime)
        if got:
            return got
    return ""


_QUOTE_MARKERS = (
    re.compile(r"^\s*On .+ wrote:\s*$"),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*From: .+", re.I),        # Outlook-style quoted header block
    re.compile(r"^\s*_{5,}\s*$"),
)


def _strip_quoted(text):
    """Best-effort: cut the message at the start of quoted history."""
    lines = text.splitlines()
    cut = None
    for i, line in enumerate(lines):
        if any(m.match(line) for m in _QUOTE_MARKERS):
            cut = i
            break
        if line.lstrip().startswith(">"):
            # a run of quoted lines - trim from here (and a trailing "wrote:" lead-in)
            cut = i
            if i > 0 and lines[i - 1].strip().endswith(":"):
                cut = i - 1
            break
    if cut is not None:
        lines = lines[:cut]
    return "\n".join(lines).strip()


def _received_at(message):
    ms = message.get("internalDate")
    if ms:
        try:
            return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            pass
    return ""


# --- public API -------------------------------------------------------------

def _service(gmail_address):
    return build("gmail", "v1", credentials=get_credentials(gmail_address))


def fetch_new_replies(gmail_address, lookback_days, lead_emails, service=None):
    """For each address in lead_emails, return the most recent inbound message in
    a thread with that address that is newer than lookback_days and not already
    marked processed.

    Returns a list of dicts:
        {"email", "thread_id", "message_id", "received_at", "text"}
    """
    svc = service or _service(gmail_address)
    processed = set(_load_processed())
    me = (gmail_address or "").lower()
    out = []

    for addr in lead_emails:
        addr = (addr or "").strip()
        if not addr:
            continue
        try:
            listing = (
                svc.users()
                .threads()
                .list(
                    userId="me",
                    q=f"from:{addr} newer_than:{lookback_days}d",
                    maxResults=5,
                )
                .execute()
            )
        except Exception as e:  # noqa: BLE001 - one bad address shouldn't kill the scan
            log.warning(f"thread list failed for {addr}: {e}")
            continue

        threads = listing.get("threads", [])
        if not threads:
            continue

        try:
            thread = (
                svc.users()
                .threads()
                .get(userId="me", id=threads[0]["id"], format="full")
                .execute()
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"thread get failed for {addr}: {e}")
            continue

        inbound = [
            m
            for m in thread.get("messages", [])
            if addr.lower() in _header(m, "from").lower()
            and me not in _header(m, "from").lower()
        ]
        if not inbound:
            continue

        msg = inbound[-1]  # messages are chronological; take the latest
        mid = msg.get("id")
        if not mid or str(mid) in processed:
            continue

        text = _strip_quoted(_find_text(msg.get("payload", {})))
        out.append(
            {
                "email": addr,
                "thread_id": thread.get("id"),
                "message_id": str(mid),
                "received_at": _received_at(msg),
                "text": text,
            }
        )

    return out
