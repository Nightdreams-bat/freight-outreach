"""Typed errors shared across the kairo package."""


class GmailNeedsReconnect(RuntimeError):
    """The stored Gmail OAuth token can't be used or refreshed any more.

    Raised so a batch send / scan aborts once with a clear "click Connect Gmail
    again" message instead of failing N times, once per lead. Testing-mode OAuth
    apps get refresh tokens that expire after 7 days, which is the usual cause.
    """
