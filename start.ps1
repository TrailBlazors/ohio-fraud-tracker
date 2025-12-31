<#
.SYNOPSIS
    Start Ohio Fraud Tracker services

.PARAMETER Api
    Start only the API (default)

.PARAMETER Frontend  
    Start only the frontend

.PARAMETER All
    Start both API and frontend

.EXAMPLE
    .\start.ps1           # Start API
    .\start.ps1 -Frontend # Start frontend
    .\start.ps1 -All      # Start both
#>

param(
    [switch]$Api,
    [switch]$Frontend,
    [switch]$All
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Default to API if nothing specified
if (-not $Api -and -not $Frontend -and -not $All) {
    $Api = $true
}

if ($All) {
    $Api = $true
    $Frontend = $true
}

Write-Host ""
Write-Host "Ohio Fraud Tracker" -ForegroundColor Cyan
Write-Host "==================" -ForegroundColor Cyan
Write-Host ""

if ($Api) {
    if ($Frontend) {
        # Start API in background
        Write-Host "Starting API in background..." -ForegroundColor Yellow
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ProjectRoot\api'; .\start.ps1"
        Start-Sleep -Seconds 2
    } else {
        # Start API in foreground
        Set-Location "$ProjectRoot\api"
        & .\start.ps1
        exit
    }
}

if ($Frontend) {
    Write-Host "Starting frontend..." -ForegroundColor Yellow
    Set-Location "$ProjectRoot\frontend"
    
    if (-not (Test-Path "node_modules")) {
        Write-Host "Installing frontend dependencies..."
        npm install
    }
    
    npm run dev
}
