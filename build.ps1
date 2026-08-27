# Builds the standalone Windows app and assembles the folder you hand to the client.
# Run from the project root:  .\build.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Invoke-Checked($file, $arguments) {
    # Windows PowerShell turns a native tool's stderr writes into terminating errors
    # when $ErrorActionPreference is 'Stop' (pip prints upgrade notices to stderr).
    # Drop to 'Continue' for the call and gate on the real exit code instead.
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $file @arguments } finally { $ErrorActionPreference = $old }
    if ($LASTEXITCODE -ne 0) { throw "$file $arguments  ->  exit $LASTEXITCODE" }
}

$py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "python.exe not found on PATH. Install Python 3.10+ and retry." }
Write-Host "Using Python: $py"

# Any running copy of the app locks the folders we're about to delete.
Get-Process FreightOutreach -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500
foreach ($d in "build", "dist", "release") {
    $p = Join-Path $root $d
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

Invoke-Checked $py @("-m", "pip", "install", "-q", "-r", (Join-Path $root "requirements-build.txt"))
Invoke-Checked $py @("-m", "PyInstaller", "--clean", "--noconfirm", (Join-Path $root "FreightOutreach.spec"))

$built = Join-Path $root "dist\FreightOutreach"
if (-not (Test-Path (Join-Path $built "FreightOutreach.exe"))) {
    throw "PyInstaller finished but dist\FreightOutreach\FreightOutreach.exe is missing."
}

Write-Host ""
Invoke-Checked (Join-Path $built "FreightOutreach.exe") @("--selfcheck")

# --- Assemble the client-facing folder --------------------------------------
$release = Join-Path $root "release\FreightOutreach"
New-Item -ItemType Directory -Force -Path $release | Out-Null

Copy-Item (Join-Path $built "FreightOutreach.exe") $release
Copy-Item (Join-Path $built "_internal") $release -Recurse

$secret = Join-Path $root "client_secret.json"
if (Test-Path $secret) {
    Copy-Item $secret $release
} else {
    Set-Content (Join-Path $release "PUT client_secret.json HERE.txt") `
        "Copy client_secret.json (the one-time Google Cloud OAuth client) into this folder.`r`nWithout it, 'Connect Gmail' in the dashboard won't work. See Source code\README.md." `
        -Encoding utf8
}

$src = Join-Path $release "Source code"
New-Item -ItemType Directory -Force -Path $src | Out-Null
Copy-Item (Join-Path $root "outreach") $src -Recurse
Get-ChildItem $root -File | Where-Object {
    $_.Name -match '\.(md|spec|txt|ps1)$' -or $_.Name -eq '.gitignore'
} | Where-Object { $_.Name -ne 'build_out.log' } | ForEach-Object { Copy-Item $_.FullName $src }
Get-ChildItem $src -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item (Join-Path $root "START_HERE.txt") (Join-Path $release "START HERE.txt")

Write-Host ""
Write-Host "Client folder ready:  $release"
Write-Host "Hand the whole 'FreightOutreach' folder to the client."
