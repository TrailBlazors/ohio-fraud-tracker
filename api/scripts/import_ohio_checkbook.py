"""
Ohio Checkbook Data Importer

Imports state spending data from Ohio Checkbook (checkbook.ohio.gov) CSV exports.

Data Structure (checkbook_transactions_YYYY_MM_Mon.csv):
- account, account_name
- department_id, department_description
- payment_date, payment_method, payment_reference_id
- payment_amount
- vendor_name, address1, address2, city, state, zip
- transaction_month

Key field for deduplication: payment_reference_id

Usage:
    python -m scripts.import_ohio_checkbook --folder ../data/ohio_checkbook/
    python -m scripts.import_ohio_checkbook --file ../data/ohio_checkbook/checkbook_transactions_2022_01_Jan.csv
"""

import sys
import csv
import argparse
import re
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, List, Set
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db_context, init_db
from app.models import Award, Recipient, Agency, normalize_name


# =============================================================================
# OHIO AGENCY MAPPING
# =============================================================================

OHIO_AGENCY_CODES = {
    "EDU": "Department of Education",
    "TAX": "Department of Taxation", 
    "JFS": "Department of Job and Family Services",
    "DOH": "Department of Health",
    "DMH": "Department of Mental Health and Addiction Services",
    "DOT": "Department of Transportation",
    "DPS": "Department of Public Safety",
    "DNR": "Department of Natural Resources",
    "DAS": "Department of Administrative Services",
    "AGR": "Department of Agriculture",
    "COM": "Department of Commerce",
    "DDD": "Department of Developmental Disabilities",
    "DHE": "Department of Higher Education",
    "DOI": "Department of Insurance",
    "MCD": "Department of Medicaid",
    "DRC": "Department of Rehabilitation and Correction",
    "DVS": "Department of Veterans Services",
    "DYS": "Department of Youth Services",
    "EPA": "Environmental Protection Agency",
    "BWC": "Bureau of Workers Compensation",
    "LOT": "Ohio Lottery Commission",
    "PUC": "Public Utilities Commission",
    "AGO": "Attorney General",
    "AOS": "Auditor of State",
    "SOS": "Secretary of State",
    "TOS": "Treasurer of State",
    "GOV": "Governor's Office",
    "OBM": "Office of Budget and Management",
    "DEV": "Development Services Agency",
    "CSR": "Casino Control Commission",
}


def get_or_create_ohio_agency(db: Session, dept_id: str, dept_name: str, agency_cache: Dict) -> Optional[int]:
    """Get or create Ohio agency with caching"""
    if not dept_id:
        return None
    
    cache_key = dept_id.upper()
    if cache_key in agency_cache:
        return agency_cache[cache_key]
    
    # Use the department_id as code
    code = dept_id.upper()
    name = dept_name or OHIO_AGENCY_CODES.get(code, f"Ohio {code}")
    
    agency = db.query(Agency).filter(Agency.code == code).first()
    if not agency:
        agency = Agency(code=code, name=name)
        db.add(agency)
        db.flush()
    
    agency_cache[cache_key] = agency.id
    return agency.id


def get_or_create_recipient(
    db: Session,
    name: str,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    recipient_cache: Dict,
    new_recipient_ids: Set
) -> int:
    """Get or create recipient with caching"""
    if not name or name.strip() == "":
        name = "Unknown Vendor"
    
    name = name.strip()[:255]
    normalized = normalize_name(name)
    city = (city or "").strip()[:100] if city else None
    
    # Cache key: normalized name + city
    cache_key = f"{normalized}|{city or ''}"
    if cache_key in recipient_cache:
        return recipient_cache[cache_key]
    
    # Try to find existing
    query = db.query(Recipient).filter(Recipient.name_normalized == normalized)
    if city:
        query = query.filter(Recipient.city == city)
    
    recipient = query.first()
    
    if not recipient:
        # Build full address
        full_address = None
        if address:
            full_address = address.strip()[:255]
        
        recipient = Recipient(
            name=name,
            name_normalized=normalized,
            address=full_address,
            city=city,
            state=(state or "OH").strip()[:2],
            zip_code=(zip_code or "").strip()[:10] if zip_code else None,
            business_status="unknown",
        )
        db.add(recipient)
        db.flush()
        new_recipient_ids.add(recipient.id)
    
    recipient_cache[cache_key] = recipient.id
    return recipient.id


def parse_amount(amount_str: str) -> float:
    """Parse amount string to float"""
    if not amount_str:
        return 0.0
    
    cleaned = re.sub(r'[$,()]', '', str(amount_str)).strip()
    if not cleaned or cleaned == '-':
        return 0.0
    
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date(date_str: str) -> Optional[date]:
    """Parse date string"""
    if not date_str:
        return None
    
    date_str = str(date_str).strip()
    
    # Handle "2022-01-18 00:00:00" format
    if ' ' in date_str:
        date_str = date_str.split(' ')[0]
    
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    
    return None


def extract_year_month(filename: str) -> tuple:
    """Extract year and month from filename for sorting"""
    # Pattern: checkbook_transactions_YYYY_MM_Mon.csv
    match = re.search(r'(\d{4})_(\d{2})_', filename)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (9999, 99)  # Sort unknown files last


def map_account_to_award_type(account_name: str) -> str:
    """Map Ohio account names to award types"""
    if not account_name:
        return "other"
    
    account_lower = account_name.lower()
    
    if 'grant' in account_lower:
        return "project_grant"
    elif 'loan' in account_lower or 'scholarship' in account_lower:
        return "direct_loan"
    elif 'subsidy' in account_lower or 'assistance' in account_lower:
        return "direct_payment"
    elif 'refund' in account_lower:
        return "direct_payment"
    elif 'contract' in account_lower:
        return "contract"
    elif 'salary' in account_lower or 'payroll' in account_lower:
        return "direct_payment"
    else:
        return "direct_payment"


def import_transaction_file(
    db: Session,
    filepath: Path,
    stats: Dict[str, int],
    existing_ids: Set[str],
    agency_cache: Dict,
    recipient_cache: Dict,
    new_recipient_ids: Set,
    new_award_ids: Set,
) -> None:
    """Import a single Ohio Checkbook transaction CSV file"""
    
    file_created = 0
    file_skipped = 0
    
    print(f"\n  Processing: {filepath.name}")
    
    try:
        # Count total rows first for progress
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            total_rows = sum(1 for _ in f) - 1  # Subtract header
        
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            batch = []
            batch_size = 5000
            
            for i, row in enumerate(reader):
                stats["processed"] += 1
                
                # Get payment reference ID for deduplication
                payment_ref = row.get("payment_reference_id", "").strip()
                if not payment_ref:
                    stats["skipped"] += 1
                    file_skipped += 1
                    continue
                
                source_id = f"ohio_{payment_ref}"
                
                # Check if already imported (in-memory check first)
                if source_id in existing_ids:
                    stats["skipped"] += 1
                    file_skipped += 1
                    continue
                
                # Parse amount
                amount = parse_amount(row.get("payment_amount", "0"))
                if amount <= 0:
                    stats["skipped"] += 1
                    file_skipped += 1
                    continue
                
                # Parse date
                payment_date = parse_date(row.get("payment_date", ""))
                
                # Get vendor info
                vendor_name = row.get("vendor_name", "Unknown").strip()
                address1 = row.get("address1", "").strip()
                address2 = row.get("address2", "").strip()
                full_address = f"{address1} {address2}".strip() if address1 else None
                city = row.get("city", "").strip()
                state = row.get("state", "OH").strip()
                zip_code = row.get("zip", "").strip()
                
                # Get agency
                dept_id = row.get("department_id", "").strip()
                dept_name = row.get("department_description", "").strip()
                agency_id = get_or_create_ohio_agency(db, dept_id, dept_name, agency_cache)
                
                # Get recipient
                recipient_id = get_or_create_recipient(
                    db, vendor_name, full_address, city, state, zip_code,
                    recipient_cache, new_recipient_ids
                )
                
                # Determine award type
                account_name = row.get("account_name", "")
                award_type = map_account_to_award_type(account_name)
                
                # Build description
                description = f"{account_name}" if account_name else ""
                payment_method = row.get("payment_method", "")
                if payment_method:
                    description = f"{description} ({payment_method})" if description else payment_method
                
                # Create award
                award = Award(
                    source="ohio_checkbook",
                    source_award_id=source_id,
                    recipient_id=recipient_id,
                    agency_id=agency_id,
                    award_type=award_type,
                    amount=amount,
                    award_date=payment_date,
                    description=description[:500] if description else None,
                    pop_city=city if city else None,
                    pop_state="OH",
                    pop_zip=zip_code if zip_code else None,
                    last_modified=datetime.utcnow(),
                )
                batch.append(award)
                existing_ids.add(source_id)
                
                stats["created"] += 1
                file_created += 1
                
                # Batch insert
                if len(batch) >= batch_size:
                    db.bulk_save_objects(batch)
                    db.commit()
                    
                    # Progress update
                    pct = (i + 1) / total_rows * 100
                    print(f"    {i+1:,}/{total_rows:,} ({pct:.0f}%) - Created: {file_created:,}")
                    batch = []
            
            # Final batch
            if batch:
                db.bulk_save_objects(batch)
                db.commit()
        
        print(f"    ✓ Done: {file_created:,} created, {file_skipped:,} skipped")
        
    except Exception as e:
        print(f"    ✗ Error: {e}")
        db.rollback()
        stats["errors"] += 1


def main():
    parser = argparse.ArgumentParser(description="Import Ohio Checkbook CSV data")
    parser.add_argument("--file", type=str, help="Single CSV file to import")
    parser.add_argument("--folder", type=str, help="Folder containing CSV files to import")
    parser.add_argument("--skip-correlation", action="store_true", help="Skip post-import correlation")
    
    args = parser.parse_args()
    
    if not args.file and not args.folder:
        print("Error: Must specify --file or --folder")
        print("\nUsage:")
        print("  python -m scripts.import_ohio_checkbook --folder ../data/ohio_checkbook/")
        print("  python -m scripts.import_ohio_checkbook --file ../data/ohio_checkbook/file.csv")
        sys.exit(1)
    
    print("=" * 70)
    print("Ohio Checkbook Import")
    print("=" * 70)
    
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
            # Get all CSV files
            csv_files = list(folder.glob("*.csv"))
            # Sort by year/month extracted from filename
            csv_files.sort(key=lambda f: extract_year_month(f.name))
            files_to_import.extend(csv_files)
        else:
            print(f"Error: Folder not found: {args.folder}")
            sys.exit(1)
    
    if not files_to_import:
        print("No CSV files found to import")
        sys.exit(1)
    
    print(f"\nFound {len(files_to_import)} CSV files to import:")
    for f in files_to_import[:5]:
        print(f"  - {f.name}")
    if len(files_to_import) > 5:
        print(f"  ... and {len(files_to_import) - 5} more")
    
    stats = {
        "processed": 0,
        "created": 0,
        "skipped": 0,
        "errors": 0,
    }
    
    new_recipient_ids: Set[int] = set()
    new_award_ids: Set[int] = set()
    
    with get_db_context() as db:
        # Load existing Ohio Checkbook source IDs for fast duplicate checking
        print("\nLoading existing records for duplicate detection...")
        existing_ids = set(
            row[0] for row in db.query(Award.source_award_id).filter(
                Award.source == "ohio_checkbook"
            ).all()
        )
        print(f"  Found {len(existing_ids):,} existing Ohio Checkbook records")
        
        # Caches for agencies and recipients
        agency_cache: Dict[str, int] = {}
        recipient_cache: Dict[str, int] = {}
        
        print("\n" + "-" * 70)
        print("IMPORTING FILES")
        print("-" * 70)
        
        for i, filepath in enumerate(files_to_import):
            print(f"\n[{i+1}/{len(files_to_import)}]", end="")
            import_transaction_file(
                db, filepath, stats, existing_ids,
                agency_cache, recipient_cache,
                new_recipient_ids, new_award_ids
            )
        
        # Final summary
        print("\n" + "=" * 70)
        print("IMPORT COMPLETE")
        print("=" * 70)
        print(f"Records processed:  {stats['processed']:,}")
        print(f"Records created:    {stats['created']:,}")
        print(f"Records skipped:    {stats['skipped']:,} (duplicates/invalid)")
        print(f"Errors:             {stats['errors']}")
        print(f"New recipients:     {len(new_recipient_ids):,}")
        
        # Database totals
        total_ohio = db.query(func.count(Award.id)).filter(
            Award.source == "ohio_checkbook"
        ).scalar() or 0
        total_all = db.query(func.count(Award.id)).scalar() or 0
        
        print(f"\nOhio Checkbook in DB: {total_ohio:,}")
        print(f"Total awards in DB:   {total_all:,}")
        
        # Run correlation if not skipped
        if not args.skip_correlation and stats['created'] > 0:
            print("\n" + "=" * 70)
            print("POST-IMPORT CORRELATION")
            print("=" * 70)
            
            try:
                from src.correlation.post_import import run_post_import_analysis
                
                results = run_post_import_analysis(
                    db=db,
                    source="ohio_checkbook",
                    new_recipient_ids=list(new_recipient_ids),
                    new_award_ids=list(new_award_ids),
                )
                
                print(f"Correlation flags created: {results.get('flags_created', 0)}")
                if results.get('flags_by_type'):
                    print(f"By type: {results['flags_by_type']}")
                    
            except ImportError:
                print("Correlation module not available, skipping...")
            except Exception as e:
                print(f"Correlation failed: {e}")


if __name__ == "__main__":
    main()
