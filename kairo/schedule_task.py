import subprocess
import sys
from pathlib import Path

# The two headless scans that can run on a Windows Task Scheduler timer.
# keeps the historical string so an existing install's registered Task Scheduler entries survive the Kairo rename
REMINDER_TASK_NAME = "Kairo_ReminderCheck"
REPLY_TASK_NAME = "Kairo_ReplyCheck"

# Back-compat alias - older code / docs referred to the reminder task as TASK_NAME.
TASK_NAME = REMINDER_TASK_NAME


def _python_for_task():
    """Prefer pythonw.exe so the scheduled task doesn't flash a console window."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return str(pythonw) if pythonw.exists() else str(exe)


def _hidden_launcher_path():
    from kairo.paths import data_dir

    return data_dir() / "run-hidden.vbs"


def _write_hidden_launcher(target):
    """Write a tiny VBScript that launches `target` with no console window.

    Task Scheduler runs the .exe directly otherwise, and a console=True build
    flashes a black window every time the task fires. wscript running this VBS
    with `0, False` starts the real process hidden and doesn't wait.
    """
    path = _hidden_launcher_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    vbs = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run """{target}"" " & WScript.Arguments(0), 0, False\r\n'
    )
    path.write_text(vbs, encoding="utf-8")
    return path


def _task_command(cli_flag):
    """The command a scheduled task should run to do a headless scan.

    Frozen build: a hidden-launch VBS wrapper around the .exe, so the task never
    flashes a console. Source checkout: pythonw -m kairo (already console-less).
    """
    if getattr(sys, "frozen", False):
        vbs = _write_hidden_launcher(Path(sys.executable).resolve())
        return f'wscript.exe //nologo //B "{vbs}" {cli_flag}'
    return f'"{_python_for_task()}" -m kairo {cli_flag}'


def register_task(interval_hours, name=REMINDER_TASK_NAME, cli_flag="--reminders"):
    """Create/replace a Windows scheduled task that runs every `interval_hours`.

    Defaults target the reminder scan so existing callers keep working; pass
    `name`/`cli_flag` for the reply scan (REPLY_TASK_NAME / "--replies").
    """
    from kairo.paths import data_dir

    working_dir = data_dir()
    cmd = [
        "schtasks", "/Create", "/F",
        "/SC", "HOURLY",
        "/MO", str(interval_hours),
        "/TN", name,
        "/TR", _task_command(cli_flag),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(working_dir))
    ok = result.returncode == 0
    if ok:
        print(f"Scheduled task '{name}' created: runs every {interval_hours}h.")
    else:
        print(f"Failed to create scheduled task '{name}':")
        print(result.stdout, result.stderr)
    return ok, (result.stdout or result.stderr).strip()


def unregister_task(name=REMINDER_TASK_NAME):
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", name, "/F"],
        capture_output=True, text=True,
    )
    ok = result.returncode == 0
    print(result.stdout or result.stderr)
    return ok, (result.stdout or result.stderr).strip()


def task_status(name=REMINDER_TASK_NAME):
    """Returns a dict with registered/next_run/status, or None if the task doesn't exist."""
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None

    info = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            info[key.strip()] = value.strip()

    return {
        "registered": True,
        "status": info.get("Status", "Unknown"),
        "next_run": info.get("Next Run Time", "Unknown"),
    }


if __name__ == "__main__":
    from kairo.config import load_config

    cfg = load_config()
    register_task(cfg["reminder_interval_hours"])
