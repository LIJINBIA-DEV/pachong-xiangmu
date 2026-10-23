[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
$projectDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$apiBase = 'http://127.0.0.1:18080'
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'

function Assert-ProjectProcess($process) {
    if (-not $process -or $process.CommandLine -notmatch '(?i)\buvicorn\s+api\.main:app\b') {
        throw 'Port 18080 is not owned by this project uvicorn process. Nothing was stopped.'
    }
    $ancestor = $process
    for ($depth = 0; $depth -lt 4 -and $ancestor; $depth++) {
        if ($ancestor.ExecutablePath -and $ancestor.ExecutablePath.Equals($pythonPath, [StringComparison]::OrdinalIgnoreCase)) { return }
        $ancestor = Get-CimInstance Win32_Process -Filter "ProcessId=$($ancestor.ParentProcessId)"
    }
    throw 'Cannot verify that the backend belongs to this project. Nothing was stopped.'
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Project Python runtime is missing.' }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 18080 -ErrorAction SilentlyContinue)
    $ownerIds = @($listeners.OwningProcess | Select-Object -Unique)
    if ($ownerIds.Count -gt 1) { throw 'Multiple processes own port 18080. Nothing was stopped.' }
    if ($ownerIds.Count -eq 1) {
        $backendProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($ownerIds[0])"
        Assert-ProjectProcess $backendProcess
        $crawl = Invoke-RestMethod "$apiBase/api/crawler/status" -TimeoutSec 5
        if ($crawl.status -notin @('idle', 'error')) { throw 'Collection is active. Finish or stop it from the console before restarting.' }
        $files = (Invoke-RestMethod "$apiBase/api/data/files" -TimeoutSec 5).files
        $reviewFile = $files | Where-Object { $_.path -match '^weibo/' -and $_.name -notmatch 'comment|creator|guard_replay|semantic_checkpoint' } | Select-Object -First 1
        if ($reviewFile) {
            $subject = Invoke-RestMethod ("$apiBase/api/data/image-subject?file=" + [uri]::EscapeDataString($reviewFile.path)) -TimeoutSec 30
            if ($subject.busy) { throw 'Image recognition is active. Wait until it finishes before restarting.' }
        }
        if ($CheckOnly) {
            Write-Host 'Verified idle MediaCrawler backend. Check-only mode: no process was stopped or started.'
            exit 0
        }
        # Only stop the verified port owner; never stop unrelated Python or Node processes.
        $verified = Get-CimInstance Win32_Process -Filter "ProcessId=$($backendProcess.ProcessId)"
        if (-not $verified -or $verified.CreationDate -ne $backendProcess.CreationDate) { throw 'Backend process changed during verification. Retry.' }
        $crawl = Invoke-RestMethod "$apiBase/api/crawler/status" -TimeoutSec 5
        if ($crawl.status -notin @('idle', 'error')) { throw 'Collection started during verification. Nothing was stopped.' }
        Stop-Process -Id $backendProcess.ProcessId
        for ($attempt = 0; $attempt -lt 50; $attempt++) {
            if (-not (Get-NetTCPConnection -State Listen -LocalPort 18080 -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 100
        }
        if (Get-NetTCPConnection -State Listen -LocalPort 18080 -ErrorAction SilentlyContinue) { throw 'Port 18080 is still occupied. New backend was not started.' }
    } elseif ($CheckOnly) {
        Write-Host 'No backend is listening. Check-only mode: no process was started.'
        exit 0
    }
    $logDir = Join-Path $projectDir 'artifacts\startup'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '18080') -WorkingDirectory $projectDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "$stamp-api-out.log") -RedirectStandardError (Join-Path $logDir "$stamp-api-error.log") | Out-Null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod "$apiBase/api/health" -TimeoutSec 2
            if ($health.status -eq 'ok') {
                & $pythonPath (Join-Path $projectDir 'scripts\check_backend_version.py')
                if ($LASTEXITCODE -eq 0) {
                    Write-Host 'The latest backend is ready. Return to the original review tab and click Retry.'
                    exit 0
                }
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw "Backend did not become ready. See logs in $logDir."
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
