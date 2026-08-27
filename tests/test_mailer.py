"""Wave 2: List-Unsubscribe headers on outgoing mail."""

import base64

import pytest

from outreach import mailer as mailer_mod
from outreach.mailer import Mailer


class _FakeSend:
    """Captures the raw MIME the Gmail API would have received."""

    def __init__(self):
        self.raw = None

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.raw = body["raw"]
        return self

    def execute(self):
        return {"id": "x"}


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
