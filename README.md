# Ohio Fraud Tracker

A platform to aggregate and cross-reference public funding data to identify potential fraud in Ohio.

## Overview

The Ohio Fraud Tracker aggregates federal grants, loans, and contracts data for Ohio recipients, enabling cross-referencing with business registrations to detect potential fraud patterns such as:

- Awards to dissolved/inactive businesses
- Unusual concentration of awards to related entities
- PPP loans that may have been fraudulently obtained
- Discrepancies between reported and actual business information

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: SQLite (local) / Turso (production)
- **Frontend**: Astro + Tailwind CSS + Flowbite

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd ohio-fraud-tracker

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Initialize Database

```bash
cd api
python -c "from app.database import init_db; init_db()"
```

### 3. Import Data

See [Data Import Instructions](#data-import-instructions) below.

### 4. Run the Application

**Terminal 1 - API Server:**
```bash
cd api
..\venv\Scripts\activate
python -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm install
npm run dev
```

Access the application at: http://localhost:3000

---

## Data Import Instructions

### USAspending.gov (Federal Grants & Loans)

Import federal awards data from USAspending.gov API.

```bash
cd api
..\venv\Scripts\activate

# Full import (2015-2025, grants and loans) - takes several hours
python -m scripts.import_usaspending --start-year 2015 --end-year 2025

# Import specific year range
python -m scripts.import_usaspending --start-year 2020 --end-year 2024

# Import only grants
python -m scripts.import_usaspending --award-types grants

# Import only loans
python -m scripts.import_usaspending --award-types loans

# Resume interrupted import (skips years with existing data)
python -m scripts.import_usaspending --resume

# Clear and reimport
python -m scripts.import_usaspending --clear --start-year 2020
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--start-year` | 2015 | Starting fiscal year |
| `--end-year` | Current year | Ending fiscal year |
| `--award-types` | grants,loans | Comma-separated: grants, loans, contracts |
| `--resume` | false | Skip years with existing data |
| `--clear` | false | Delete existing USAspending data first |

**Expected Data:**
- ~50,000-100,000+ awards for Ohio (2015-2025)
- Total funding: $300+ billion

---

### SBA PPP Loans (COVID Relief)

Import Paycheck Protection Program loan data from SBA FOIA release.

#### Step 1: Download CSV Files

1. Go to: https://data.sba.gov/dataset/ppp-foia
2. Download the CSV file(s):
   - **Start with:** `public_150k_plus_240930.csv` (~1 GB) - Loans ≥ $150,000
   - **Optional:** `public_up_to_150k_*.csv` files (~2 GB each) - Smaller loans
3. Place files in: `api/data/sba_ppp/`

#### Step 2: Run Import

```bash
cd api
..\venv\Scripts\activate

# Test with a small sample first
python -m scripts.import_sba_ppp --file 150k_plus --limit 1000

# Import the 150k+ file (recommended first)
python -m scripts.import_sba_ppp --file 150k_plus

# Import all downloaded files
python -m scripts.import_sba_ppp

# Clear and reimport
python -m scripts.import_sba_ppp --clear --file 150k_plus
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--data-dir` | ./data/sba_ppp | Directory containing CSV files |
| `--file` | All files | Specific file to import (e.g., `150k_plus`, `small_1`) |
| `--limit` | None | Limit records for testing |
| `--clear` | false | Delete existing PPP data first |

**Expected Data:**
- ~250,000+ Ohio PPP loans
- Total: ~$25+ billion in Ohio PPP funding
- Includes forgiveness amounts and business details

---

### Ohio Secretary of State (Business Registry)

*Coming soon* - Cross-reference recipients with Ohio business registrations to verify:
- Business active/inactive status
- Formation dates
- Registered agent information

---

### Ohio Checkbook (State Spending)

Import Ohio state spending data from checkbook.ohio.gov.

#### Step 1: Download Data Files

1. Go to: https://checkbook.ohio.gov/
2. Click "Download" or use the data export feature
3. Download spending data files (CSV format)
4. Place files in: `data/ohio_checkbook/`

#### Step 2: Run Import

```bash
cd api
..\venv\Scripts\activate

# Import all files in the folder
python -m scripts.import_ohio_checkbook --folder ../data/ohio_checkbook/

# Import a specific file
python -m scripts.import_ohio_checkbook --file ../data/ohio_checkbook/spending_2024.csv
```

**Expected Data:**
- ~8+ million spending records
- Total: $45+ billion in state spending
- Includes vendor payments, contracts, grants

---

## Project Structure

```
ohio-fraud-tracker/
├── api/                        # FastAPI backend
│   ├── app/
│   │   ├── main.py            # FastAPI app entry point
│   │   ├── database.py        # Database connection
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── schemas.py         # Pydantic schemas
│   │   └── routers/           # API endpoints
│   │       ├── awards.py
│   │       ├── recipients.py
│   │       └── stats.py
│   ├── scripts/               # Import scripts
│   │   ├── import_usaspending.py
│   │   └── import_sba_ppp.py
│   └── data/                  # Local data files
│       └── sba_ppp/           # PPP CSV files go here
├── frontend/                  # Astro frontend
│   ├── src/
│   │   ├── layouts/
│   │   ├── pages/
│   │   ├── lib/api.ts        # API client
│   │   └── styles/
│   └── package.json
├── src/                       # Shared data source clients
│   └── data_sources/
│       └── usaspending.py
├── requirements.txt
└── README.md
```

## Database Schema

### Core Tables

- **recipients** - Businesses/organizations receiving awards
- **awards** - Individual grants, loans, contracts
- **agencies** - Federal agencies (HHS, DOT, SBA, etc.)
- **sub_agencies** - Agency subdivisions

### Key Fields

**Awards:**
- `source` - Data source (usaspending, sba_ppp)
- `source_award_id` - Unique ID from source system
- `award_type` - grant, loan, contract, etc.
- `amount` - Dollar amount
- `award_date` - Date of award

**Recipients:**
- `name` / `name_normalized` - Business name
- `business_status` - active, inactive, unknown
- `uei` / `ein` - Federal identifiers
- `ohio_entity_number` - Ohio SOS entity number

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Dashboard statistics |
| `GET /api/awards` | List/search awards |
| `GET /api/grants` | List grants only |
| `GET /api/loans` | List loans only |
| `GET /api/recipients` | List/search recipients |
| `GET /api/recipients/{id}` | Recipient details |
| `GET /api/recipients/{id}/awards` | Awards for recipient |
| `GET /api/recipients/flagged` | Flagged recipients |

## Fraud Detection Features

### Current
- Cross-reference recipient business status
- Identify inactive businesses receiving awards
- Track award concentrations by recipient

### Planned
- Ohio SOS business registry integration
- Address clustering detection
- Temporal pattern analysis
- PPP forgiveness anomaly detection

## Deployment (Vercel + Turso)

This project deploys as a monorepo on Vercel with Turso as the database.

### 1. Set Up Turso Database

```bash
# Install Turso CLI
curl -sSfL https://get.tur.so/install.sh | bash

# Login
turso auth login

# Create database
turso db create ohio-fraud-tracker

# Get connection URL
turso db show ohio-fraud-tracker --url

# Create auth token
turso db tokens create ohio-fraud-tracker
```

### 2. Deploy to Vercel

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy (from project root)
vercel

# Set environment variables
vercel env add TURSO_DATABASE_URL
vercel env add TURSO_AUTH_TOKEN

# Deploy to production
vercel --prod
```

### 3. Vercel Environment Variables

Set these in your Vercel project settings:

| Variable | Value |
|----------|-------|
| `TURSO_DATABASE_URL` | `libsql://ohio-fraud-tracker-xxx.turso.io` |
| `TURSO_AUTH_TOKEN` | Your token from `turso db tokens create` |

### Architecture

```
┌─────────────────────────────────────────┐
│              Vercel                      │
│  ┌─────────────┐  ┌─────────────────┐   │
│  │  Frontend   │  │  API (FastAPI)  │   │
│  │  (Astro)    │  │  (Serverless)   │   │
│  └─────────────┘  └────────┬────────┘   │
└────────────────────────────┼────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │     Turso       │
                    │   (Database)    │
                    └─────────────────┘
```

### Cost

| Component | Free Tier |
|-----------|----------|
| Vercel (Frontend + API) | Hobby plan - free |
| Turso (Database) | 9 GB storage, 1B reads/month |
| **Total** | **$0/month** |

---

## Environment Variables

Create a `.env` file in the `api/` directory:

```env
# Database (optional - defaults to local SQLite)
TURSO_DATABASE_URL=libsql://your-db.turso.io
TURSO_AUTH_TOKEN=your-token

# Debug
SQL_ECHO=false
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License
