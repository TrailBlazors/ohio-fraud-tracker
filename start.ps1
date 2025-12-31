<#
.SYNOPSIS
    Start Ohio Fraud Tracker services

.DESCRIPTION
    By default, starts both the API and frontend.
    The API runs in a separate window, frontend in the current window.

.PARAMETER Api
    Start only the API

.PARAMETER Frontend  
    Start only the frontend

.PARAMETER Setup
    Run setup for both API and frontend

.PARAMETER Status
    Show status of both services

.EXAMPLE
    .\start.ps1           # Start both API and frontend
    .\start.ps1 -Api      # Start only API
    .\start.ps1 -Frontend # Start only frontend
    .\start.ps1 -Setup    # First-time setup
#>

param(
    [switch]$Api,
    [switch]$Frontend,
    [switch]$Setup,
    [switch]$Status
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiPath = Join-Path $ProjectRoot "api"
$FrontendPath = Join-Path $ProjectRoot "frontend"

# Banner
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "         Ohio Fraud Tracker                     " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Setup mode
if ($Setup) {
    Write-Host "Setting up Ohio Fraud Tracker..." -ForegroundColor Yellow
    Write-Host ""
    
    # API setup
    Write-Host "[1/2] Setting up API..." -ForegroundColor Green
    Set-Location $ProjectRoot
    
    if (-not (Test-Path "venv313")) {
        Write-Host "  Creating Python virtual environment (Python 3.13)..."
        py -3.13 -m venv venv313
    }
    
    $VenvPip = Join-Path $ProjectRoot "venv313\Scripts\pip.exe"
    Write-Host "  Installing Python dependencies..."
    & $VenvPip install -r (Join-Path $ApiPath "requirements.txt")
    
    if (-not (Test-Path (Join-Path $ApiPath ".env"))) {
        Copy-Item (Join-Path $ApiPath ".env.example") (Join-Path $ApiPath ".env")
    }
    
    Set-Location $ApiPath
    New-Item -ItemType Directory -Path "data" -Force | Out-Null
    
    # Frontend setup
    Write-Host ""
    Write-Host "[2/2] Setting up Frontend..." -ForegroundColor Green
    Set-Location $FrontendPath
    
    if (-not (Test-Path "node_modules")) {
        Write-Host "  Installing Node dependencies..."
        npm install
    }
    
    Write-Host ""
    Write-Host "Setup complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Run '.\start.ps1' to start both services"
    Write-Host ""
    exit 0
}

# Status mode
if ($Status) {
    Write-Host "Service Status" -ForegroundColor Yellow
    Write-Host ""
    
    # Check API
    Write-Host "API:" -ForegroundColor Cyan
    $VenvPython = Join-Path $ProjectRoot "venv313\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        Write-Host "  Python venv: OK (Python 3.13)" -ForegroundColor Green
        
        # Check if API is running
        $apiRunning = Test-NetConnection -ComputerName localhost -Port 8000 -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
        if ($apiRunning.TcpTestSucceeded) {
            Write-Host "  Server:      Running on port 8000" -ForegroundColor Green
        } else {
            Write-Host "  Server:      Not running" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Python venv: Not found (run .\start.ps1 -Setup)" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host "Frontend:" -ForegroundColor Cyan
    if (Test-Path (Join-Path $FrontendPath "node_modules")) {
        Write-Host "  Node modules: OK" -ForegroundColor Green
    } else {
        Write-Host "  Node modules: Not installed (run .\start.ps1 -Setup)" -ForegroundColor Red
    }
    
    Write-Host ""
    exit 0
}

# Default: start both if no flags specified
if (-not $Api -and -not $Frontend) {
    $Api = $true
    $Frontend = $true
}

# Start services
if ($Api -and $Frontend) {
    # Start both - API in background window, frontend in foreground
    Write-Host "Starting API in new window..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$ApiPath'; .\start.ps1"
    
    Write-Host "Waiting for API to start..."
    Start-Sleep -Seconds 3
    
    Write-Host "Starting frontend..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  API:      http://localhost:8000" -ForegroundColor White
    Write-Host "  API Docs: http://localhost:8000/docs" -ForegroundColor White
    Write-Host "  Frontend: http://localhost:4321" -ForegroundColor White
    Write-Host ""
    Write-Host "Press Ctrl+C to stop frontend (close API window separately)" -ForegroundColor DarkGray
    Write-Host ""
    
    Set-Location $FrontendPath
    npm run dev
}
elseif ($Api) {
    # Start only API in foreground
    Write-Host "Starting API..." -ForegroundColor Yellow
    Set-Location $ApiPath
    & .\start.ps1
}
elseif ($Frontend) {
    # Start only frontend in foreground
    Write-Host "Starting frontend..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Frontend: http://localhost:4321" -ForegroundColor White
    Write-Host ""
    
    Set-Location $FrontendPath
    npm run dev
}
