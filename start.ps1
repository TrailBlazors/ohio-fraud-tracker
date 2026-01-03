<#
.SYNOPSIS
    Start Ohio Fraud Tracker

.EXAMPLE
    .\start.ps1              # Start API (new window) + Frontend (this window)
    .\start.ps1 -Api         # Start API only (this window)
    .\start.ps1 -Frontend    # Start frontend only (this window)
    .\start.ps1 -Setup       # First-time setup
#>

param(
    [switch]$Api,
    [switch]$Frontend,
    [switch]$Setup
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiPath = Join-Path $ProjectRoot "api"
$FrontendPath = Join-Path $ProjectRoot "frontend"
$VenvPython = Join-Path $ApiPath ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "         Ohio Fraud Tracker                     " -ForegroundColor Cyan  
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

if ($Setup) {
    Write-Host "Setting up..." -ForegroundColor Yellow
    
    Set-Location $ApiPath
    if (-not (Test-Path ".venv")) {
        Write-Host "Creating Python venv..."
        py -3.13 -m venv .venv
    }
    
    Write-Host "Installing Python deps..."
    & "$ApiPath\.venv\Scripts\pip.exe" install -r requirements.txt
    & "$ApiPath\.venv\Scripts\pip.exe" install "psycopg[binary]"
    
    Set-Location $FrontendPath
    if (-not (Test-Path "node_modules")) {
        Write-Host "Installing Node deps..."
        npm install
    }
    
    Write-Host "`nSetup complete!" -ForegroundColor Green
    exit 0
}

if ($Api) {
    # API only in this window
    Write-Host "Starting API at http://localhost:8000" -ForegroundColor White
    Set-Location $ApiPath
    & $VenvPython run.py --no-reload
}
elseif ($Frontend) {
    # Frontend only in this window
    Write-Host "Starting frontend at http://localhost:4321" -ForegroundColor White
    Set-Location $FrontendPath
    npm run dev
}
else {
    # Default: API in new window, Frontend in this window
    Write-Host "Starting API in new window..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ApiPath'; & '$VenvPython' run.py --no-reload"
    
    Start-Sleep -Seconds 2
    
    Write-Host "Starting frontend..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  API:      http://localhost:8000" -ForegroundColor White
    Write-Host "  Frontend: http://localhost:4321" -ForegroundColor White
    Write-Host ""
    
    Set-Location $FrontendPath
    npm run dev
}
