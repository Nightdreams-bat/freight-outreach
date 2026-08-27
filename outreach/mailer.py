import base64
import random
import time
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from outreach.errors import GmailNeedsReconnect
from outreach.gmail_oauth import get_credentials
from outreach.logging_setup import get_logger

log = get_logger("mailer")

_UNSET = object()  # "caller didn't say" - distinct from an explicit None (= no header)

# Gmail throttling comes back as 429, or as 403 with one of these reasons. A plain
# 403 (bad scope / permission) and 400 / 404 are permanent - retrying won't help.
_RATE_LIMIT_REASONS = ("ratelimitexceeded", "userratelimitexceeded")
_RETRY_STATUSES = (429, 500, 503)
_MAX_BACKOFF = 60


class Mailer:
    def __init__(self, gmail_address, sender_name=None, sender_company=None,
                 max_attempts=4, retry_delay=5, reply_to=None, retries=None):
        self.gmail_address = gmail_address
        self.sender_name = sender_name
        self.sender_company = sender_company
        # `retries` is the old name for `max_attempts`; keep it working.
        self.max_attempts = int(retries) if retries is not None else int(max_attempts)
        self.retry_delay = retry_delay
        self.reply_to = (reply_to or "").strip() or None

    # Back-compat alias for callers/tests that still read `.retries`.
    @property
    def retries(self):
        return self.max_attempts

    def _from_header(self):
        if self.sender_name and self.sender_company:
            display_name = f"{self.sender_name} - {self.sender_company}"
        else:
            display_name = self.sender_name or self.sender_company or ""
        return formataddr((display_name, self.gmail_address)) if display_name else self.gmail_address

    def send(self, to_addr, subject, body, unsubscribe_mailto=_UNSET,
             in_reply_to=None, references=None, thread_id=None):
        """Send one plaintext email through the Gmail API.

        Returns {"message_id": <generated Message-ID>, "thread_id": <Gmail threadId>}
        so the caller can thread later follow-ups/reminders onto this message.

        Pass `in_reply_to` / `references` (a Message-ID) and/or `thread_id` (a Gmail
        threadId) to make this message a reply in an existing conversation.
        Pass `unsubscribe_mailto=None` to omit the List-Unsubscribe headers.
        """
        # Default the one-click unsubscribe address to the sender's own mailbox.
        if unsubscribe_mailto is _UNSET:
            unsubscribe_mailto = self.gmail_address

        # A bare text/plain part (no multipart wrapper) is cleaner and scores
        # marginally better than multipart/mixed around a single part.
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self._from_header()
        msg["To"] = to_addr
        msg["Subject"] = subject
        # Reply-To is only set when the operator has configured a separate address.
        # Setting it to something other than the connected mailbox breaks automated
        # reply detection (gmail_read only searches the connected inbox).
        if self.reply_to:
            msg["Reply-To"] = self.reply_to
        # One-click list-unsubscribe (Gmail bulk-sender requirement / spam signal
        # when absent). Points at the sender's own mailbox with a parseable
        # subject - there is no hosted endpoint for this local tool.
        if unsubscribe_mailto:
            msg["List-Unsubscribe"] = f"<mailto:{unsubscribe_mailto}?subject=unsubscribe>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        # A real mail client always sets these; their absence is itself a spam
        # signal, so we set them explicitly rather than leaving it to chance.
        msg["Date"] = formatdate(localtime=True)
        message_id = make_msgid(domain=self.gmail_address.split("@")[-1])
        msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to
        elif references:
            msg["References"] = references

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id

        creds = get_credentials(self.gmail_address)  # may raise GmailNeedsReconnect
        service = build("gmail", "v1", credentials=creds)

        last_error = None
        for attempt in range(self.max_attempts):
            try:
                resp = service.users().messages().send(userId="me", body=send_body).execute()
                return {"message_id": message_id, "thread_id": (resp or {}).get("threadId")}
            except HttpError as e:
                status = e.resp.status if e.resp is not None else None
                if not _is_retryable(e, status):
                    raise  # bad request / permissions / bad address - retrying won't help
                last_error = e
                delay = _retry_after(e)
            except RefreshError as e:
                raise GmailNeedsReconnect(
                    "Gmail sign-in expired - click Connect Gmail again"
                ) from e
            except (TransportError, OSError) as e:
                last_error = e
                delay = None

            if attempt < self.max_attempts - 1:
                if delay is None:
                    delay = min(2 ** attempt + random.uniform(0, 1), _MAX_BACKOFF)
                log.warning("Gmail send failed (attempt %d/%d), retrying in %.1fs: %s",
                            attempt + 1, self.max_attempts, delay, last_error)
                time.sleep(delay)
        raise last_error


def _rate_limit_reason(e):
    """Best-effort scrape of an HttpError for a Gmail rate-limit reason string."""
    blob = ""
    try:
        for detail in (e.error_details or []):
            if isinstance(detail, dict) and detail.get("reason"):
                blob += " " + str(detail["reason"])
    except Exception:  # noqa: BLE001
        pass
    blob += " " + str(getattr(e.resp, "reason", "") or "")
    blob += " " + str(e)
    return blob.lower()


def _is_retryable(e, status):
    if status in _RETRY_STATUSES:
        return True
    if status == 403 and any(r in _rate_limit_reason(e) for r in _RATE_LIMIT_REASONS):
        return True
    return False


def _retry_after(e):
    """Seconds from a Retry-After response header, or None if absent/unparseable."""
    try:
        val = e.resp.get("retry-after")
    except Exception:  # noqa: BLE001
        val = None
    if not val:
        return None
    try:
        return min(float(val), _MAX_BACKOFF)
    except (TypeError, ValueError):
        return None
