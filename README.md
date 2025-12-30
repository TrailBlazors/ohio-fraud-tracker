# Ohio Fraud Tracker

A platform to aggregate and cross-reference public funding data to identify potential fraud in Ohio.

## Data Sources

### Federal
- **USAspending.gov** - Federal grants, contracts, loans to Ohio recipients
- **SBA PPP/EIDL** - Pandemic relief loan data
- **SBIR/STTR** - Small business innovation research awards

### State (Ohio)
- **Ohio Checkbook** - State spending transparency
- **Secretary of State** - Business registrations
- **Ohio Auditor** - Fraud reports and audit findings

## Project Structure

```
ohio-fraud-tracker/
├── src/
│   ├── data_sources/       # API clients for each data source
│   │   ├── usaspending.py
│   │   ├── sba_ppp.py
│   │   ├── sbir.py
│   │   └── ohio_checkbook.py
│   ├── models/             # Database models
│   ├── services/           # Business logic
│   └── api/                # FastAPI endpoints
├── tests/
├── data/                   # Local data cache
├── requirements.txt
└── README.md
```

## Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

## Usage

```python
from src.data_sources.usaspending import USASpendingClient

client = USASpendingClient()

# Get all grants to Ohio
grants = client.get_awards_by_state("OH", award_types=["grants"])

# Get specific recipient
recipient_awards = client.get_awards_by_recipient("Some Company LLC", state="OH")
```
