param(
    [Parameter(Mandatory=$false)][string]$Wheel,
    [string]$Prefix = "$env:LOCALAPPDATA\Programs\VlaPet",
    [switch]$Models,
    [switch]$Rollback,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Releases = Join-Path $Prefix "releases"
$Current = Join-Path $Prefix "current.txt"
$Previous = Join-Path $Prefix "previous.txt"
$Launcher = Join-Path $Prefix "momo-chan.cmd"
$CompatibilityLauncher = Join-Path $Prefix "vla-pet.cmd"

if ($Uninstall) {
    Remove-Item -Recurse -Force $Prefix -ErrorAction SilentlyContinue
    Write-Host "Uninstalled momo-chan. User data in AppData is preserved."
    exit 0
}

if ($Rollback) {
    if (-not (Test-Path $Previous)) { throw "No previous release is available" }
    $OldCurrent = if (Test-Path $Current) { Get-Content $Current -Raw } else { "" }
    $OldPrevious = Get-Content $Previous -Raw
    Set-Content -NoNewline -Path "$Current.tmp" -Value $OldPrevious
    Move-Item -Force "$Current.tmp" $Current
    if ($OldCurrent) { Set-Content -NoNewline -Path $Previous -Value $OldCurrent }
    Write-Host "Rolled back momo-chan."
    exit 0
}

if (-not $Wheel -or -not (Test-Path $Wheel)) { throw "-Wheel must name an existing wheel" }
New-Item -ItemType Directory -Force -Path $Releases | Out-Null
$Release = Join-Path $Releases ([guid]::NewGuid().ToString("N"))
py -3 -m venv $Release
$Python = Join-Path $Release "Scripts\python.exe"
if ($Models) {
    # Avoid PyPI's CUDA-enabled default on the CPU-first v1 profile.
    & $Python -m pip install --extra-index-url "https://download.pytorch.org/whl/cpu" "torch==2.13.0+cpu" "torchvision==0.28.0+cpu"
    if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force $Release; throw "CPU Torch installation failed" }
}
$Package = if ($Models) { "${Wheel}[models]" } else { $Wheel }
& $Python -m pip install $Package
if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force $Release; throw "Package installation failed" }
if (Test-Path $Current) { Copy-Item -Force $Current $Previous }
Set-Content -NoNewline -Path "$Current.tmp" -Value $Release
Move-Item -Force "$Current.tmp" $Current
$LauncherBody = @"
@echo off
set /p VLA_PET_RELEASE=<"$Current"
"%VLA_PET_RELEASE%\Scripts\momo-chan.exe" %*
"@
$LauncherBody | Set-Content -Path $Launcher -Encoding ASCII
$LauncherBody | Set-Content -Path $CompatibilityLauncher -Encoding ASCII
Write-Host "Installed momo-chan into $Prefix"
