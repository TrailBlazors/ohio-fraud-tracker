# Ohio Fraud Tracker API

REST API for tracking government funding data in Ohio and detecting potential fraud.

## Quick Start

### Option 1: PowerShell (Recommended)
```powershell
cd C:\Projects\ohio-fraud-tracker\api

# First time setup
.\start.ps1 -Setup

# Start the API
.\start.ps1

# Check database status
.\start.ps1 -Status
```

### Option 2: Double-click
Just double-click `start.bat` to launch the API.

### Option 3: Command line
```powershell
cd C:\Projects\ohio-fraud-tracker\api
.\.venv\Scripts\Activate.ps1
python run.py
```

### Option 4: Dev commands
```powershell
python dev.py start      # Start API
python dev.py status     # Database status
python dev.py correlate  # Run fraud detection
python dev.py shell      # Interactive Python shell
```

## API Endpoints

Once running, visit:
- **API Docs**: http://127.0.0.1:8000/docs
- **Health Check**: http://127.0.0.1:8000/health

### Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats/summary` | Dashboard statistics |
| `GET /api/awards` | Search/filter awards |
| `GET /api/recipients` | Search recipients |
| `GET /api/recipients/{id}` | Recipient detail with awards |
| `GET /api/correlation/flags` | Fraud indicators |
| `GET /api/correlation/flags/summary` | Flag statistics |

## Data Import

### USAspending (Federal Data)
```powershell
# Import all Ohio grants and loans (2015-present)
python -m scripts.import_usaspending --resume

# Import specific years
python -m scripts.import_usaspending --start-year 2020 --end-year 2024
```

### Ohio Checkbook (State Data)
```powershell
# Download CSV from checkbook.ohio.gov/State/
# Then import:
python -m scripts.import_ohio_checkbook --file data/state_expenses.csv
```

## Fraud Detection

```powershell
# Run correlation analysis
python -m scripts.run_correlation --save

# Check status
python -m scripts.scheduled_jobs status
```

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```env
# Local SQLite (default)
DATABASE_URL=sqlite:///./data/ohio_fraud_tracker.db

# Or use Turso for production
TURSO_DATABASE_URL=libsql://your-db.turso.io
TURSO_AUTH_TOKEN=your-token

# API settings
API_HOST=127.0.0.1
API_PORT=8000
```

## Project Structure

```
api/
├── app/
│   ├── main.py          # FastAPI app
│   ├── models.py        # Database models
│   ├── database.py      # DB connection
│   ├── schemas.py       # Pydantic schemas
│   └── routers/         # API endpoints
├── scripts/
│   ├── import_usaspending.py
│   ├── import_ohio_checkbook.py
│   ├── run_correlation.py
│   └── scheduled_jobs.py
├── data/                # Local database
├── run.py               # Quick start script
├── dev.py               # Dev commands
├── start.ps1            # PowerShell launcher
└── start.bat            # Batch launcher
```
