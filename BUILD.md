# Building the standalone executable

The client doesn't need Python installed. You build a self-contained folder on a
Windows machine that has Python, then hand them that folder.

## Build

```powershell
cd C:\Users\darga\freight-outreach
.\build.ps1
```

That installs the build dependencies, runs PyInstaller against `FreightOutreach.spec`,
and finishes with a self-check that verifies the Windows credential store, the bundled
Flask templates, and every Google/Excel import work inside the frozen build.

Output: **`dist\FreightOutreach\`** - a folder containing `FreightOutreach.exe` and an
`_internal\` folder. Copy the whole folder anywhere; the `.exe` won't run without
`_internal\` beside it.

## What goes next to the .exe on the client's PC

User data lives in the **same folder as `FreightOutreach.exe`**, not inside `_internal\`:

| File | How it gets there |
|---|---|
| `config.json` | created by `FreightOutreach.exe --setup` |
| `client_secret.json` | copy it in by hand - it's the one-time Google Cloud OAuth client (see `README.md`) |
| `clients.xlsx` | created on first run, or point `config.json` at an existing path |
| `outreach.log`, `send_log.json`, `send_history.jsonl` | created automatically |

## Running it

| Action | Command |
|---|---|
| Open the dashboard | double-click `FreightOutreach.exe` (or run it with no arguments) |
| First-time setup wizard | `FreightOutreach.exe --setup` |
| Send the cold batch now, headless | `FreightOutreach.exe --cold` |
| Run the reminder scan now, headless | `FreightOutreach.exe --reminders` |
| Verify the build is intact | `FreightOutreach.exe --selfcheck` |

The dashboard uses port 5000 when it's free and falls back to a random open port
otherwise; it prints the URL and opens the browser for you.

## Automatic reminders

The "Enable automatic reminders" button in Settings registers a Windows Task Scheduler
job. In the frozen build it runs `FreightOutreach.exe --reminders`; from source it runs
`python -m outreach --reminders`. Either way the job's working directory is the folder
holding `config.json`.
