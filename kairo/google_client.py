"""Let each install point at its OWN Google Cloud OAuth client.

Kairo's bundled OAuth app asks for the restricted ``gmail.readonly`` scope. In
Google's eyes a shared, unaudited client is capped (100 users, 7-day token
expiry in Testing mode) unless it passes a paid third-party security audit
(CASA). The escape hatch: the operator runs their own Google Cloud project -
they own it, so there is no cap, no audit, and sign-ins don't expire once they
publish it to production.

Kairo already loads its OAuth client from ``paths.CLIENT_SECRET_PATH``. This
module validates a client_secret.json the operator downloaded from Google,
installs it there, and invalidates the current Gmail connection so they re-auth
against the new project.
"""

import json
import os
import shutil
import tempfile

from kairo import paths
from kairo.config import load_config, save_config
from kairo.credentials import delete_oauth_token

_REQUIRED_FIELDS = ("client_id", "client_secret", "auth_uri", "token_uri")


def _read_client_secret():
    """Return the parsed client_secret.json, or None if it's absent/unreadable."""
    path = paths.CLIENT_SECRET_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def describe_client(cfg=None):
    """Summarise the currently-installed OAuth client for the Settings page.

    Pass the already-loaded config when you have it; otherwise it's loaded here.
    """
    data = _read_client_secret()
    if cfg is None:
        cfg = load_config()
    is_custom = bool(cfg.get("google_client_is_custom"))

    if not isinstance(data, dict):
        return {"configured": False, "is_custom": is_custom, "client_id": "", "kind": "unknown"}

    if isinstance(data.get("installed"), dict):
        kind, section = "installed", data["installed"]
    elif isinstance(data.get("web"), dict):
        kind, section = "web", data["web"]
    else:
        kind, section = "unknown", {}

    client_id = str(section.get("client_id") or "")
    return {
        "configured": bool(client_id),
        "is_custom": is_custom,
        "client_id": client_id,
        "kind": kind,
    }


def _invalidate_connection(cfg):
    """Drop the stored Gmail token + address so the operator re-authorises."""
    addr = cfg.get("gmail_address")
    if addr:
        delete_oauth_token(addr)
    cfg["gmail_address"] = ""


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".client_secret-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install_client_secret(text_or_bytes):
    """Validate and install an operator-supplied Desktop-app OAuth client.

    Returns the new client_id. Raises ValueError with a plain-language message
    on any validation failure.
    """
    if isinstance(text_or_bytes, (bytes, bytearray)):
        try:
            text = bytes(text_or_bytes).decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError("That file isn't text - upload the client_secret JSON "
                             "you downloaded from Google.") from e
    else:
        text = str(text_or_bytes)

    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError("That doesn't look like a JSON file. Upload the "
                         "client_secret JSON exactly as you downloaded it from Google.") from e

    if not isinstance(data, dict) or "installed" not in data:
        if isinstance(data, dict) and "web" in data:
            raise ValueError(
                "That's a *Web application* OAuth client. Kairo needs a *Desktop app* "
                "client - create one under Credentials -> Create credentials -> OAuth "
                "client ID -> Application type: Desktop app."
            )
        raise ValueError(
            "That JSON has no \"installed\" section, so it isn't a Desktop app OAuth "
            "client. In Google Cloud: Credentials -> Create credentials -> OAuth client "
            "ID -> Application type: Desktop app, then download the JSON."
        )

    section = data["installed"]
    if not isinstance(section, dict):
        raise ValueError("The \"installed\" section of that JSON is malformed.")

    missing = [f for f in _REQUIRED_FIELDS if not str(section.get(f) or "").strip()]
    if missing:
        raise ValueError(
            "That client_secret JSON is missing required field(s): "
            + ", ".join(missing)
            + ". Re-download it from Google Cloud -> Credentials."
        )

    _atomic_write(paths.CLIENT_SECRET_PATH, text)

    cfg = load_config()
    cfg["google_client_is_custom"] = True
    _invalidate_connection(cfg)
    save_config(cfg)

    return str(section["client_id"])


def reset_to_bundled():
    """Restore Kairo's bundled OAuth client (or clear the custom one).

    Returns a short note string describing what happened.
    """
    bundled = paths.resource_path("client_secret.json")
    restored = False
    if bundled.exists():
        try:
            paths.CLIENT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, paths.CLIENT_SECRET_PATH)
            restored = True
        except OSError:
            restored = False
    else:
        try:
            paths.CLIENT_SECRET_PATH.unlink()
        except OSError:
            pass

    cfg = load_config()
    cfg["google_client_is_custom"] = False
    _invalidate_connection(cfg)
    save_config(cfg)

    if restored:
        return "Switched back to Kairo's shared Google app. Click Connect Gmail to sign in."
    return ("Removed your custom Google credentials. There's no shared app bundled in "
            "this build - add your own client_secret JSON again, then Connect Gmail.")
