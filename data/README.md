# Data Directory

This folder contains data files for the Ohio Fraud Tracker.

## Structure

```
data/
├── ohio_checkbook/     # Ohio state spending CSVs
│   └── README.md       # Download instructions
├── usaspending/        # Federal spending (auto-downloaded via API)
└── sba/                # SBA loan data
```

## Database

The SQLite database (`ohio_fraud_tracker.db`) is stored in `api/data/` and is not tracked in git.

## Data Sources

| Source | Type | Method |
|--------|------|--------|
| USAspending.gov | Federal grants, loans, contracts | API (automated) |
| Ohio Checkbook | State expenses, contracts | CSV download (manual) |
| SBA | PPP/disaster loans | CSV download |

## Import Commands

```powershell
cd C:\Projects\ohio-fraud-tracker\api

# Federal data (automated)
python -m scripts.import_usaspending --resume

# Ohio state data (manual download first)
python -m scripts.import_ohio_checkbook --folder ..\data\ohio_checkbook\

# SBA PPP data
python -m scripts.import_sba_ppp --file ..\data\sba\ppp_loans.csv
```
