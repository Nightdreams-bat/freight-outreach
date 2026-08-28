# PyInstaller spec for the standalone Windows build.
# Run via  .\packaging\build.ps1  (which sets the working dir to the repo root),
# or by hand from the repo root:  pyinstaller packaging\Kairo.spec
# Output: dist/Kairo/Kairo.exe  (a folder the client can copy anywhere)

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

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
    ("kairo/web/templates", "kairo/web/templates"),
    ("kairo/web/static", "kairo/web/static"),
]
datas += collect_data_files("googleapiclient")

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
    ["kairo/__main__.py"],
    pathex=[],
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
    icon="assets/kairo.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Kairo",
)
