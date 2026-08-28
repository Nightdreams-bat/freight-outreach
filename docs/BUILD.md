# Building the Windows package

The client never installs Python. You build on a Windows machine that has it,
then hand over one folder.

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

`config.json`, `clients.xlsx`, and the logs are created next to `Kairo.exe` on
first use. There is no setup wizard — everything is edited on the **Settings**
page.

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
