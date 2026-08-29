# PyInstaller spec for the standalone Windows build.
# Run via  .\packaging\build.ps1 , or by hand from anywhere:  pyinstaller packaging\Kairo.spec
# Output: dist/Kairo/Kairo.exe  (a folder the client can copy anywhere)

import os

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

# PyInstaller resolves relative paths in this spec against the spec file's own
# directory (packaging/), NOT the working directory - so anchor every source path
# to the repo root explicitly. SPECPATH is the dir containing this spec.
ROOT = os.path.dirname(os.path.abspath(SPECPATH))


def _root(*parts):
    return os.path.join(ROOT, *parts)

hiddenimports = []
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("google_auth_oauthlib")
hiddenimports += collect_submodules("googleapiclient")
hiddenimports += ["win32ctypes.pywin32", "win32timezone"]
# tzdata ships the IANA database as a data-only package (Windows has no system
# zoneinfo); tzlocal detects the machine zone. httpx is anthropic's transport -
# normally pulled in by anthropic's PyInstaller hook, listed here to be safe.
hiddenimports += ["tzdata", "tzlocal", "httpx", "httpcore"]

datas = [
    (_root("kairo", "web", "templates"), "kairo/web/templates"),
    (_root("kairo", "web", "static"), "kairo/web/static"),
]
datas += collect_data_files("googleapiclient")

# The one-time Google OAuth client. Not in the repo (gitignored); the release
# workflow writes it from a GitHub secret before this runs. When present it is
# bundled at the archive root and copied out to %APPDATA%\Kairo on first run
# (kairo/paths.py) so "Connect Gmail" works without any manual setup.
_secret = _root("client_secret.json")
if os.path.exists(_secret):
    datas.append((_secret, "."))

# anthropic (reply classification) and its stack. anthropic 1.x pulls httpx +
# jiter (compiled) + pydantic; none are fully covered by PyInstaller's built-in
# hooks, so collect each one wholesale. tzdata is data-only (IANA zone files).
#
# pywebview + pythonnet power the native desktop window (WebView2). PyInstaller
# ships hooks for webview/clr/clr_loader, but pythonnet's Python.Runtime.dll and
# the WebView2 loader assemblies still need collecting.
binaries = []
#
# ddgs (keyless web search for the "Find leads" beta) pulls primp (compiled Rust
# HTTP client) and lxml (compiled C) - both need their binaries collected.
for _pkg in ("anthropic", "httpx", "httpcore", "jiter", "anyio", "sniffio", "distro",
             "pydantic", "pydantic_core", "docstring_parser", "tzdata",
             "webview", "pythonnet", "clr_loader",
             "ddgs", "primp", "lxml"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

hiddenimports += ["webview.platforms.edgechromium", "clr_loader", "clr_loader.netfx"]

a = Analysis(
    [_root("kairo", "__main__.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Nothing in this app uses these; they're only in the build machine's global
        # site-packages and PyInstaller would otherwise vacuum them in (~hundreds of MB).
        "matplotlib", "numpy", "pandas", "scipy", "PIL", "pygame",
        "IPython", "jedi", "parso", "notebook", "zmq", "pytest",
        "tkinter.test", "test", "unittest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kairo",
    console=True,  # keep a console for CLI flags (--cold, --selfcheck, scheduled tasks);
                   # GUI mode hides the console window at runtime (kairo/desktop.py)
    disable_windowed_traceback=False,
    icon=_root("assets", "kairo.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Kairo",
)
