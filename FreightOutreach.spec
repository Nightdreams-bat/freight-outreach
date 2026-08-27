# PyInstaller spec for the standalone Windows build.
#   pip install -r requirements.txt pyinstaller
#   pyinstaller FreightOutreach.spec
# Output: dist/FreightOutreach/FreightOutreach.exe  (a folder the client can copy anywhere)

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = []
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("google_auth_oauthlib")
hiddenimports += collect_submodules("googleapiclient")
hiddenimports += ["win32ctypes.pywin32", "win32timezone"]

datas = [
    ("outreach/web/templates", "outreach/web/templates"),
    ("outreach/web/static", "outreach/web/static"),
]
datas += collect_data_files("googleapiclient")

a = Analysis(
    ["outreach/__main__.py"],
    pathex=[],
    binaries=[],
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
    name="FreightOutreach",
    console=True,  # keep a console: the dashboard prints its URL, and errors stay visible
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FreightOutreach",
)
