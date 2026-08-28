"""Pre-send domain-resolution check.

Drops dead scraped domains before they cost a send slot and a bounce. Fail-safe:
only a definitive name-resolution failure (`socket.gaierror`) returns False - a
timeout or any other transient error returns True so the send still goes out.
"""

import socket

from outreach.logging_setup import get_logger

log = get_logger("dns_check")

_CACHE = {}


def clear_cache():
    """Drop the per-domain resolution cache (call once at the start of a batch)."""
    _CACHE.clear()


def domain_resolves(domain, *, timeout=3.0):
    """True if `domain` has a DNS record (or if the lookup was inconclusive).

    Only a definitive `socket.gaierror` name failure returns False.
    """
    domain = (domain or "").strip().lower()
    if not domain:
        return False
    if domain in _CACHE:
        return _CACHE[domain]

    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(domain, None)
        result = True
    except socket.gaierror as e:
        log.info("Domain %s does not resolve: %s", domain, e)
        result = False
    except Exception as e:  # noqa: BLE001 - timeout / transient: fail safe, send anyway
        log.warning("DNS check for %s was inconclusive (%s); sending anyway", domain, e)
        result = True
    finally:
        socket.setdefaulttimeout(old_timeout)

    _CACHE[domain] = result
    return result
