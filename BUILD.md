# Building the client package

The client doesn't need Python. You build on a Windows machine that has Python,
then hand them one folder.

## Build

```powershell
cd C:\Users\darga\freight-outreach
.\build.ps1
```

`build.ps1` installs the build dependencies, runs PyInstaller against
`FreightOutreach.spec`, runs a self-check on the result, and assembles the
client folder at **`release\FreightOutreach\`**.

## What the client folder looks like

```
FreightOutreach\
  START HERE.txt          plain-English instructions
  Setup.exe               first-time setup wizard  <- client runs this first
  FreightOutreach.exe     the app (opens the dashboard)
  client_secret.json      Google OAuth client (copied in if present in the repo root)
  _internal\              the frozen Python runtime - shared by both .exe files
  Source code\            a copy of the source, for anyone who wants to read it
```

`config.json`, `clients.xlsx`, and the logs are created next to the two `.exe`
files as the client uses it.

`Setup.exe` and `FreightOutreach.exe` are the **same binary** - the app runs the
setup wizard when it sees it's being run under the name `Setup.exe`. One build,
one `_internal\`, no duplication beyond the ~10 MB bootloader stub.

## Running it (what the client does)

1. Double-click `Setup.exe` - answer the questions. Writes `config.json`.
2. Make sure `client_secret.json` is in the folder.
3. Double-click `FreightOutreach.exe` - the dashboard opens; connect Gmail in Settings.

After that, `FreightOutreach.exe` is the only thing they touch day to day.

## Developer flags

Run either `.exe` (or `python -m outreach` from source) with:

| Flag | Does |
|---|---|
| `--setup` | setup wizard (same as running `Setup.exe`) |
| `--cold` | send the cold-intro batch now, headless |
| `--reminders` | run the reminder scan now, headless (used by the `FreightOutreach_ReminderCheck` task) |
| `--replies` | run the reply scan now, headless (used by the `FreightOutreach_ReplyCheck` task) — reads replies, drafts actions, never sends/books |
| `--selfcheck` | verify a freshly built `.exe` has everything it needs (now also checks `anthropic` imports) |

## Bundled dependencies

`anthropic` (reply classification) and its stack — `httpx2`, `jiter` (compiled),
`pydantic` — are collected in `FreightOutreach.spec` via `collect_all`, since none
are covered by PyInstaller's built-in hooks the way plain `httpx` is. The frozen
`--selfcheck` prints `import anthropic: OK` when this worked. Adds ~35 MB to the
folder (~185 MB total).

## Scheduled tasks

The Settings page registers two Windows Task Scheduler jobs, each on its own
Enable/Disable toggle:

| Task | Runs | What |
|---|---|---|
| `FreightOutreach_ReminderCheck` | `--reminders` | 24h-before-meeting reminders |
| `FreightOutreach_ReplyCheck` | `--replies` | scan for lead replies, draft follow-ups |

In the frozen build each runs `FreightOutreach.exe <flag>`; from source,
`python -m outreach <flag>`. Working directory is the folder holding `config.json`.
