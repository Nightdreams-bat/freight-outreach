# Builds the standalone Windows executable into dist\FreightOutreach\.
# Run from the project root:  .\build.ps1
$ErrorActionPreference = "Stop"

python -m pip install -q -r requirements-build.txt
python -m PyInstaller --clean --noconfirm FreightOutreach.spec

Write-Host ""
& ".\dist\FreightOutreach\FreightOutreach.exe" --selfcheck

Write-Host ""
Write-Host "Build complete: dist\FreightOutreach\  (copy this whole folder to the client's PC)"
