"""
Ohio Checkbook Data Importer

Imports state spending data from Ohio Checkbook (checkbook.ohio.gov) CSV exports.

Since Ohio Checkbook doesn't have a public API, this script processes
CSV files that users download manually from the website.

Data Sources:
- State Expenses: checkbook.ohio.gov/State/
- State Contracts: checkbook.ohio.gov/State/Expanded/StateContracts.aspx
- State Salaries: checkbook.ohio.gov/Salaries/State.aspx

How to Download Data:
1. Go to checkbook.ohio.gov/State/
2. Select filters (fiscal year, agency, etc.) or view all
3. Click "Download CSV" button
4. Save to data/ohio_checkbook/ folder

CSV Column Mappings (may vary by export type):
- State Expenses: Agency, Fund, Program, Expense Type, Amount, Date, Vendor
- State Contracts: Vendor Name, Contract Amount, Agency, Start Date, End Date

Usage:
    python -m scripts.import_ohio_checkbook --file data/ohio_checkbook/state_expenses_2024.csv
    python -m scripts.import_ohio_checkbook --folder data/ohio_checkbook/
"""

import sys
import csv
import argparse
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, List, Any
import re

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db_context, init_db
from app.models import Award, Recipient, Agency, normalize_name


# =============================================================================
# COLUMN MAPPINGS
# =============================================================================

# Different Ohio Checkbook exports have different columns
# These mappings handle common variations

EXPENSE_COLUMN_MAPPINGS = {
    # Vendor/Payee columns
    "vendor": ["Vendor", "Payee", "Vendor Name", "Payee Name", "VENDOR", "PAYEE"],
    "vendor_city": ["Vendor City", "City", "VENDOR CITY"],
    "vendor_state": ["Vendor State", "State", "VENDOR STATE"],
    
    # Amount columns  
    "amount": ["Amount", "Total", "Payment Amount", "AMOUNT", "Total Amount", "Expense Amount"],
    
    # Date columns
    "date": ["Date", "Payment Date", "Transaction Date", "Check Date", "DATE"],
    "fiscal_year": ["Fiscal Year", "FY", "Year", "FISCAL YEAR"],
    
    # Agency/Department columns
    "agency": ["Agency", "Department", "Agency Name", "AGENCY"],
    "sub_agency": ["Sub-Agency", "Division", "Program", "SUB-AGENCY"],
    
    # Category columns
    "expense_type": ["Expense Type", "Object", "Category", "EXPENSE TYPE"],
    "fund": ["Fund", "Fund Name", "FUND"],
    
    # Description
    "description": ["Description", "Memo", "Purpose", "DESCRIPTION"],
}

CONTRACT_COLUMN_MAPPINGS = {
    "vendor": ["Vendor Name", "Vendor", "Contractor", "VENDOR NAME"],
    "amount": ["Contract Amount", "Amount", "Total Amount", "CONTRACT AMOUNT"],
    "agency": ["Agency", "Awarding Agency", "AGENCY"],
    "start_date": ["Start Date", "Effective Date", "Begin Date", "START DATE"],
    "end_date": ["End Date", "Expiration Date", "END DATE"],
    "contract_number": ["Contract Number", "Contract ID", "CONTRACT NUMBER"],
    "description": ["Description", "Contract Description", "Purpose", "DESCRIPTION"],
}


def find_column(row: Dict, possible_names: List[str]) -> Optional[str]:
    """Find a column value by trying multiple possible names"""
    for name in possible_names:
        if name in row and row[name]:
            return str(row[name]).strip()
        # Try case-insensitive
        for key in row.keys():
            if key.lower() == name.lower() and row[key]:
                return str(row[key]).strip()
    return None


def parse_amount(amount_str: Optional[str]) -> float:
    """Parse amount string to float, handling currency formatting"""
    if not amount_str:
        return 0.0
    
    # Remove currency symbols, commas, parentheses (for negatives)
    cleaned = re.sub(r'[$,()]', '', str(amount_str))
    cleaned = cleaned.strip()
    
    if not cleaned or cleaned == '-':
        return 0.0
    
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse various date formats"""
    if not date_str:
        return None
    
    date_str = str(date_str).strip()
    
    # Common formats
    formats = [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%m-%d-%Y",
        "%d-%b-%Y",
        "%B %d, %Y",
        "%m/%d/%y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    
    return None


def detect_file_type(headers: List[str]) -> str:
    """Detect if this is an expenses, contracts, or salary file"""
    headers_lower = [h.lower() for h in headers]
    
    if any('contract' in h for h in headers_lower):
        return "contracts"
    elif any('salary' in h or 'compensation' in h for h in headers_lower):
        return "salaries"
    else:
        return "expenses"


# =============================================================================
# OHIO AGENCY MAPPING
# =============================================================================

OHIO_AGENCY_CODES = {
    "Department of Education": "ODE",
    "Department of Health": "ODH", 
    "Department of Job and Family Services": "ODJFS",
    "Department of Transportation": "ODOT",
    "Department of Public Safety": "ODPS",
    "Department of Natural Resources": "ODNR",
    "Department of Administrative Services": "DAS",
    "Department of Agriculture": "ODA",
    "Department of Commerce": "COM",
    "Department of Developmental Disabilities": "DODD",
    "Department of Higher Education": "ODHE",
    "Department of Insurance": "DOI",
    "Department of Medicaid": "ODM",
    "Department of Mental Health and Addiction Services": "OMHAS",
    "Department of Rehabilitation and Correction": "ODRC",
    "Department of Taxation": "TAX",
    "Department of Veterans Services": "ODVS",
    "Department of Youth Services": "DYS",
    "Environmental Protection Agency": "OEPA",
    "Bureau of Workers Compensation": "BWC",
    "Ohio Lottery Commission": "LOT",
    "Public Utilities Commission": "PUCO",
    "Attorney General": "AGO",
    "Auditor of State": "AOS",
    "Secretary of State": "SOS",
    "Treasurer of State": "TOS",
}


def get_ohio_agency_code(name: str) -> str:
    """Get Ohio agency code from name"""
    if not name:
        return "UNK"
    
    # Check direct mapping
    for full_name, code in OHIO_AGENCY_CODES.items():
        if full_name.lower() in name.lower() or name.lower() in full_name.lower():
            return code
    
    # Generate code from name
    words = name.split()
    if len(words) >= 2:
        return ''.join(w[0].upper() for w in words[:3])
    return name[:5].upper()


# =============================================================================
# IMPORT FUNCTIONS
# =============================================================================

def get_or_create_ohio_agency(db: Session, name: str) -> Optional[int]:
    """Get or create Ohio agency"""
    if not name:
        return None
    
    code = get_ohio_agency_code(name)
    
    agency = db.query(Agency).filter(Agency.code == code).first()
    if agency:
        return agency.id
    
    agency = Agency(code=code, name=name)
    db.add(agency)
    db.flush()
    return agency.id


def get_or_create_ohio_recipient(
    db: Session, 
    name: str, 
    city: Optional[str] = None,
    state: str = "OH",
    new_ids: set = None
) -> int:
    """Get or create recipient from Ohio Checkbook data"""
    if not name or name.strip() == "":
        name = "Unknown Vendor"
    
    name = name.strip()
    normalized = normalize_name(name)
    
    # Try to find existing
    query = db.query(Recipient).filter(Recipient.name_normalized == normalized)
    if city:
        query = query.filter(Recipient.city == city)
    
    recipient = query.first()
    
    if recipient:
        return recipient.id
    
    recipient = Recipient(
        name=name,
        name_normalized=normalized,
        city=city,
        state=state or "OH",
        business_status="unknown",
    )
    db.add(recipient)
    db.flush()
    
    if new_ids is not None:
        new_ids.add(recipient.id)
    
    return recipient.id


def import_expenses_csv(
    db: Session, 
    filepath: Path, 
    stats: Dict[str, int],
    new_ids: Dict[str, set]
) -> bool:
    """Import Ohio Checkbook expenses CSV"""
    
    print(f"\nImporting expenses from: {filepath.name}")
    
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            batch_count = 0
            for row in reader:
                stats["processed"] += 1
                
                # Extract fields using flexible column mapping
                vendor = find_column(row, EXPENSE_COLUMN_MAPPINGS["vendor"])
                amount_str = find_column(row, EXPENSE_COLUMN_MAPPINGS["amount"])
                date_str = find_column(row, EXPENSE_COLUMN_MAPPINGS["date"])
                agency_name = find_column(row, EXPENSE_COLUMN_MAPPINGS["agency"])
                description = find_column(row, EXPENSE_COLUMN_MAPPINGS["description"])
                vendor_city = find_column(row, EXPENSE_COLUMN_MAPPINGS["vendor_city"])
                
                # Parse values
                amount = parse_amount(amount_str)
                award_date = parse_date(date_str)
                
                # Skip zero or negative amounts (refunds, etc.)
                if amount <= 0:
                    stats["skipped"] += 1
                    continue
                
                # Create unique source ID
                source_id = f"ohio_exp_{hash(f'{vendor}_{amount}_{date_str}_{agency_name}')}_{stats['processed']}"
                
                # Check for duplicate
                existing = db.query(Award).filter(
                    Award.source == "ohio_checkbook",
                    Award.source_award_id == source_id
                ).first()
                
                if existing:
                    stats["skipped"] += 1
                    continue
                
                # Get/create entities
                agency_id = get_or_create_ohio_agency(db, agency_name)
                recipient_id = get_or_create_ohio_recipient(
                    db, vendor, vendor_city, "OH", new_ids.get("recipients")
                )
                
                # Create award
                award = Award(
                    source="ohio_checkbook",
                    source_award_id=source_id,
                    recipient_id=recipient_id,
                    agency_id=agency_id,
                    award_type="direct_payment",
                    amount=amount,
                    award_date=award_date,
                    description=(description or "")[:500],
                    pop_state="OH",
                    last_modified=datetime.utcnow(),
                )
                db.add(award)
                
                if new_ids.get("awards") is not None:
                    db.flush()
                    new_ids["awards"].add(award.id)
                
                stats["created"] += 1
                batch_count += 1
                
                # Commit in batches
                if batch_count >= 1000:
                    db.commit()
                    print(f"  Processed {stats['processed']:,} rows, created {stats['created']:,}")
                    batch_count = 0
            
            db.commit()
            return True
            
    except Exception as e:
        print(f"  Error importing {filepath.name}: {e}")
        db.rollback()
        stats["errors"] += 1
        return False


def import_contracts_csv(
    db: Session, 
    filepath: Path, 
    stats: Dict[str, int],
    new_ids: Dict[str, set]
) -> bool:
    """Import Ohio Checkbook contracts CSV"""
    
    print(f"\nImporting contracts from: {filepath.name}")
    
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            batch_count = 0
            for row in reader:
                stats["processed"] += 1
                
                # Extract fields
                vendor = find_column(row, CONTRACT_COLUMN_MAPPINGS["vendor"])
                amount_str = find_column(row, CONTRACT_COLUMN_MAPPINGS["amount"])
                agency_name = find_column(row, CONTRACT_COLUMN_MAPPINGS["agency"])
                start_date_str = find_column(row, CONTRACT_COLUMN_MAPPINGS["start_date"])
                end_date_str = find_column(row, CONTRACT_COLUMN_MAPPINGS["end_date"])
                contract_num = find_column(row, CONTRACT_COLUMN_MAPPINGS["contract_number"])
                description = find_column(row, CONTRACT_COLUMN_MAPPINGS["description"])
                
                # Parse values
                amount = parse_amount(amount_str)
                start_date = parse_date(start_date_str)
                end_date = parse_date(end_date_str)
                
                if amount <= 0:
                    stats["skipped"] += 1
                    continue
                
                # Create unique source ID
                source_id = contract_num or f"ohio_con_{hash(f'{vendor}_{amount}_{start_date_str}')}_{stats['processed']}"
                
                # Check for duplicate
                existing = db.query(Award).filter(
                    Award.source == "ohio_checkbook",
                    Award.source_award_id == source_id
                ).first()
                
                if existing:
                    existing.amount = amount  # Update amount
                    stats["updated"] += 1
                    continue
                
                # Get/create entities
                agency_id = get_or_create_ohio_agency(db, agency_name)
                recipient_id = get_or_create_ohio_recipient(
                    db, vendor, None, "OH", new_ids.get("recipients")
                )
                
                # Create award
                award = Award(
                    source="ohio_checkbook",
                    source_award_id=source_id,
                    recipient_id=recipient_id,
                    agency_id=agency_id,
                    award_type="contract",
                    amount=amount,
                    award_date=start_date,
                    start_date=start_date,
                    end_date=end_date,
                    description=(description or "")[:500],
                    pop_state="OH",
                    last_modified=datetime.utcnow(),
                )
                db.add(award)
                
                if new_ids.get("awards") is not None:
                    db.flush()
                    new_ids["awards"].add(award.id)
                
                stats["created"] += 1
                batch_count += 1
                
                if batch_count >= 1000:
                    db.commit()
                    print(f"  Processed {stats['processed']:,} rows, created {stats['created']:,}")
                    batch_count = 0
            
            db.commit()
            return True
            
    except Exception as e:
        print(f"  Error importing {filepath.name}: {e}")
        db.rollback()
        stats["errors"] += 1
        return False


def import_csv_file(
    db: Session, 
    filepath: Path, 
    stats: Dict[str, int],
    new_ids: Dict[str, set]
) -> bool:
    """Import a single CSV file, auto-detecting type"""
    
    # Read headers to detect file type
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        headers = next(reader, [])
    
    file_type = detect_file_type(headers)
    print(f"  Detected file type: {file_type}")
    
    if file_type == "contracts":
        return import_contracts_csv(db, filepath, stats, new_ids)
    elif file_type == "salaries":
        print("  Skipping salary file (not relevant for fraud detection)")
        return True
    else:
        return import_expenses_csv(db, filepath, stats, new_ids)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Import Ohio Checkbook CSV data")
    parser.add_argument("--file", type=str, help="Single CSV file to import")
    parser.add_argument("--folder", type=str, help="Folder containing CSV files to import")
    parser.add_argument("--skip-correlation", action="store_true", help="Skip post-import correlation")
    
    args = parser.parse_args()
    
    if not args.file and not args.folder:
        print("Error: Must specify --file or --folder")
        print("\nHow to get data:")
        print("1. Go to checkbook.ohio.gov/State/")
        print("2. Apply filters (fiscal year, agency, etc.)")
        print("3. Click 'Download CSV'")
        print("4. Run: python -m scripts.import_ohio_checkbook --file your_file.csv")
        sys.exit(1)
    
    print("=" * 60)
    print("Ohio Checkbook Import")
    print("=" * 60)
    
    init_db()
    
    # Collect files to import
    files_to_import = []
    
    if args.file:
        fp = Path(args.file)
        if fp.exists():
            files_to_import.append(fp)
        else:
            print(f"Error: File not found: {args.file}")
            sys.exit(1)
    
    if args.folder:
        folder = Path(args.folder)
        if folder.exists():
            files_to_import.extend(folder.glob("*.csv"))
        else:
            print(f"Error: Folder not found: {args.folder}")
            sys.exit(1)
    
    if not files_to_import:
        print("No CSV files found to import")
        sys.exit(1)
    
    print(f"\nFiles to import: {len(files_to_import)}")
    for f in files_to_import:
        print(f"  - {f.name}")
    
    stats = {
        "processed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    
    new_ids = {
        "recipients": set(),
        "awards": set()
    }
    
    with get_db_context() as db:
        for filepath in files_to_import:
            import_csv_file(db, filepath, stats, new_ids)
        
        # Print summary
        print("\n" + "=" * 60)
        print("IMPORT COMPLETE")
        print("=" * 60)
        print(f"Records processed: {stats['processed']:,}")
        print(f"Records created: {stats['created']:,}")
        print(f"Records updated: {stats['updated']:,}")
        print(f"Records skipped: {stats['skipped']:,}")
        print(f"Errors: {stats['errors']}")
        
        # Database totals
        total_ohio = db.query(func.count(Award.id)).filter(
            Award.source == "ohio_checkbook"
        ).scalar() or 0
        total_all = db.query(func.count(Award.id)).scalar() or 0
        
        print(f"\nOhio Checkbook awards in database: {total_ohio:,}")
        print(f"Total awards in database: {total_all:,}")
        
        # Run correlation if not skipped
        if not args.skip_correlation and (new_ids["recipients"] or new_ids["awards"]):
            print("\n" + "=" * 60)
            print("POST-IMPORT CORRELATION")
            print("=" * 60)
            
            try:
                from src.correlation.post_import import run_post_import_analysis
                
                results = run_post_import_analysis(
                    db=db,
                    source="ohio_checkbook",
                    new_recipient_ids=list(new_ids["recipients"]),
                    new_award_ids=list(new_ids["awards"]),
                )
                
                print(f"Correlation flags created: {results['flags_created']}")
                if results.get('flags_by_type'):
                    print(f"By type: {results['flags_by_type']}")
                    
            except Exception as e:
                print(f"Correlation failed: {e}")


if __name__ == "__main__":
    main()
