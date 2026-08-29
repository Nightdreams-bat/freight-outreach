"""Subprocess wrappers that never flash a console window in a windowed build.

A PyInstaller `console=False` build has no console, so every plain
`subprocess.run`/`Popen` spawns a visible conhost window for a fraction of a
second. Routing process spawns through here suppresses that.
"""

import os
import subprocess

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _hidden_startupinfo():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def _patch(kwargs):
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | NO_WINDOW
    if os.name == "nt" and kwargs.get("startupinfo") is None:
        kwargs["startupinfo"] = _hidden_startupinfo()
    return kwargs


def run(cmd, **kwargs):
    """`subprocess.run` with no-window flags injected."""
    return subprocess.run(cmd, **_patch(kwargs))


def popen(cmd, **kwargs):
    """`subprocess.Popen` with no-window flags injected."""
    return subprocess.Popen(cmd, **_patch(kwargs))
