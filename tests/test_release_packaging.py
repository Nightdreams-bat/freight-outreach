"""The GitHub-Releases installer pipeline: version string, paths for an installed
build, and the packaging files the release workflow drives."""

import re
from pathlib import Path

import pytest

import kairo
from kairo import paths

REPO = Path(__file__).resolve().parent.parent


def test_version_is_semver():
    assert re.match(r"^\d+\.\d+\.\d+([-+].+)?$", kairo.__version__)


# ---- paths.py for an installed (frozen) build --------------------------------

@pytest.fixture
def reset_paths():
    saved = paths._DATA_DIR
    paths._DATA_DIR = None
    yield
    paths._DATA_DIR = saved


def test_frozen_data_dir_is_appdata_kairo(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
    assert paths._frozen_data_dir() == Path(r"C:\Users\x\AppData\Roaming") / "Kairo"


def test_frozen_data_dir_uses_appdata(monkeypatch, reset_paths, tmp_path):
    appdata = tmp_path / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(paths, "resource_path", lambda rel: tmp_path / "no" / rel)
    monkeypatch.setattr(paths.sys, "executable", str(tmp_path / "Programs" / "Kairo" / "Kairo.exe"))
    d = paths.data_dir()
    assert d == appdata / "Kairo"
    assert d.is_dir()


def test_migrate_copies_data_from_old_exe_dir(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "config.json").write_text('{"sender_name": "Ana"}', encoding="utf-8")
    (old / "reply_queue.jsonl").write_text("{}\n", encoding="utf-8")
    dest = tmp_path / "new"
    dest.mkdir()

    import kairo.paths as p
    old_exec = p.sys.executable
    p.sys.executable = str(old / "Kairo.exe")
    try:
        p._migrate_from_exe_dir(dest)
    finally:
        p.sys.executable = old_exec

    assert (dest / "config.json").read_text(encoding="utf-8") == '{"sender_name": "Ana"}'
    assert (dest / "reply_queue.jsonl").exists()


def test_migrate_never_overwrites_existing(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "config.json").write_text("OLD", encoding="utf-8")
    dest = tmp_path / "new"
    dest.mkdir()
    (dest / "config.json").write_text("KEEP", encoding="utf-8")

    import kairo.paths as p
    old_exec = p.sys.executable
    p.sys.executable = str(old / "Kairo.exe")
    try:
        p._migrate_from_exe_dir(dest)
    finally:
        p.sys.executable = old_exec

    assert (dest / "config.json").read_text(encoding="utf-8") == "KEEP"


def test_seed_bundled_client_secret(monkeypatch, tmp_path):
    bundled = tmp_path / "bundle" / "client_secret.json"
    bundled.parent.mkdir()
    bundled.write_text('{"installed": {}}', encoding="utf-8")
    dest = tmp_path / "data"
    dest.mkdir()
    monkeypatch.setattr(paths, "resource_path", lambda rel: bundled if rel == "client_secret.json" else tmp_path / rel)

    paths._seed_bundled_client_secret(dest)
    assert (dest / "client_secret.json").read_text(encoding="utf-8") == '{"installed": {}}'

    # a second run (or an existing file) is a no-op
    (dest / "client_secret.json").write_text("USER", encoding="utf-8")
    paths._seed_bundled_client_secret(dest)
    assert (dest / "client_secret.json").read_text(encoding="utf-8") == "USER"


# ---- packaging files --------------------------------------------------------

def test_inno_script_is_per_user_and_versioned():
    iss = (REPO / "packaging" / "Kairo.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss
    assert r"{localappdata}\Programs\Kairo" in iss
    assert "AppVersion={#AppVersion}" in iss
    assert 'Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall' in iss
    assert 'Tasks: desktopicon' in iss


def test_release_workflow_wiring():
    wf = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in wf
    assert "contents: write" in wf
    assert "kairo.__version__" in wf
    assert "secrets.CLIENT_SECRET_JSON" in wf
    assert "packaging/Kairo.iss" in wf


def test_spec_bundles_client_secret_when_present():
    spec = (REPO / "packaging" / "Kairo.spec").read_text(encoding="utf-8")
    assert 'os.path.exists(_secret)' in spec


def test_spec_ships_a_windowed_gui_exe_and_a_console_cli_exe():
    spec = (REPO / "packaging" / "Kairo.spec").read_text(encoding="utf-8")
    assert 'name="Kairo", console=False' in spec
    assert 'name="kairo-cli", console=True' in spec
    # CI self-checks the console build so its stdout shows up in the logs.
    wf = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "dist/Kairo/kairo-cli.exe --selfcheck" in wf
