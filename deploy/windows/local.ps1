param([ValidateSet('start', 'stop', 'logs')][string]$Action = 'start')
$ErrorActionPreference = 'Continue' # Docker writes progress to stderr; check exit codes below.
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $projectRoot

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        $dockerBin = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin'
        if (Test-Path (Join-Path $dockerBin 'docker.exe')) {
            $env:Path = "$dockerBin;$env:Path"
        } else {
            throw 'Install Docker Desktop for Windows (WSL 2 / Linux containers), then run START-WINDOWS.cmd again. https://docs.docker.com/desktop/setup/install/windows-install/'
        }
    }

    docker info --format '{{.OSType}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (Test-Path $desktop) { Start-Process $desktop }
        Write-Host 'Waiting for Docker Desktop (up to 2 minutes)...'
        $deadline = (Get-Date).AddMinutes(2)
        do {
            Start-Sleep -Seconds 3
            docker info --format '{{.OSType}}' *> $null
            if ($LASTEXITCODE -eq 0) { break }
        } while ((Get-Date) -lt $deadline)
        if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop, wait for Engine running, then try again.' }
    }
    $engine = docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0 -or $engine.Trim() -ne 'linux') {
        throw 'Switch Docker Desktop to Linux containers and try again.'
    }
    docker compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is missing. Update Docker Desktop.' }

    # An explicit empty env file prevents loading a production .env from this directory.
    $composeArgs = @('compose', '--env-file', 'deploy/windows/local.env', '-p', 'slovech-local', '-f', 'compose.local.yaml')
    if ($Action -eq 'stop') {
        & docker @composeArgs stop
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop the local application.' }
        Write-Host 'Stopped. Local notes and data are preserved.'
        exit 0
    }
    if ($Action -eq 'logs') {
        & docker @composeArgs logs --tail 100 -f app
        exit $LASTEXITCODE
    }

    if (-not (Test-Path '.env.local')) {
        Write-Host 'First setup: use a NEW TEST bot from @BotFather. Do not use a bot already running elsewhere.'
        function Read-Key([string]$Label) {
            $secure = Read-Host $Label -AsSecureString
            $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            try { $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim() }
            finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
            if ($value -notmatch '^[A-Za-z0-9_,:-]+$') { throw 'The key is empty or contains unsupported characters.' }
            return $value
        }
        $botKey = Read-Key 'Test BOT_TOKEN'
        $aiKey = Read-Key 'GEMINI_API_KEYS'
        $template = [IO.File]::ReadAllText((Join-Path $projectRoot 'deploy/windows/keys.example'))
        $template = $template.Replace('BOT_TOKEN=', "BOT_TOKEN=$botKey").Replace('GEMINI_API_KEYS=', "GEMINI_API_KEYS=$aiKey")
        [IO.File]::WriteAllText((Join-Path $projectRoot '.env.local'), $template, (New-Object Text.UTF8Encoding($false)))
        $botKey = $null
        $aiKey = $null
        $template = $null
        Write-Host 'Keys saved locally in .env.local. They are not included in the image.'
    }

    docker image inspect slovech-local:2 *> $null
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path 'slovech-local-image.tar') {
            Write-Host 'Loading the prepared image...'
            docker load -i slovech-local-image.tar
            if ($LASTEXITCODE -ne 0) { throw 'Could not load slovech-local-image.tar.' }
        } else {
            Write-Host 'First start: building the image. Internet is required; this may take several minutes.'
            & docker @composeArgs build --pull app
            if ($LASTEXITCODE -ne 0) { throw 'Image build failed. Check the internet connection and Docker output above.' }
        }
    }
    & docker @composeArgs up -d --no-build --pull never --wait --wait-timeout 240
    if ($LASTEXITCODE -ne 0) {
        & docker @composeArgs logs --tail 60 app
        throw 'Application did not become ready. Check whether localhost:8000 is already in use and read the log above.'
    }
    $statusJson = & docker @composeArgs exec -T app python -c 'from scripts.local_stack import status_path; print(status_path().read_text())'
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the startup status. Open LOGS-WINDOWS.cmd.' }
    $status = $statusJson | ConvertFrom-Json -ErrorAction Stop
    Write-Host "Ready! Open $($status.bot_url), send /start, then press the Mini App button."
    Write-Host "Mini App: $($status.miniapp_url)"
    Write-Host 'Local API: http://localhost:8000/ready. All data stays in local Docker volumes.'
    Start-Process $status.bot_url
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
