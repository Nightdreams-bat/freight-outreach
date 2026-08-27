"""Wave 2: List-Unsubscribe headers on outgoing mail."""

import base64

import pytest

from outreach import mailer as mailer_mod
from outreach.mailer import Mailer


class _FakeSend:
    """Captures the raw MIME the Gmail API would have received."""

    def __init__(self):
        self.raw = None
        self.last_body = {}
        self.result = {"id": "x"}

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.raw = body["raw"]
        self.last_body = body
        return self

    def execute(self):
        return self.result


@pytest.fixture
def captured(monkeypatch):
    fake = _FakeSend()
    monkeypatch.setattr(mailer_mod, "get_credentials", lambda addr: object())
    monkeypatch.setattr(mailer_mod, "build", lambda *a, **k: fake)
    return fake


def _decode(fake):
    return base64.urlsafe_b64decode(fake.raw.encode()).decode("utf-8", "replace")


def test_list_unsubscribe_defaults_to_sender_address(captured):
    Mailer("me@example.com").send("lead@acme.test", "Hi", "Body")
    msg = _decode(captured)
    assert "List-Unsubscribe: <mailto:me@example.com?subject=unsubscribe>" in msg
    assert "List-Unsubscribe-Post: List-Unsubscribe=One-Click" in msg


def test_list_unsubscribe_can_be_disabled(captured):
    Mailer("me@example.com").send("lead@acme.test", "Hi", "Body", unsubscribe_mailto=None)
    assert "List-Unsubscribe" not in _decode(captured)


def test_explicit_unsubscribe_mailto_is_used(captured):
    Mailer("me@example.com").send("lead@acme.test", "Hi", "Body", unsubscribe_mailto="unsub@x.test")
    assert "<mailto:unsub@x.test?subject=unsubscribe>" in _decode(captured)


# --- Wave 3: threading, Reply-To, retry/backoff -------------------------

def test_send_returns_message_and_thread_ids(captured):
    captured.result = {"id": "x", "threadId": "THREAD1"}
    out = Mailer("me@example.com").send("lead@acme.test", "Hi", "Body")
    assert out["thread_id"] == "THREAD1"
    assert out["message_id"].startswith("<") and out["message_id"].endswith("@example.com>")


def test_threading_headers_set_when_ids_passed(captured):
    Mailer("me@example.com").send(
        "lead@acme.test", "Re: Hi", "Body",
        in_reply_to="<cold@example.com>", references="<cold@example.com>", thread_id="T9",
    )
    msg = _decode(captured)
    assert "In-Reply-To: <cold@example.com>" in msg
    assert "References: <cold@example.com>" in msg
    assert captured.last_body.get("threadId") == "T9"


def test_no_threading_headers_by_default(captured):
    Mailer("me@example.com").send("lead@acme.test", "Hi", "Body")
    msg = _decode(captured)
    assert "In-Reply-To:" not in msg
    assert "threadId" not in captured.last_body


def test_reply_to_omitted_unless_configured(captured):
    Mailer("me@example.com").send("lead@acme.test", "Hi", "Body")
    assert "Reply-To:" not in _decode(captured)
    Mailer("me@example.com", reply_to="inbox@crm.test").send("lead@acme.test", "Hi", "Body")
    assert "Reply-To: inbox@crm.test" in _decode(captured)


def test_not_a_multipart_message(captured):
    Mailer("me@example.com").send("lead@acme.test", "Hi", "Body")
    msg = _decode(captured)
    assert "Content-Type: text/plain" in msg
    assert "multipart" not in msg


class _Resp(dict):
    def __init__(self, status, reason="", headers=None):
        super().__init__(headers or {})
        self.status = status
        self.reason = reason


def _http_error(status, reason=""):
    from googleapiclient.errors import HttpError
    return HttpError(_Resp(status, reason), b'{"error": {"message": "boom"}}')


def test_retry_backs_off_on_429_then_succeeds(monkeypatch):
    from outreach import mailer as mailer_mod

    slept = []
    monkeypatch.setattr(mailer_mod.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(mailer_mod, "get_credentials", lambda addr: object())

    calls = {"n": 0}

    class Flaky:
        def users(self): return self
        def messages(self): return self
        def send(self, userId, body): return self

        def execute(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(429, "Too Many Requests")
            return {"id": "x", "threadId": "t"}

    monkeypatch.setattr(mailer_mod, "build", lambda *a, **k: Flaky())
    out = Mailer("me@example.com", max_attempts=4).send("lead@acme.test", "Hi", "Body")
    assert out["thread_id"] == "t"
    assert calls["n"] == 2
    assert len(slept) == 1 and 0 < slept[0] <= 60


def test_permanent_400_is_not_retried(monkeypatch):
    from outreach import mailer as mailer_mod

    monkeypatch.setattr(mailer_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mailer_mod, "get_credentials", lambda addr: object())
    calls = {"n": 0}

    class Bad:
        def users(self): return self
        def messages(self): return self
        def send(self, userId, body): return self
        def execute(self):
            calls["n"] += 1
            raise _http_error(400, "Bad Request")

    monkeypatch.setattr(mailer_mod, "build", lambda *a, **k: Bad())
    with pytest.raises(Exception):
        Mailer("me@example.com").send("lead@acme.test", "Hi", "Body")
    assert calls["n"] == 1


def test_refresh_error_raises_needs_reconnect(monkeypatch):
    from google.auth.exceptions import RefreshError

    from outreach import mailer as mailer_mod
    from outreach.errors import GmailNeedsReconnect

    monkeypatch.setattr(mailer_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mailer_mod, "get_credentials", lambda addr: object())

    class Dead:
        def users(self): return self
        def messages(self): return self
        def send(self, userId, body): return self
        def execute(self): raise RefreshError("token revoked")

    monkeypatch.setattr(mailer_mod, "build", lambda *a, **k: Dead())
    with pytest.raises(GmailNeedsReconnect):
        Mailer("me@example.com").send("lead@acme.test", "Hi", "Body")
