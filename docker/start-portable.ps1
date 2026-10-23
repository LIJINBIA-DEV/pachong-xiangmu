param([switch]$Rebuild)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install and start Docker Desktop (Linux containers) first.' }
$dockerOS = docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker is not ready. Start Docker Desktop and retry.' }
if ($dockerOS -ne 'linux') { throw 'Switch Docker Desktop to Linux containers and retry.' }
if (-not (Test-Path -LiteralPath '.env.portable')) {
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $bytes = New-Object byte[] 8
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $password = -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
    $template = (Get-Content '.env.portable.example' -Raw).Replace('BROWSER_PASSWORD=', "BROWSER_PASSWORD=$password")
    [IO.File]::WriteAllText((Join-Path $pwd '.env.portable'), $template, (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Created .env.portable. Configure your own model API keys there; keep this file private.'
}
$composeArgs = @('compose', '--env-file', '.env.portable', '-f', 'compose.portable.yaml')
$imageName = & docker @composeArgs config --images
if ($LASTEXITCODE -ne 0) { throw 'Invalid .env.portable or Compose configuration.' }
$localImage = & docker image ls --quiet $imageName
if (-not $localImage) {
    $archive = @((Join-Path $pwd 'mediacrawler-image.tar'), (Join-Path (Split-Path $pwd -Parent) 'mediacrawler-image.tar')) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($archive) {
        & docker load --input $archive
        if ($LASTEXITCODE -ne 0) { throw 'Could not import the bundled Docker image.' }
    }
}
if ($Rebuild) {
    & docker @composeArgs build
    if ($LASTEXITCODE -ne 0) { throw 'Image build failed; see the error above.' }
}
& docker @composeArgs up -d --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Run docker compose --env-file .env.portable -f compose.portable.yaml logs --tail 100' }
Write-Host 'Started. Default workbench: http://127.0.0.1:18180'
Write-Host 'Browser password is BROWSER_PASSWORD in .env.portable. Data stays in Docker volumes.'
