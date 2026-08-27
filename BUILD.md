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
| `--reminders` | run the reminder scan now, headless (used by the scheduled task) |
| `--selfcheck` | verify a freshly built `.exe` has everything it needs |

## Automatic reminders

The "Enable automatic reminders" button in Settings registers a Windows Task
Scheduler job. In the frozen build it runs `FreightOutreach.exe --reminders`;
from source it runs `python -m outreach --reminders`. The job's working
directory is the folder holding `config.json`.
