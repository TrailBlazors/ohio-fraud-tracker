<# 
.SYNOPSIS
    Sets up Windows Task Scheduler tasks for Ohio Fraud Tracker correlation jobs.

.DESCRIPTION
    Creates three scheduled tasks:
    - Nightly verification (2 AM daily)
    - Weekly full scan (3 AM Sunday)
    - Hourly quick scan (every hour)

.NOTES
    Run as Administrator
    
.EXAMPLE
    .\setup_windows_tasks.ps1
    .\setup_windows_tasks.ps1 -ProjectPath "C:\Projects\ohio-fraud-tracker"
#>

param(
    [string]$ProjectPath = "C:\Projects\ohio-fraud-tracker",
    [string]$PythonPath = "C:\Projects\ohio-fraud-tracker\api\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

Write-Host "Setting up Ohio Fraud Tracker scheduled tasks..." -ForegroundColor Cyan

# Verify paths exist
if (-not (Test-Path $ProjectPath)) {
    Write-Error "Project path not found: $ProjectPath"
    exit 1
}

if (-not (Test-Path $PythonPath)) {
    Write-Warning "Python path not found: $PythonPath"
    Write-Host "Please update the -PythonPath parameter" -ForegroundColor Yellow
    exit 1
}

# Task settings
$TaskFolder = "OhioFraudTracker"
$WorkingDir = "$ProjectPath\api"

# Create task folder if it doesn't exist
$scheduler = New-Object -ComObject Schedule.Service
$scheduler.Connect()
$rootFolder = $scheduler.GetFolder("\")

try {
    $existingFolder = $rootFolder.GetFolder($TaskFolder)
    Write-Host "Task folder already exists" -ForegroundColor Yellow
} catch {
    $rootFolder.CreateFolder($TaskFolder)
    Write-Host "Created task folder: $TaskFolder" -ForegroundColor Green
}

# Helper function to create task
function New-CorrelationTask {
    param(
        [string]$TaskName,
        [string]$JobType,
        [string]$TriggerDescription,
        $Trigger
    )
    
    $Action = New-ScheduledTaskAction `
        -Execute $PythonPath `
        -Argument "-m scripts.scheduled_jobs $JobType --output logs\$JobType`_`$(Get-Date -Format 'yyyyMMdd_HHmmss').json" `
        -WorkingDirectory $WorkingDir
    
    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    
    $Principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
    
    $Task = New-ScheduledTask `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Ohio Fraud Tracker - $TriggerDescription"
    
    # Remove existing task if present
    $existingTask = Get-ScheduledTask -TaskName $TaskName -TaskPath "\$TaskFolder\" -ErrorAction SilentlyContinue
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName $TaskName -TaskPath "\$TaskFolder\" -Confirm:$false
        Write-Host "  Removed existing task: $TaskName" -ForegroundColor Yellow
    }
    
    Register-ScheduledTask `
        -TaskName $TaskName `
        -TaskPath "\$TaskFolder\" `
        -InputObject $Task
    
    Write-Host "  Created task: $TaskName ($TriggerDescription)" -ForegroundColor Green
}

# Create logs directory
$LogsDir = "$WorkingDir\logs"
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir | Out-Null
    Write-Host "Created logs directory: $LogsDir" -ForegroundColor Green
}

Write-Host "`nCreating scheduled tasks..." -ForegroundColor Cyan

# 1. Nightly verification - 2 AM daily
$NightlyTrigger = New-ScheduledTaskTrigger -Daily -At "2:00 AM"
New-CorrelationTask `
    -TaskName "NightlyVerification" `
    -JobType "nightly" `
    -TriggerDescription "Daily at 2 AM - SOS verification" `
    -Trigger $NightlyTrigger

# 2. Weekly full scan - 3 AM Sunday
$WeeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "3:00 AM"
New-CorrelationTask `
    -TaskName "WeeklyFullScan" `
    -JobType "weekly" `
    -TriggerDescription "Sunday at 3 AM - Full correlation scan" `
    -Trigger $WeeklyTrigger

# 3. Hourly quick scan
$HourlyTrigger = New-ScheduledTaskTrigger -Once -At "12:00 AM" `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 365)
New-CorrelationTask `
    -TaskName "HourlyQuickScan" `
    -JobType "hourly" `
    -TriggerDescription "Every hour - Quick scan of new data" `
    -Trigger $HourlyTrigger

Write-Host "`n✓ All tasks created successfully!" -ForegroundColor Green
Write-Host "`nTo view tasks: Open Task Scheduler > Task Scheduler Library > $TaskFolder" -ForegroundColor Cyan
Write-Host "To run manually: Right-click task > Run" -ForegroundColor Cyan
Write-Host "`nLogs will be written to: $LogsDir" -ForegroundColor Cyan

# Show task status
Write-Host "`nTask Status:" -ForegroundColor Cyan
Get-ScheduledTask -TaskPath "\$TaskFolder\" | Format-Table TaskName, State, LastRunTime, NextRunTime -AutoSize
