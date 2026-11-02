# Builds dist\Drivion, then checks that nothing personal got in and that it runs.
# Run from the project root: .\packaging\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot)
$python = ".\.venv\Scripts\python.exe"
$output = "dist\Drivion"

& $python -m PyInstaller packaging\drivion.spec --noconfirm --distpath dist --workpath build\pyinstaller
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Copy-Item config\settings.example.toml, .env.example, README.md, LICENSE $output

# The spec lists what goes in, so this is a second, independent check.
$private = Get-ChildItem $output -Recurse -Force -File |
    Where-Object { $_.Name -in ".env", "settings.toml", "templates.bin" -or $_.Extension -eq ".face" }
if ($private) { throw "Personal files in the build: $($private.FullName -join ', ')" }

& "$output\drivion.exe" --version
if ($LASTEXITCODE -ne 0) { throw "drivion.exe did not start" }

$size = (Get-ChildItem $output -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Output ("Built {0} ({1:N0} MB). Check it with: {0}\drivion.exe --self-test" -f $output, $size)
