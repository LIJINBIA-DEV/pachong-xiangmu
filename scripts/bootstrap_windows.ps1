[CmdletBinding()]
param(
    [switch]$SetupOnly,
    [switch]$NoOpen,
    [switch]$Repair,
    [ValidateSet('auto', 'chrome', 'msedge', 'chromium')]
    [string]$BrowserChannel = 'auto',
    [int]$ApiPort = 18080,
    [int]$WebPort = 5173
)

# Windows PowerShell 5.1 compatible. Runtime installs are project-local.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Keep Windows built-in modules discoverable when launched from PowerShell 7.
$env:PSModulePath = (Join-Path $PSHOME 'Modules') + ';' + $env:PSModulePath
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeRoot = Join-Path $projectRoot '.runtime'
$logStarted = $false
$setupLock = $null

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

function Get-FileDigest([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}

function Get-VerifiedDownload([string]$Url, [string]$Destination, [string]$Hash) {
    if ((Test-Path -LiteralPath $Destination) -and (Get-FileDigest $Destination) -eq $Hash) { return }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Write-Host "Downloading: $Url (attempt $attempt/3)"
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile "$Destination.part" -TimeoutSec 300
            if ((Get-FileDigest "$Destination.part") -ne $Hash) { throw 'SHA256 verification failed.' }
            Move-Item -LiteralPath "$Destination.part" -Destination $Destination -Force
            return
        } catch {
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

function Get-InputsHash([string[]]$Paths) {
    return (($Paths | ForEach-Object { (Get-FileDigest (Join-Path $projectRoot $_)).ToUpperInvariant() }) -join ':')
}

try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'This launcher supports Windows 10/11 x64 only.'
    }
    Set-Location -LiteralPath $projectRoot
    foreach ($required in @('pyproject.toml', 'uv.lock', 'webui/package-lock.json', 'scripts/project_session.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $required))) { throw "Incomplete package: $required. Extract the entire ZIP before starting." }
    }
    # Never change dependencies underneath an already running project session.
    $owners = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
        $_.CommandLine -and $_.CommandLine.Contains($projectRoot) -and $_.CommandLine.Contains('project_session.py')
    })
    if ($owners.Count -gt 0) { throw 'This project is already running. Keep its CMD window open; do not start a second copy.' }
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $setupLock = [IO.File]::Open((Join-Path $runtimeRoot 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $logs = Join-Path $projectRoot 'artifacts/setup'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $logPath = Join-Path $logs ((Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    Start-Transcript -LiteralPath $logPath -Force | Out-Null
    $logStarted = $true
    Write-Host 'MediaCrawler: first run installs dependencies; later runs reuse them.'
    Write-Host "Setup log: $logPath"
    $downloads = Join-Path $runtimeRoot 'downloads'
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null

    Write-Host '[1/5] Preparing uv and Node.js...'
    $uvDir = Join-Path $runtimeRoot 'uv-0.13.1'
    $uvExe = Join-Path $uvDir 'uv.exe'
    if (-not (Test-Path -LiteralPath $uvExe)) {
        $archive = Join-Path $downloads 'uv-0.13.1.zip'
        Get-VerifiedDownload 'https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip' $archive '3b2661a463a5baea7f5076ea2b25ab71d77f36a6c0d809e5350651792f80a672'
        Expand-Archive -LiteralPath $archive -DestinationPath $uvDir -Force
    }
    $nodeDir = Join-Path $runtimeRoot 'node-v22.23.3-win-x64'
    $nodeExe = Join-Path $nodeDir 'node.exe'
    if (-not (Test-Path -LiteralPath $nodeExe)) {
        $archive = Join-Path $downloads 'node-v22.23.3-win-x64.zip'
        Get-VerifiedDownload 'https://nodejs.org/dist/v22.23.3/node-v22.23.3-win-x64.zip' $archive '2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71'
        Expand-Archive -LiteralPath $archive -DestinationPath $runtimeRoot -Force
    }
    $env:PATH = "$uvDir;$nodeDir;$env:PATH"
    $env:PYTHONUTF8 = '1'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtimeRoot 'python'
    $env:UV_CACHE_DIR = Join-Path $runtimeRoot 'uv-cache'
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
    $env:UV_LINK_MODE = 'copy'
    $env:UV_HTTP_TIMEOUT = '120'
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $runtimeRoot 'browsers'
    $env:PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT = '120000'
    $env:MEDIACRAWLER_CONTAINER_MODE = '0'
    $env:NO_PROXY = (($env:NO_PROXY, 'localhost', '127.0.0.1', '::1') | Where-Object { $_ }) -join ','
    $env:MEDIACRAWLER_API_PORT = "$ApiPort"

    Write-Host '[2/5] Preparing Python 3.11 and packages...'
    $pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
    $pythonOk = $false
    if (Test-Path -LiteralPath $pythonExe) {
        & $pythonExe scripts/check_desktop_environment.py --check-python-env
        $pythonOk = $LASTEXITCODE -eq 0
    }
    if (-not $pythonOk) {
        $venvDir = Join-Path $projectRoot '.venv'
        if (Test-Path -LiteralPath $venvDir) {
            # Preserve an invalid copied environment instead of deleting it.
            $resolved = (Get-Item -LiteralPath $venvDir).FullName
            if ($resolved -ne $venvDir -or (Get-Item -LiteralPath $venvDir).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected .venv path.' }
            Rename-Item -LiteralPath $venvDir -NewName ('.venv.previous-' + (Get-Date -Format 'yyyyMMddHHmmss'))
        }
        Invoke-Checked $uvExe @('python', 'install', '3.11')
        Invoke-Checked $uvExe @('venv', '--python', '3.11', '.venv')
    }
    $pythonHash = Get-InputsHash @('pyproject.toml', 'uv.lock')
    $pythonStamp = Join-Path $runtimeRoot 'python-inputs.txt'
    if ($Repair -or -not $pythonOk -or -not (Test-Path -LiteralPath $pythonStamp) -or (Get-Content -LiteralPath $pythonStamp -Raw).Trim() -ne $pythonHash) {
        Invoke-Checked $uvExe @('sync', '--locked', '--inexact', '--python', '3.11')
        Set-Content -LiteralPath $pythonStamp -Value $pythonHash -Encoding ASCII
    }
    # Runtime subprocesses must use the environment already prepared here.
    $env:UV_NO_SYNC = '1'

    Write-Host '[3/5] Preparing the web interface...'
    $webHash = Get-InputsHash @('webui/package.json', 'webui/package-lock.json')
    $webStamp = Join-Path $runtimeRoot 'web-inputs.txt'
    if ($Repair -or -not (Test-Path -LiteralPath (Join-Path $projectRoot 'webui/node_modules/vite/bin/vite.js')) -or -not (Test-Path -LiteralPath $webStamp) -or (Get-Content -LiteralPath $webStamp -Raw).Trim() -ne $webHash) {
        Push-Location (Join-Path $projectRoot 'webui')
        try { Invoke-Checked (Join-Path $nodeDir 'npm.cmd') @('ci', '--no-audit', '--no-fund') } finally { Pop-Location }
        Set-Content -LiteralPath $webStamp -Value $webHash -Encoding ASCII
    }

    Write-Host '[4/5] Checking the collection browser...'
    $channel = 'chromium'
    $chromePaths = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
    $edgePaths = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")
    if (@($chromePaths | Where-Object { Test-Path -LiteralPath $_ }).Count) { $channel = 'chrome' }
    elseif (@($edgePaths | Where-Object { Test-Path -LiteralPath $_ }).Count) { $channel = 'msedge' }
    if ($BrowserChannel -ne 'auto') { $channel = $BrowserChannel }
    & $pythonExe scripts/check_desktop_environment.py --browser-only --channel $channel
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing an independent Chromium browser...'
        Invoke-Checked $pythonExe @('scripts/install_desktop_browser.py')
        $channel = 'chromium'
        Invoke-Checked $pythonExe @('scripts/check_desktop_environment.py', '--browser-only', '--channel', $channel)
    }
    $env:MEDIACRAWLER_BROWSER_CHANNEL = $channel

    Write-Host '[5/5] Checking application imports and initial settings...'
    Invoke-Checked $pythonExe @('scripts/check_desktop_environment.py', '--initialize')
    Write-Host 'Ready. Choose LOCAL mode and scan with your own account. Enter your own API keys in Settings.'
    if ($logStarted) { Stop-Transcript | Out-Null; $logStarted = $false }
    $setupLock.Dispose(); $setupLock = $null
    if ($SetupOnly) { exit 0 }
    $sessionArgs = @('-u', 'scripts/project_session.py', '--api-port', "$ApiPort", '--web-port', "$WebPort")
    if ($NoOpen) { $sessionArgs += '--no-open' }
    Invoke-Checked $pythonExe $sessionArgs
    exit 0
} catch {
    Write-Host "START FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Check the error above and artifacts/setup logs, fix network/disk access, then double-click again.'
    Write-Host 'Do not delete data or browser_data to fix an installation error.'
    exit 1
} finally {
    if ($setupLock) { $setupLock.Dispose() }
    if ($logStarted) { Stop-Transcript | Out-Null }
}
