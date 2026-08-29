# Builds the app AND the Windows installer locally - the same output the release
# workflow publishes to GitHub Releases, for testing before you push a tag.
#
#   .\packaging\build-installer.ps1
#
# Produces packaging\Output\KairoSetup-<version>.exe. Uses whatever
# client_secret.json sits at the repo root (bundled if present, skipped if not).
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path $here -Parent

# 1. PyInstaller build + self-check + client folder (existing script).
& (Join-Path $here "build.ps1")

# 2. Locate the Inno Setup compiler.
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) {
    throw "Inno Setup 6 not found. Install it:  winget install JRSoftware.InnoSetup"
}

# 3. Version comes from kairo/__init__.py (single source of truth).
$py = (Get-Command python.exe).Source
$version = (& $py -c "import kairo; print(kairo.__version__)").Trim()
Write-Host "Building installer for Kairo $version"

# 4. Compile.
& $iscc "/DAppVersion=$version" (Join-Path $here "Kairo.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC exited $LASTEXITCODE" }

$setup = Join-Path $here "Output\KairoSetup-$version.exe"
Write-Host ""
Write-Host "Installer ready:  $setup"
