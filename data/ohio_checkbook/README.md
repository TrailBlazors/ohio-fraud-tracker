# Ohio Checkbook Data

This folder contains CSV transaction files from [Ohio Checkbook](https://checkbook.ohio.gov).

## Current Data

Files follow the naming convention: `checkbook_transactions_YYYY_MM_Mon.csv`

Available: 2022-01 through 2025 (monthly files)

## File Structure

Each CSV contains these columns:
- `account`, `account_name` - Budget account classification
- `department_id`, `department_description` - State agency
- `payment_date`, `payment_method` - When and how paid
- `payment_reference_id` - **Unique ID** (used for deduplication)
- `payment_amount` - Dollar amount
- `vendor_name`, `address1`, `address2`, `city`, `state`, `zip` - Recipient info
- `transaction_month` - Fiscal month

## Import Commands

```powershell
cd C:\Projects\ohio-fraud-tracker\api
.\.venv\Scripts\Activate.ps1

# Import ALL CSV files in this folder (recommended)
python -m scripts.import_ohio_checkbook --folder ..\data\ohio_checkbook\

# Import a single file
python -m scripts.import_ohio_checkbook --file ..\data\ohio_checkbook\checkbook_transactions_2022_01_Jan.csv

# Import without running correlation analysis
python -m scripts.import_ohio_checkbook --folder ..\data\ohio_checkbook\ --skip-correlation
```

## Deduplication

The importer uses `payment_reference_id` as the unique identifier. If you re-run the import:
- Existing records are skipped automatically
- Only new transactions are added
- Safe to run multiple times

## Data Volume

Typical monthly files:
- Small months: 50-100MB, ~500K-1M transactions
- Large months: 200-300MB, ~2-3M transactions

Total 2022-2025: ~1.5GB, ~15M+ transactions

## Download Instructions

If you need to download more data:

1. Go to https://checkbook.ohio.gov/Spending/Transactions
2. Select date range (one month at a time recommended)
3. Click "Export" → CSV
4. Save with naming convention: `checkbook_transactions_YYYY_MM_Mon.csv`
