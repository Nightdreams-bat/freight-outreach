import subprocess
import sys
from pathlib import Path

TASK_NAME = "FreightOutreach_ReminderCheck"


def _python_for_task():
    """Prefer pythonw.exe so the scheduled task doesn't flash a console window."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return str(pythonw) if pythonw.exists() else str(exe)


def register_task(interval_hours):
    project_root = Path(__file__).resolve().parent.parent
    script = project_root / "outreach" / "send_reminders.py"
    python_exe = _python_for_task()

    cmd = [
        "schtasks", "/Create", "/F",
        "/SC", "HOURLY",
        "/MO", str(interval_hours),
        "/TN", TASK_NAME,
        "/TR", f'"{python_exe}" "{script}"',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root))
    ok = result.returncode == 0
    if ok:
        print(f"Scheduled task '{TASK_NAME}' created: runs every {interval_hours}h.")
    else:
        print("Failed to create scheduled task:")
        print(result.stdout, result.stderr)
    return ok, (result.stdout or result.stderr).strip()


def unregister_task():
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    ok = result.returncode == 0
    print(result.stdout or result.stderr)
    return ok, (result.stdout or result.stderr).strip()


def task_status():
    """Returns a dict with registered/next_run/status, or None if the task doesn't exist."""
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
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
    from outreach.config import load_config

    cfg = load_config()
    register_task(cfg["reminder_interval_hours"])
