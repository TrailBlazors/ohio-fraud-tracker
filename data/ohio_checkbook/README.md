# Ohio Checkbook Data

This folder holds CSV files downloaded from [Ohio Checkbook](https://checkbook.ohio.gov).

## How to Download Data

### State Expenses (Recommended First)

1. Go to https://checkbook.ohio.gov/State/
2. **Filter by Fiscal Year** (click the year dropdown)
   - Start with the current year, then go back as needed
3. Optional: Filter by Agency, Fund, or Expense Type
4. Click **"Download CSV"** button (top right of chart)
5. Save the file here with a descriptive name:
   - `state_expenses_FY2024.csv`
   - `state_expenses_FY2023.csv`

### State Contracts

1. Go to https://checkbook.ohio.gov/State/Expanded/StateContracts.aspx
2. Apply filters as desired
3. Click **"Download CSV"**
4. Save as: `state_contracts_FY2024.csv`

### Local Government (Optional)

1. Go to https://checkbook.ohio.gov/Local/
2. Select a specific county, city, or township
3. Download CSV
4. Save as: `local_[entity_name]_FY2024.csv`

## Import Commands

```powershell
cd C:\Projects\ohio-fraud-tracker\api

# Import a single file
python -m scripts.import_ohio_checkbook --file ..\data\ohio_checkbook\state_expenses_FY2024.csv

# Import all CSVs in this folder
python -m scripts.import_ohio_checkbook --folder ..\data\ohio_checkbook\
```

## Expected Columns

The importer auto-detects file types. Common columns include:

### State Expenses
- Vendor / Payee
- Amount
- Date / Payment Date
- Agency
- Fund
- Expense Type

### State Contracts  
- Vendor Name
- Contract Amount
- Agency
- Start Date / End Date
- Contract Number

## Tips

- **Start with one fiscal year** to test the import
- **Filter by large amounts** (e.g., >$100k) to focus on significant transactions
- The importer skips zero/negative amounts (refunds)
- Duplicate detection prevents re-importing the same transactions

## Data Freshness

Ohio Checkbook updates daily with transactions through the previous business day.
For best results, download fresh data periodically (weekly or monthly).
