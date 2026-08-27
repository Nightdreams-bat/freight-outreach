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
  FreightOutreach.exe     the app (opens the dashboard)
  client_secret.json      Google OAuth client (copied in if present in the repo root)
  _internal\              the frozen Python runtime
  Source code\            a copy of the source, for anyone who wants to read it
```

`config.json`, `clients.xlsx`, and the logs are created next to
`FreightOutreach.exe` as the client uses it. There is no setup wizard -
`config.json` is written with defaults on first run and everything is edited on
the dashboard's **Settings** page.

## Running it (what the client does)

1. Double-click `FreightOutreach.exe` - the dashboard opens.
2. On the Settings page: fill in business details, point "Excel file" at their
   leads sheet, check the auto-detected column mapping, click "Connect Gmail".
   (`client_secret.json` must be in the folder for the Gmail step.)

The dashboard flags anything still missing until it's done.

## Developer flags

Run either `.exe` (or `python -m outreach` from source) with:

| Flag | Does |
|---|---|
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
