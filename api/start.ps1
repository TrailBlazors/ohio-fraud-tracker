<#
.SYNOPSIS
    Start the Ohio Fraud Tracker API

.DESCRIPTION
    Activates the virtual environment and starts the FastAPI server.

.PARAMETER Port
    Port to run the API on (default: 8000)

.PARAMETER Prod
    Run in production mode (no auto-reload)

.PARAMETER Setup
    Run initial setup (create venv, install deps)

.PARAMETER Status
    Show database status and exit

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Port 3000
    .\start.ps1 -Setup
    .\start.ps1 -Status
#>

param(
    [int]$Port = 8000,
    [switch]$Prod,
    [switch]$Setup,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$VenvPip = Join-Path $ScriptDir ".venv\Scripts\pip.exe"

# Banner
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "         Ohio Fraud Tracker API                 " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# Setup mode
if ($Setup) {
    Write-Host "`nSetting up development environment..." -ForegroundColor Yellow
    
    if (-not (Test-Path ".venv")) {
        Write-Host "Creating virtual environment..."
        python -m venv .venv
    }
    
    Write-Host "Installing dependencies..."
    & $VenvPip install -r requirements.txt
    
    Write-Host "Creating data directory..."
    New-Item -ItemType Directory -Path "data" -Force | Out-Null
    
    if (-not (Test-Path ".env")) {
        Write-Host "Creating .env from example..."
        Copy-Item ".env.example" ".env"
    }
    
    Write-Host "`nSetup complete!" -ForegroundColor Green
    Write-Host "Run '.\start.ps1' to start the API`n"
    exit 0
}

# Check venv
if (-not (Test-Path $VenvPython)) {
    Write-Host "Virtual environment not found!" -ForegroundColor Red
    Write-Host "Run: .\start.ps1 -Setup"
    exit 1
}

# Status mode
if ($Status) {
    Write-Host "`nDatabase Status" -ForegroundColor Yellow
    & $VenvPython -c @"
import sys
sys.path.insert(0, '.')
from app.database import get_db_info, get_db_context
from app.models import Award, Recipient
from sqlalchemy import func

info = get_db_info()
print(f'Database: {info["type"]}')

with get_db_context() as db:
    awards = db.query(func.count(Award.id)).scalar() or 0
    recipients = db.query(func.count(Recipient.id)).scalar() or 0
    total = db.query(func.sum(Award.amount)).scalar() or 0
    
    print(f'Awards:     {awards:,}')
    print(f'Recipients: {recipients:,}')
    print(f'Total:      \${total:,.2f}')
"@
    exit 0
}

# Start server
Write-Host ""
Write-Host "  Server:    http://127.0.0.1:$Port" -ForegroundColor White
Write-Host "  API Docs:  http://127.0.0.1:$Port/docs" -ForegroundColor White
if ($Prod) {
    Write-Host "  Mode:      Production" -ForegroundColor White
} else {
    Write-Host "  Mode:      Development (auto-reload)" -ForegroundColor White
}
Write-Host ""
Write-Host "  Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

if ($Prod) {
    & $VenvPython run.py --port $Port --prod
} else {
    & $VenvPython run.py --port $Port
}
