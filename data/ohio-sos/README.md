# Ohio Secretary of State Business Filings

Download business registration data from the Ohio SOS website.

## Download Instructions

1. Go to: https://www.ohiosos.gov/businesses/business-reports/download-business-report/

2. Download the following reports (CSV format):
   - **Corporations** - For-profit and non-profit corporations
   - **LLCs** - Limited Liability Companies
   - **LLPs** - Limited Liability Partnerships
   - **Limited Partnerships**
   - **Professional Associations** (optional)

3. Place downloaded CSV files in this folder (`data/ohio-sos/`)

## Import Commands

```powershell
cd C:\Projects\ohio-fraud-tracker\api

# Import all CSV files in the folder
python -m scripts.import_ohio_sos --folder ../data/ohio-sos/

# Import a single file
python -m scripts.import_ohio_sos --file ../data/ohio-sos/corporations.csv

# Import and run matching
python -m scripts.import_ohio_sos --folder ../data/ohio-sos/ --match
```

## Matching Commands

```powershell
# Run matching against recipients
python -m scripts.match_ohio_sos

# Run with higher confidence threshold
python -m scripts.match_ohio_sos --min-confidence 0.9

# Run and update recipient business_status
python -m scripts.match_ohio_sos --update-recipients
```

## API Endpoints

After deployment, you can also use the API:

```bash
# Check SOS data status
curl https://your-site.com/api/stats/ohio-sos/status

# Run matching via API
curl -X POST "https://your-site.com/api/stats/ohio-sos/match?min_confidence=0.75&update_recipients=true"

# Update recipients only
curl -X POST "https://your-site.com/api/stats/ohio-sos/update-recipients?min_confidence=0.9"
```

## Data Fields

The import script handles various column naming conventions. Key fields:

| Field | Description |
|-------|-------------|
| entity_number | Unique SOS filing number |
| entity_name | Legal business name |
| status | Active, Cancelled, Dissolved, etc. |
| formation_date | Date business was formed |
| entity_type | LLC, Corporation, LLP, etc. |
| principal_city | Business address city |
| agent_name | Registered/statutory agent |

## Matching Logic

Recipients are matched to SOS businesses using:

1. **Exact name + city** (confidence: 1.0)
2. **Exact name only** (confidence: 0.9)
3. **Fuzzy match + city** (confidence: 0.75-0.85)

Only high-confidence matches (≥0.9) are used to update recipient status by default.

## Notes

- Re-running import updates existing records (upsert by entity_number)
- Keep CSV files for potential re-import after schema changes
- SOS data is typically updated quarterly by Ohio SOS
