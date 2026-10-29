#Requires -Version 5.1
<#
.SYNOPSIS
    Build the Habit Quest desktop app into a Windows installer and a zip.

.DESCRIPTION
    One command produces everything a person needs to install Habit Quest:

      desktop\release\Habit-Quest-Setup-<version>.exe       installer + desktop icon
      desktop\release\Habit-Quest-<version>-win-x64.zip     portable copy
      desktop\release\Habit-Quest-<version>-windows-x64.zip hand-off bundle

    The build is repeatable: run it again after changing the app and it rebuilds
    the frozen Python backend, repackages Electron and regenerates the zip. It
    is safe to run as often as you like.

.PARAMETER Bump
    Bump the version in desktop\package.json first (patch, minor or major).

.PARAMETER SkipBackend
    Do not rebuild the frozen backend; reuse desktop\backend-dist. The result
    then needs Python 3.10+ on the machine that runs it, so only use this for a
    quick UI-only test build.

.PARAMETER SkipInstall
    Do not run npm install. Use when node_modules is already up to date.

.PARAMETER NoZip
    Leave the finished files loose in desktop\release instead of bundling them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-install.ps1 -Bump minor
#>
[CmdletBinding()]
param(
    [ValidateSet('none', 'patch', 'minor', 'major')]
    [string]$Bump = 'none',
    [switch]$SkipBackend,
    [switch]$SkipInstall,
    [switch]$NoZip
)

# Native tools (npm, pip, PyInstaller) write to stderr for ordinary progress and
# warnings. Leaving PowerShell in 'Stop' mode would turn that into a build
# failure, so every external command is checked by its exit code instead.
$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DesktopDir = Join-Path $RepoRoot 'desktop'
$ReleaseDir = Join-Path $DesktopDir 'release'
$LegacyStagingDir = Join-Path $DesktopDir 'release-bundle'
$BackendDist = Join-Path $DesktopDir 'backend-dist'
$BuildDir = Join-Path $RepoRoot 'build'
$Started = Get-Date

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Detail([string]$Text) {
    Write-Host "    $Text" -ForegroundColor DarkGray
}

function Invoke-Checked {
    param([string]$What, [scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed (exit code $LASTEXITCODE)."
    }
}

function Assert-Tool {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found on PATH. $Hint"
    }
}

# Windows hands a freshly written big file to the virus scanner, which can hold
# it for a second or two. Every copy and every archive write below therefore
# retries instead of failing the whole build on one unlucky moment.
function Copy-FileRetry {
    param([string]$Source, [string]$Destination, [int]$Attempts = 5)
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Copy-Item -LiteralPath $Source -Destination $Destination -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq $Attempts) { throw }
            Write-Detail "file busy - retrying the copy (attempt $attempt of $Attempts)"
            Start-Sleep -Seconds 2
        }
    }
}

function New-ZipArchive {
    # Zips a folder into one .zip file, atomically and with retries.
    #
    # Compress-Archive is deliberately not used. It opens every source file in
    # turn and aborts the build the moment one of them is busy, which is how a
    # 160 MB file copied seconds earlier can fail with "used by another
    # process". .NET's ZipFile reports the real error, writes to a .partial name
    # and only moves it into place when the archive is complete, so a failed
    # run never leaves a half-written zip behind.
    param([string]$SourceDirectory, [string]$DestinationPath, [int]$Attempts = 5)

    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
    $partial = "$DestinationPath.partial"

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction Stop }
            [System.IO.Compression.ZipFile]::CreateFromDirectory(
                $SourceDirectory,
                $partial,
                [System.IO.Compression.CompressionLevel]::Optimal,
                $false)

            $entries = 0
            $zip = [System.IO.Compression.ZipFile]::OpenRead($partial)
            try { $entries = $zip.Entries.Count } finally { $zip.Dispose() }
            if ($entries -eq 0) { throw "The archive came out empty: $SourceDirectory" }

            if (Test-Path -LiteralPath $DestinationPath) { Remove-Item -LiteralPath $DestinationPath -Force -ErrorAction Stop }
            Move-Item -LiteralPath $partial -Destination $DestinationPath -ErrorAction Stop
            return
        } catch {
            $inner = $_.Exception
            while ($inner.InnerException) { $inner = $inner.InnerException }
            $busy = ($inner -is [System.IO.IOException]) -or ($inner -is [System.UnauthorizedAccessException])
            if (-not $busy) { throw }
            if ($attempt -eq $Attempts) {
                if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
                throw ("Could not write {0} after {1} attempts: {2}. A virus scanner or another program is holding one of the files. Everything before this step is cached - close any Explorer window showing the build folders and run the build again." -f $DestinationPath, $Attempts, $inner.Message.TrimEnd('.'))
            }
            Write-Detail "archive busy - retrying (attempt $attempt of $Attempts)"
            Start-Sleep -Seconds 2
        }
    }
}

function Test-PythonModule {
    param([string]$Python, [string]$Module)
    & $Python -c "import $Module" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Get-PythonCommand {
    foreach ($candidate in @('python', 'python3', 'py')) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        $version = (& $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $version) { continue }
        $parts = $version.Trim().Split('.')
        if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) { return $candidate }
    }
    throw 'Habit Quest needs Python 3.10 or newer to build the bundled backend. Install it from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH".'
}

Write-Host ''
Write-Host '  Habit Quest - build the desktop installer' -ForegroundColor Yellow
Write-Host "  repository: $RepoRoot"

# ---------------------------------------------------------------- prerequisites
Write-Step 'Checking the build tools'
Assert-Tool 'node' 'Install Node.js 18 or newer from https://nodejs.org/.'
Assert-Tool 'npm' 'npm ships with Node.js; reinstall Node if it is missing.'

$nodeVersion = (& node --version).TrimStart('v')
$nodeMajor = [int]($nodeVersion.Split('.')[0])
if ($nodeMajor -lt 18) { throw "Node.js $nodeVersion is too old; the build needs 18 or newer." }
Write-Detail "node $nodeVersion"

$python = Get-PythonCommand
Write-Detail "$((& $python --version 2>&1).ToString().Trim()) ($python)"

$packagePath = Join-Path $DesktopDir 'package.json'
$package = Get-Content -LiteralPath $packagePath -Raw -ErrorAction Stop | ConvertFrom-Json

# ---------------------------------------------------------------------- version
if ($Bump -ne 'none') {
    Write-Step "Bumping the version ($Bump)"
    Push-Location $DesktopDir
    try {
        Invoke-Checked 'npm version' { & npm version $Bump --no-git-tag-version --allow-same-version }
    } finally {
        Pop-Location
    }
    $package = Get-Content -LiteralPath $packagePath -Raw -ErrorAction Stop | ConvertFrom-Json
}
$version = $package.version
$productName = $package.productName
Write-Detail "$productName $version"

# --------------------------------------------------------------- frozen backend
New-Item -ItemType Directory -Force -Path $BackendDist -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Force -Path $BuildDir -ErrorAction Stop | Out-Null

$backendExe = Join-Path $BackendDist 'habit-quest-backend.exe'

if ($SkipBackend) {
    Write-Step 'Skipping the bundled backend (-SkipBackend)'
    Write-Detail 'The packaged app will need Python 3.10+ on the machine that runs it.'
} else {
    Write-Step 'Building the standalone backend (PyInstaller)'
    $venv = Join-Path $BuildDir 'venv-backend'
    $venvPython = Join-Path $venv 'Scripts\python.exe'

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Detail "creating a build-only virtual environment in $venv"
        Invoke-Checked 'python -m venv' { & $python -m venv $venv }
    }

    if (-not (Test-PythonModule -Python $venvPython -Module 'PyInstaller')) {
        Write-Detail 'installing PyInstaller (first build only)'
        Invoke-Checked 'pip install pyinstaller' {
            & $venvPython -m pip install --disable-pip-version-check --quiet --upgrade pip pyinstaller
        }
    }
    $pyinstallerVersion = (& $venvPython -c 'import PyInstaller; print(PyInstaller.__version__)').Trim()
    Write-Detail "PyInstaller $pyinstallerVersion"

    if (Test-Path -LiteralPath $backendExe) { Remove-Item -LiteralPath $backendExe -Force -ErrorAction Stop }

    Invoke-Checked 'PyInstaller' {
        & $venvPython -m PyInstaller `
            --noconfirm `
            --clean `
            --onefile `
            --console `
            --name 'habit-quest-backend' `
            --distpath $BackendDist `
            --workpath (Join-Path $BuildDir 'pyinstaller-work') `
            --specpath (Join-Path $BuildDir 'pyinstaller-work') `
            --paths $RepoRoot `
            --add-data "$(Join-Path $RepoRoot 'static');static" `
            (Join-Path $DesktopDir 'backend_entry.py')
    }
    if (-not (Test-Path -LiteralPath $backendExe)) { throw "PyInstaller did not produce $backendExe." }
    Write-Detail ("backend: {0:N1} MB" -f ((Get-Item -LiteralPath $backendExe).Length / 1MB))

    Write-Step 'Smoke-testing the backend executable'
    Invoke-Checked 'backend smoke test' { & node (Join-Path $DesktopDir 'smoke-backend.js') $backendExe }
}

# ------------------------------------------------------------------ node deps
Write-Step 'Installing desktop dependencies'
if ($SkipInstall) {
    Write-Detail 'skipped (-SkipInstall)'
} else {
    Push-Location $DesktopDir
    try {
        Invoke-Checked 'npm install' { & npm install --no-audit --no-fund --loglevel=error }
    } finally {
        Pop-Location
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $DesktopDir 'node_modules\electron-builder'))) {
    throw 'electron-builder is not installed. Re-run without -SkipInstall.'
}

# --------------------------------------------------------------------- package
Write-Step 'Packaging the Electron app (installer + portable zip)'
if (Test-Path -LiteralPath $ReleaseDir) { Remove-Item -LiteralPath $ReleaseDir -Recurse -Force -ErrorAction Stop }
Push-Location $DesktopDir
try {
    Invoke-Checked 'electron-builder' { & npm run dist }
} finally {
    Pop-Location
}

$installer = Join-Path $ReleaseDir "Habit-Quest-Setup-$version.exe"
$portable = Join-Path $ReleaseDir "Habit-Quest-$version-win-x64.zip"
foreach ($artifact in @($installer, $portable)) {
    if (-not (Test-Path -LiteralPath $artifact)) { throw "Expected build output is missing: $artifact" }
}

# ------------------------------------------------------------------- bundle zip
if (-not $NoZip) {
    Write-Step 'Assembling the distribution zip'

    # Stage in a fresh folder under %TEMP%. An earlier version of this script
    # staged inside the repository, where a failed run left a stale folder
    # behind and any program watching that folder (Explorer, a scanner) could
    # hold the staged files open. A per-run temp folder starts empty every time
    # and is deleted even when the build fails.
    if (Test-Path -LiteralPath $LegacyStagingDir) {
        Remove-Item -LiteralPath $LegacyStagingDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    $staging = Join-Path ([System.IO.Path]::GetTempPath()) ('habit-quest-bundle-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $bundle = Join-Path $ReleaseDir "Habit-Quest-$version-windows-x64.zip"

    try {
        New-Item -ItemType Directory -Force -Path $staging -ErrorAction Stop | Out-Null
        Copy-FileRetry -Source $installer -Destination (Join-Path $staging "Habit-Quest-Setup-$version.exe")
        Copy-FileRetry -Source $portable -Destination (Join-Path $staging "Habit-Quest-$version-win-x64.zip")
        foreach ($doc in @('USER-GUIDE.md', 'BUILDING.md')) {
            $source = Join-Path $RepoRoot "docs\$doc"
            if (Test-Path -LiteralPath $source) {
                Copy-FileRetry -Source $source -Destination (Join-Path $staging $doc)
            }
        }
        Set-Content -LiteralPath (Join-Path $staging 'VERSION.txt') -Encoding UTF8 -ErrorAction Stop -Value @(
            "$productName $version",
            "Built $(Get-Date -Format 'yyyy-MM-dd HH:mm')",
            '',
            "Install: run Habit-Quest-Setup-$version.exe",
            "No install: unzip Habit-Quest-$version-win-x64.zip and run Habit Quest.exe"
        )

        New-ZipArchive -SourceDirectory $staging -DestinationPath $bundle
    } finally {
        if (Test-Path -LiteralPath $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Detail ("bundle: {0:N1} MB" -f ((Get-Item -LiteralPath $bundle).Length / 1MB))
}

# ---------------------------------------------------------------------- hashes
Get-ChildItem -LiteralPath $ReleaseDir -File -ErrorAction Stop |
    Where-Object { $_.Extension -in @('.exe', '.zip') } |
    ForEach-Object { "$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)  $($_.Name)" } |
    Set-Content -LiteralPath (Join-Path $ReleaseDir 'SHA256SUMS.txt') -Encoding ASCII -ErrorAction Stop

# --------------------------------------------------------------------- summary
$elapsed = (Get-Date) - $Started
Write-Host ''
Write-Host "  Done in $([int]$elapsed.TotalMinutes)m $($elapsed.Seconds)s" -ForegroundColor Green
Write-Host "  $ReleaseDir" -ForegroundColor Green
Get-ChildItem -LiteralPath $ReleaseDir -File |
    Where-Object { $_.Extension -in @('.exe', '.zip') } |
    Sort-Object Name |
    ForEach-Object { Write-Host ("    {0,-44} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB)) }
Write-Host ''
Write-Host '  Install:  run the Setup .exe (it creates the desktop icon)'
Write-Host "  Portable: unzip Habit-Quest-$version-win-x64.zip and run Habit Quest.exe"
Write-Host ''
