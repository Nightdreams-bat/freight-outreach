"""Create Desktop + Start-Menu shortcuts to the app, once, on first frozen run.

Uses the Windows Script Host COM object via pywin32 (already bundled). Every
failure is swallowed - a missing shortcut is a cosmetic problem, never a reason
to stop the app from starting.
"""

import os

from outreach.logging_setup import get_logger

log = get_logger("shortcut")

LINK_NAME = "Freight Outreach.lnk"


def _shell():
    import win32com.client  # noqa: PLC0415 - optional, only on Windows builds

    return win32com.client.Dispatch("WScript.Shell")


def _write_link(shell, folder, target_exe):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, LINK_NAME)
    link = shell.CreateShortcut(path)
    link.TargetPath = target_exe
    link.WorkingDirectory = os.path.dirname(target_exe)
    link.IconLocation = f"{target_exe}, 0"
    link.Description = "Freight Outreach - cold outreach + reminders dashboard"
    link.Save()
    return path


def create_shortcuts(target_exe):
    """Write the .lnk into Desktop and Start-Menu Programs. Returns the paths written."""
    written = []
    try:
        shell = _shell()
    except Exception as e:  # noqa: BLE001
        log.info("Shortcut host unavailable: %s", e)
        return written

    desktop = shell.SpecialFolders("Desktop")
    programs = shell.SpecialFolders("Programs")
    for folder in (desktop, programs):
        if not folder:
            continue
        try:
            written.append(_write_link(shell, folder, target_exe))
        except Exception as e:  # noqa: BLE001
            log.info("Couldn't write shortcut in %s: %s", folder, e)
    return written
