<#
.SYNOPSIS
    Git commits for recent Ohio Fraud Tracker work
#>

Write-Host "Ohio Fraud Tracker - Git Commits" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan
Write-Host ""

$ProjectRoot = "C:\Projects\ohio-fraud-tracker"
Set-Location $ProjectRoot

# Clean up empty directories
if (Test-Path "scripts\tests") {
    Remove-Item "scripts\tests" -Force -ErrorAction SilentlyContinue
}

# Show current status
Write-Host "Current git status:" -ForegroundColor Yellow
git status --short
Write-Host ""

$confirm = Read-Host "Proceed with commits? (y/n)"
if ($confirm -ne "y") {
    Write-Host "Aborted."
    exit
}

# Commit 1: Correlation engine
Write-Host "`n[1/6] Committing correlation engine..." -ForegroundColor Green
git add src/correlation/
git commit -m "Add correlation engine for fraud detection"

# Commit 2: Ohio Checkbook importer
Write-Host "`n[2/6] Committing Ohio Checkbook importer..." -ForegroundColor Green
git add api/scripts/import_ohio_checkbook.py
git add data/
git commit -m "Add Ohio Checkbook CSV importer"

# Commit 3: Scheduled jobs
Write-Host "`n[3/6] Committing scheduled jobs..." -ForegroundColor Green
git add api/scripts/scheduled_jobs.py
git add api/scripts/run_correlation.py
git add scripts/setup_windows_tasks.ps1
git commit -m "Add scheduled correlation jobs"

# Commit 4: API startup improvements
Write-Host "`n[4/6] Committing API startup improvements..." -ForegroundColor Green
git add api/run.py
git add api/dev.py
git add api/start.ps1
git add api/start.bat
git add api/app/__main__.py
git add api/README.md
git add start.ps1
git add start-api.bat
git commit -m "Improve API startup experience"

# Commit 5: File reorganization
Write-Host "`n[5/6] Committing file reorganization..." -ForegroundColor Green
git add scripts/examples/
git add api/scripts/seed_data.py
git add api/tests/
git commit -m "Reorganize scripts and tests"

# Commit 6: Documentation and config
Write-Host "`n[6/6] Committing docs and config..." -ForegroundColor Green
git add .gitignore
git add docs/
git add scripts/git-commits.ps1
git commit -m "Update documentation and gitignore"

Write-Host "`nAll commits complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Run: git log --oneline -10"
Write-Host "Run: git push"
