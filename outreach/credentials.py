SERVICE_NAME = "freight-outreach-oauth"


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
