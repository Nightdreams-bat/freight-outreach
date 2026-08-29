# Building the Windows package

The client never installs Python. The polished path is the
**[GitHub-Releases installer](#github-releases-installer)** below; `build.ps1`
still produces the raw hand-over folder.

```powershell
.\packaging\build.ps1
```

`build.ps1` installs the build deps, runs PyInstaller against
`packaging\Kairo.spec`, self-checks the result, and assembles
**`release\Kairo\`**:

```
Kairo\
  START HERE.txt        plain-English instructions
  Kairo.exe             the app (opens the dashboard)
  client_secret.json    Google OAuth client — copied in if present at the repo root
  _internal\            the frozen Python runtime
  Source code\          a full copy of the source
```

There is no setup wizard — everything is edited on the **Settings** page.

## User data location

A frozen build keeps `config.json`, `client_secret.json`, `clients.xlsx`, the
logs and the trackers in **`%APPDATA%\Kairo`** (`kairo/paths.py`, `data_dir()`),
not next to the `.exe`. That way an uninstall or an upgrade never touches the
operator's settings. On first run an installed build also migrates any of those
files from an older next-to-the-exe layout, and copies out the `client_secret.json`
that was bundled into the build (see below). Running from source is unchanged:
data sits in the repo root.

## GitHub-Releases installer

`git tag vX.Y.Z && git push origin vX.Y.Z` triggers
`.github/workflows/release.yml` on a Windows runner:

1. checks the tag matches `kairo.__version__`,
2. writes `client_secret.json` from the `CLIENT_SECRET_JSON` repo secret (bundled
   into the archive root by `Kairo.spec`, copied to `%APPDATA%\Kairo` on first run),
3. runs PyInstaller + `--selfcheck`,
4. compiles `packaging\Kairo.iss` with Inno Setup into
   `KairoSetup-<version>.exe`,
5. publishes a GitHub Release with the installer + its `.sha256`.

`.\packaging\build-installer.ps1` does steps 3–4 locally for testing (needs
Inno Setup 6: `winget install JRSoftware.InnoSetup`).

**The installer** (`Kairo.iss`) is per-user: `PrivilegesRequired=lowest`, installs
to `{localappdata}\Programs\Kairo` (changeable), no UAC prompt. Optional Desktop
shortcut, "Launch Kairo now" checkbox, clean uninstaller. It is **unsigned** —
first run hits a SmartScreen warning (More info → Run anyway).

**Repo secret required:** `CLIENT_SECRET_JSON` = the full contents of the Google
Cloud OAuth desktop-client JSON. Set it under Settings → Secrets and variables →
Actions.

## Bundled dependencies

`anthropic` and its stack (`httpx`, `jiter`, `pydantic`), `pywebview` +
`pythonnet` (the native window), and `ddgs` + `primp` + `lxml` (keyless lead
search) are collected wholesale in `Kairo.spec` via `collect_all` — none are
fully covered by PyInstaller's built-in hooks. The frozen `--selfcheck` prints
`import anthropic: OK` when it worked. Total folder ≈ 185 MB.

## Scheduled tasks

The Settings page registers two Windows Task Scheduler jobs, each with its own
Enable/Disable toggle:

| Task | Flag | What |
|---|---|---|
| `Kairo_ReminderCheck` | `--reminders` | 24h-before-meeting reminders + follow-up scan |
| `Kairo_ReplyCheck` | `--replies` | scan for lead replies, draft follow-ups (never sends) |

Frozen build runs `Kairo.exe <flag>`; from source, `python -m kairo <flag>`.
Working directory is the folder holding `config.json`.
