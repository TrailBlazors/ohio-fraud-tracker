# OpenCorporates Integration Guide

## Overview

OpenCorporates is the world's largest open database of corporate registry data. We use their API to:
- Verify Ohio businesses exist in Secretary of State records
- Check if businesses were active when receiving awards
- Flag dissolved/cancelled businesses that received funding
- Cross-reference addresses and registered agents

## Step 1: Get a Free API Token

OpenCorporates provides **free API access** for public benefit projects (fraud detection qualifies).

1. Go to: https://opencorporates.com/api_accounts/new
2. Select "Open Data / Public Benefit" plan
3. Fill out the application:
   - Project name: "Ohio Government Fraud Detection"
   - Description: "Cross-referencing federal/state funding data with Ohio SOS business records to detect potential fraud"
   - License: Will be releasing under open license (if true)
4. Submit and wait for approval (usually 1-2 business days)

## Step 2: Configure Your Environment

Add your API token to `.env`:

```env
# OpenCorporates API Token
OPENCORPORATES_API_TOKEN=your_token_here
```

## Step 3: Test the Integration

```powershell
cd C:\Projects\ohio-fraud-tracker\api
.\.venv\Scripts\Activate.ps1

# Test the client
python -c "
from src.data_sources.opencorporates import OpenCorporatesClient
client = OpenCorporatesClient()
results = client.search_companies('Kroger', jurisdiction='us_oh')
print(f'Found {results.total_count} results')
if results.companies:
    c = results.companies[0]
    print(f'Top match: {c.name} ({c.current_status})')
"
```

## Step 4: Run Verification

### Manual Single Verification
```powershell
# Check queue status
python -m scripts.scheduled_jobs status

# Run correlation scan (no SOS verification)
python -m scripts.run_correlation

# Run with SOS verification (100 recipients)
python -m scripts.run_correlation --verify-sos --limit 100 --save
```

### Automatic Post-Import
When you import USAspending data, correlation runs automatically:

```powershell
# Import with SOS verification
python -m scripts.import_usaspending --resume --verify-sos

# Import without SOS verification
python -m scripts.import_usaspending --resume

# Skip correlation entirely
python -m scripts.import_usaspending --resume --skip-correlation
```

### Scheduled Jobs
Set up automated verification with Windows Task Scheduler:

```powershell
# Run as Administrator
.\scripts\setup_windows_tasks.ps1
```

This creates three tasks:
| Task | Schedule | What it does |
|------|----------|--------------|
| NightlyVerification | 2 AM daily | Verifies 100 high-priority recipients |
| WeeklyFullScan | 3 AM Sunday | Full duplicate/outlier analysis |
| HourlyQuickScan | Every hour | Scans newly imported data |

## API Rate Limits

| Plan | Daily Limit | Monthly Limit | Notes |
|------|-------------|---------------|-------|
| No token | 50 | 200 | Very limited |
| Free (public benefit) | ~500 | ~10,000 | Apply at opencorporates.com |
| Paid | Unlimited | Based on plan | Contact OpenCorporates |

Our system is configured to:
- Stay under 50 requests/minute
- Prioritize high-dollar recipients
- Skip already-verified recipients
- Retry failed requests with backoff

## What Gets Verified

The priority queue verifies recipients in this order:

1. **Critical**: High-dollar (>$1M) never verified
2. **High**: Multi-source funding or >$500k
3. **Medium**: Recently added, moderate amounts
4. **Low**: Never verified, smaller amounts
5. **Background**: Stale (>6 months since last check)

## Fraud Flags Generated

| Flag Type | Severity | Description |
|-----------|----------|-------------|
| `business_not_found` | HIGH | Business not in Ohio SOS records |
| `business_dissolved_before_award` | CRITICAL | Business dissolved before receiving funding |
| `business_not_formed_before_award` | CRITICAL | Business didn't exist when funding received |
| `address_mismatch_sos_vs_award` | MEDIUM | Address on award differs from SOS records |

## Viewing Results

### API Endpoints
```
GET /api/correlation/flags                    # List all flags
GET /api/correlation/flags/summary            # Summary stats
GET /api/correlation/recipient/{id}/verify    # Check specific recipient
```

### Database Query
```sql
SELECT * FROM fraud_flags 
WHERE severity IN ('critical', 'high') 
  AND is_resolved = 0
ORDER BY created_at DESC;
```

## Troubleshooting

### "Rate limit exceeded"
- Wait 24 hours for daily limit reset
- Reduce `--limit` parameter
- Apply for higher tier if needed

### "Invalid API token"
- Check `.env` file has correct token
- Verify token at https://opencorporates.com/api_accounts

### "Company not found"
- Not all Ohio businesses are in OpenCorporates
- Try searching manually at https://businesssearch.ohiosos.gov/
- Some sole proprietors aren't required to register

### "401 Unauthorized"
- Token may have expired
- Regenerate at https://opencorporates.com/api_accounts

## Data Flow

```
USAspending Import
       │
       ▼
┌─────────────────┐
│ Post-Import     │──────────────────────────┐
│ Correlation     │                          │
└────────┬────────┘                          │
         │                                   │
         ▼                                   ▼
┌─────────────────┐              ┌─────────────────┐
│ Quick Checks:   │              │ SOS Verification│
│ - Duplicates    │              │ (via OpenCorp)  │
│ - Outliers      │              │                 │
│ - Multi-source  │              └────────┬────────┘
└────────┬────────┘                       │
         │                                │
         └──────────┬─────────────────────┘
                    │
                    ▼
            ┌───────────────┐
            │  FraudFlags   │
            │   Database    │
            └───────────────┘
```

## Next Steps

1. Import your data: `python -m scripts.import_usaspending --resume`
2. Check verification queue: `python -m scripts.scheduled_jobs status`
3. Run initial verification: `python -m scripts.run_correlation --verify-sos --limit 100 --save`
4. Set up scheduled tasks: `.\scripts\setup_windows_tasks.ps1`
5. Monitor flags: Visit `/api/correlation/flags/summary`
