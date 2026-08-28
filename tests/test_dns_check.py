"""outreach.dns_check - fail-safe domain resolution check with a per-domain cache."""

import socket

import pytest

from outreach import dns_check


@pytest.fixture(autouse=True)
def _clear():
    dns_check.clear_cache()
    yield
    dns_check.clear_cache()


def test_resolves_true_on_success(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [("x",)])
    assert dns_check.domain_resolves("example.com") is True


def test_gaierror_means_false(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert dns_check.domain_resolves("no-such-domain.test") is False


def test_timeout_is_failsafe_true(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert dns_check.domain_resolves("slow-domain.test") is True


def test_empty_domain_is_false():
    assert dns_check.domain_resolves("") is False


def test_result_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: calls.append(1) or [("x",)])
    dns_check.domain_resolves("example.com")
    dns_check.domain_resolves("example.com")
    assert len(calls) == 1
    dns_check.clear_cache()
    dns_check.domain_resolves("example.com")
    assert len(calls) == 2
