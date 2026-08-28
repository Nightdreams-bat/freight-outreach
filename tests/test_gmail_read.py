"""Wave 2: gmail_read - inbound reply selection, body decode, quote stripping,
processed-id tracking. No network: a fake Gmail service is injected."""

import base64

import pytest

from outreach import gmail_read


# --- fake Gmail service ------------------------------------------------------

def _b64(text):
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _msg(msg_id, from_addr, body_parts, internal_date="1700000000000"):
    """body_parts: list of (mime_type, text). One part -> flat payload."""
    def part(mime, text):
        return {"mimeType": mime, "body": {"data": _b64(text)}, "headers": []}

    if len(body_parts) == 1:
        payload = part(*body_parts[0])
    else:
        payload = {"mimeType": "multipart/alternative", "parts": [part(m, t) for m, t in body_parts]}
    payload["headers"] = [{"name": "From", "value": from_addr}]
    return {"id": msg_id, "internalDate": internal_date, "payload": payload}


class _FakeExec:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class _FakeThreads:
    def __init__(self, threads_by_query, thread_bodies):
        self._by_query = threads_by_query
        self._bodies = thread_bodies

    def list(self, userId, q, maxResults):
        for needle, threads in self._by_query.items():
            if needle in q:
                return _FakeExec({"threads": threads})
        return _FakeExec({"threads": []})

    def get(self, userId, id, format):
        return _FakeExec(self._bodies[id])


class _FakeUsers:
    def __init__(self, threads):
        self._threads = threads

    def threads(self):
        return self._threads


class FakeGmail:
    def __init__(self, threads_by_query, thread_bodies):
        self._users = _FakeUsers(_FakeThreads(threads_by_query, thread_bodies))

    def users(self):
        return self._users


@pytest.fixture(autouse=True)
def _tmp_processed(tmp_path, monkeypatch):
    monkeypatch.setattr(gmail_read, "PROCESSED_REPLIES_PATH", tmp_path / "processed.json")


# --- _strip_quoted ---------------------------------------------------------

def test_strip_quoted_on_wrote():
    text = "Yes, works for me.\n\nOn Mon, Sep 1 2026 at 9:00, Al <al@x.com> wrote:\n> original\n> more"
    assert gmail_read._strip_quoted(text) == "Yes, works for me."


def test_strip_quoted_bare_gt_lines():
    text = "Sounds good.\n> quoted stuff\n> more quoted"
    assert gmail_read._strip_quoted(text) == "Sounds good."


def test_strip_quoted_nothing_to_strip():
    assert gmail_read._strip_quoted("Just a plain reply.") == "Just a plain reply."


# --- body extraction -----------------------------------------------------

def test_find_text_prefers_plain():
    payload = _msg("m1", "x@y.com", [("text/plain", "plain body"), ("text/html", "<p>html body</p>")])["payload"]
    assert gmail_read._find_text(payload) == "plain body"


def test_find_text_html_fallback():
    payload = _msg("m1", "x@y.com", [("text/html", "<p>Hello</p><br><b>there</b>")])["payload"]
    out = gmail_read._find_text(payload)
    assert "Hello" in out and "there" in out and "<" not in out


# --- fetch_new_replies ---------------------------------------------------

def _service_with_thread(messages):
    return FakeGmail(
        threads_by_query={"from:lead@co.test": [{"id": "T1"}]},
        thread_bodies={"T1": {"id": "T1", "messages": messages}},
    )


def test_picks_latest_inbound_message():
    svc = _service_with_thread([
        _msg("out1", "me@gmail.com", [("text/plain", "cold email")], "1700000000000"),
        _msg("in1", "lead@co.test", [("text/plain", "first reply")], "1700000100000"),
        _msg("in2", "lead@co.test", [("text/plain", "Yes let's talk\n\nOn ... wrote:\n> x")], "1700000200000"),
    ])
    got = gmail_read.fetch_new_replies("me@gmail.com", 30, ["lead@co.test"], service=svc)
    assert len(got) == 1
    assert got[0]["message_id"] == "in2"
    assert got[0]["text"] == "Yes let's talk"
    assert got[0]["thread_id"] == "T1"
    assert got[0]["received_at"].startswith("20")


def test_ignores_thread_with_no_inbound():
    svc = _service_with_thread([_msg("out1", "me@gmail.com", [("text/plain", "hi")])])
    assert gmail_read.fetch_new_replies("me@gmail.com", 30, ["lead@co.test"], service=svc) == []


def test_skips_already_processed():
    svc = _service_with_thread([_msg("in1", "lead@co.test", [("text/plain", "hello")])])
    gmail_read.mark_processed(["in1"])
    assert gmail_read.fetch_new_replies("me@gmail.com", 30, ["lead@co.test"], service=svc) == []


def test_unknown_address_returns_nothing():
    svc = _service_with_thread([_msg("in1", "lead@co.test", [("text/plain", "hi")])])
    assert gmail_read.fetch_new_replies("me@gmail.com", 30, ["other@nope.test"], service=svc) == []


# --- processed-id tracking --------------------------------------------

def test_mark_processed_persists_ids():
    assert gmail_read._load_processed() == []
    gmail_read.mark_processed(["abc", "def"])
    assert set(gmail_read._load_processed()) == {"abc", "def"}


def test_mark_processed_dedupes():
    gmail_read.mark_processed(["a", "a", "b"])
    gmail_read.mark_processed(["b", "c"])
    assert gmail_read._load_processed().count("b") == 1


def test_processed_list_capped():
    gmail_read.mark_processed([str(i) for i in range(gmail_read.MAX_PROCESSED + 500)])
    stored = gmail_read._load_processed()
    assert len(stored) == gmail_read.MAX_PROCESSED
    assert stored[-1] == str(gmail_read.MAX_PROCESSED + 499)  # newest kept


# --- fetch_bounces (NDR parsing) ----------------------------------------

def _ndr(msg_id, *, subject="Delivery Status Notification (Failure)",
         failed_header=None, dsn_text=None, body_text="", from_addr="mailer-daemon@googlemail.com",
         internal_date="1700000000000"):
    headers = [{"name": "From", "value": from_addr}, {"name": "Subject", "value": subject}]
    if failed_header:
        headers.append({"name": "X-Failed-Recipients", "value": failed_header})
    parts = [{"mimeType": "text/plain", "body": {"data": _b64(body_text)}, "headers": []}]
    if dsn_text is not None:
        parts.append({
            "mimeType": "message/delivery-status",
            "headers": [],
            "body": {},
            "parts": [{"mimeType": "text/plain", "body": {"data": _b64(dsn_text)}, "headers": []}],
        })
    payload = {"mimeType": "multipart/report", "headers": headers, "parts": parts}
    return {"id": msg_id, "internalDate": internal_date, "payload": payload}


class _FakeMessages:
    def __init__(self, listing, bodies):
        self._listing = listing
        self._bodies = bodies

    def list(self, userId, q, maxResults):
        return _FakeExec(self._listing)

    def get(self, userId, id, format):
        return _FakeExec(self._bodies[id])


class FakeGmailMessages:
    def __init__(self, messages):
        self._m = _FakeMessages(
            {"messages": [{"id": m["id"]} for m in messages]},
            {m["id"]: m for m in messages},
        )

    def users(self):
        outer = self

        class _U:
            def messages(self_inner):
                return outer._m

        return _U()


def test_fetch_bounces_uses_failed_recipients_header():
    svc = FakeGmailMessages([
        _ndr("b1", failed_header="deadbox@gone.test",
             dsn_text="Action: failed\nStatus: 5.1.1\n", body_text="550 no such user"),
    ])
    out = gmail_read.fetch_bounces("me@gmail.com", 7, service=svc)
    assert out == [{"message_id": "b1", "failed_email": "deadbox@gone.test",
                    "permanent": True, "received_at": out[0]["received_at"]}]
    assert out[0]["received_at"].startswith("20")


def test_fetch_bounces_falls_back_to_final_recipient():
    svc = FakeGmailMessages([
        _ndr("b2", dsn_text="Final-Recipient: rfc822; nope@dead.test\nStatus: 5.0.0\n"),
    ])
    out = gmail_read.fetch_bounces("me@gmail.com", 7, service=svc)
    assert out[0]["failed_email"] == "nope@dead.test"
    assert out[0]["permanent"] is True


def test_fetch_bounces_transient_is_not_permanent():
    svc = FakeGmailMessages([
        _ndr("b3", failed_header="slow@busy.test",
             dsn_text="Status: 4.2.2\n", body_text="452 mailbox full"),
    ])
    out = gmail_read.fetch_bounces("me@gmail.com", 7, service=svc)
    assert out[0]["failed_email"] == "slow@busy.test"
    assert out[0]["permanent"] is False


def test_fetch_bounces_body_regex_fallback():
    svc = FakeGmailMessages([
        _ndr("b4", dsn_text=None,
             body_text="Your message to victim@lost.test was not delivered. 5.4.1 permanent error"),
    ])
    out = gmail_read.fetch_bounces("me@gmail.com", 7, service=svc)
    assert out[0]["failed_email"] == "victim@lost.test"
    assert out[0]["permanent"] is True


def test_fetch_bounces_skips_processed():
    svc = FakeGmailMessages([_ndr("b5", failed_header="x@y.test", dsn_text="Status: 5.1.1\n")])
    gmail_read.mark_processed(["b5"])
    assert gmail_read.fetch_bounces("me@gmail.com", 7, service=svc) == []
