"""`kairo.google_client` — installing an operator's own Google OAuth client."""

import json

import pytest

from kairo import config, google_client
from kairo import paths as kpaths

INSTALLED = {
    "installed": {
        "client_id": "123-abc.apps.googleusercontent.com",
        "client_secret": "shh",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}
WEB = {"web": {"client_id": "x", "client_secret": "y",
               "auth_uri": "a", "token_uri": "t"}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    secret = tmp_path / "client_secret.json"
    cfgpath = tmp_path / "config.json"
    monkeypatch.setattr(kpaths, "CLIENT_SECRET_PATH", secret)
    monkeypatch.setattr(config, "CONFIG_PATH", cfgpath)
    cfgpath.write_text(json.dumps({
        "gmail_address": "al@freightco.test",
        "google_client_is_custom": False,
        "excel_path": str(tmp_path / "leads.xlsx"),
    }), encoding="utf-8")

    deleted = []
    monkeypatch.setattr(google_client, "delete_oauth_token", lambda a: deleted.append(a))

    class E:
        secret = None
        cfgpath = None
        deleted = None
    E.secret, E.cfgpath, E.deleted = secret, cfgpath, deleted
    return E


def _cfg(env):
    return json.loads(env.cfgpath.read_text(encoding="utf-8"))


def test_install_valid_installed_json(env):
    cid = google_client.install_client_secret(json.dumps(INSTALLED))
    assert cid == INSTALLED["installed"]["client_id"]
    assert json.loads(env.secret.read_text(encoding="utf-8")) == INSTALLED
    cfg = _cfg(env)
    assert cfg["google_client_is_custom"] is True
    assert cfg["gmail_address"] == ""
    assert env.deleted == ["al@freightco.test"]


def test_install_accepts_bytes(env):
    cid = google_client.install_client_secret(json.dumps(INSTALLED).encode("utf-8"))
    assert cid == INSTALLED["installed"]["client_id"]


def test_web_json_rejected(env):
    with pytest.raises(ValueError, match="Desktop app"):
        google_client.install_client_secret(json.dumps(WEB))


def test_missing_field_named(env):
    bad = {"installed": dict(INSTALLED["installed"])}
    del bad["installed"]["client_secret"]
    with pytest.raises(ValueError, match="client_secret"):
        google_client.install_client_secret(json.dumps(bad))


def test_non_json_rejected(env):
    with pytest.raises(ValueError, match="JSON"):
        google_client.install_client_secret("not json at all")


def test_describe_client_reports_custom_and_id(env):
    google_client.install_client_secret(json.dumps(INSTALLED))
    d = google_client.describe_client()
    assert d["is_custom"] is True
    assert d["kind"] == "installed"
    assert d["client_id"] == INSTALLED["installed"]["client_id"]
    assert d["configured"] is True


def test_describe_client_shared_when_flag_false(env):
    env.secret.write_text(json.dumps(INSTALLED), encoding="utf-8")
    d = google_client.describe_client()
    assert d["is_custom"] is False
    assert d["client_id"] == INSTALLED["installed"]["client_id"]


def test_reset_to_bundled_clears_flag_and_connection(env, monkeypatch):
    google_client.install_client_secret(json.dumps(INSTALLED))
    env.deleted.clear()
    # config now has gmail_address "" — put one back to prove reset invalidates it
    cfg = _cfg(env)
    cfg["gmail_address"] = "al@freightco.test"
    env.cfgpath.write_text(json.dumps(cfg), encoding="utf-8")

    monkeypatch.setattr(kpaths, "resource_path", lambda rel: env.secret.parent / "no-bundled")
    note = google_client.reset_to_bundled()

    out = _cfg(env)
    assert out["google_client_is_custom"] is False
    assert out["gmail_address"] == ""
    assert env.deleted == ["al@freightco.test"]
    assert isinstance(note, str) and note
