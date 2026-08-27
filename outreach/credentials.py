SERVICE_NAME = "freight-outreach-oauth"
ANTHROPIC_SERVICE = "freight-outreach-anthropic"


def _keyring():
    try:
        import keyring
        return keyring
    except ImportError as e:
        raise ImportError(
            "The 'keyring' package is required to store the Gmail OAuth token securely.\n"
            "Install it with: pip install keyring"
        ) from e


def set_oauth_token(gmail_address, token_json):
    _keyring().set_password(SERVICE_NAME, gmail_address, token_json)


def get_oauth_token(gmail_address):
    token_json = _keyring().get_password(SERVICE_NAME, gmail_address)
    if not token_json:
        raise RuntimeError(
            f"No stored Gmail connection for {gmail_address}. Click 'Connect Gmail' in the "
            f"dashboard's Settings page."
        )
    return token_json


def set_anthropic_key(api_key):
    """Store the Anthropic API key in the OS credential store."""
    _keyring().set_password(ANTHROPIC_SERVICE, "api_key", api_key)


def get_anthropic_key():
    """Return the stored Anthropic API key, or None if the client hasn't set one.

    The LLM (reply classification) is an optional feature, so a missing key is a
    normal state - callers decide whether to skip or warn, not an exception here.
    """
    return _keyring().get_password(ANTHROPIC_SERVICE, "api_key") or None


def clear_anthropic_key():
    """Remove the stored Anthropic API key, if any."""
    try:
        _keyring().delete_password(ANTHROPIC_SERVICE, "api_key")
    except Exception:
        pass
