"""
SBA PPP Loan Import Script

Downloads and imports SBA Paycheck Protection Program (PPP) loan data for Ohio.
Data source: https://data.sba.gov/dataset/ppp-foia

The PPP FOIA data contains ~11.5 million loans nationwide. We filter for Ohio only.

Usage:
    # First, download the CSV files manually (they're large):
    # Go to: https://data.sba.gov/dataset/ppp-foia
    # Download all public_*.csv files
    # Place in: C:\\Projects\\ohio-fraud-tracker\\api\\data\\sba_ppp\\
    
    # Then run (will auto-discover all CSV files):
    python -m scripts.import_sba_ppp

Options:
    --data-dir      Directory containing CSV files (default: ./data/sba_ppp)
    --clear         Clear existing SBA PPP data before import
    --limit         Limit number of records to import (for testing)
    --file          Import specific file only (e.g., '150k_plus' or exact filename)
"""

import sys
import argparse
import csv
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set
import time

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db_context, init_db
from app.models import Award, Recipient, Agency, normalize_name


# =============================================================================
# CONSTANTS
# =============================================================================

# Friendly name aliases for --file argument
FILE_ALIASES = {
    "150k_plus": "public_150k_plus",
    "150k": "public_150k_plus",
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse date string from PPP data"""
    if not date_str or date_str.strip() == "":
        return None
    
    formats = ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    
    return None


def parse_amount(amount_str: Optional[str]) -> float:
    """Parse dollar amount from string"""
    if not amount_str or amount_str.strip() == "":
        return 0.0
    
    try:
        cleaned = amount_str.replace("$", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def get_or_create_sba_agency(db: Session) -> int:
    """Get or create the SBA agency record"""
    agency = db.query(Agency).filter(Agency.code == "SBA").first()
    
    if not agency:
        agency = Agency(code="SBA", name="Small Business Administration")
        db.add(agency)
        db.flush()
    
    return agency.id


def get_or_create_recipient(db: Session, row: Dict[str, Any], recipient_cache: Dict[str, int]) -> int:
    """Get or create recipient from PPP row data with caching"""
    
    name = row.get("BorrowerName") or "Unknown Business"
    normalized = normalize_name(name)
    city = row.get("BorrowerCity", "").strip() or None
    
    # Get NAICS code and business type from PPP data
    naics_code = row.get("NAICSCode", "").strip() or None
    business_type = row.get("BusinessType", "").strip() or None
    
    # Create cache key
    cache_key = f"{normalized}|{city or ''}"
    
    # Check cache first
    if cache_key in recipient_cache:
        # Update NAICS if we have it and recipient doesn't
        recipient_id = recipient_cache[cache_key]
        if naics_code:
            recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
            if recipient and not recipient.naics_code:
                recipient.naics_code = naics_code
                if business_type and not recipient.business_type:
                    recipient.business_type = business_type
        return recipient_id
    
    # Try to find existing recipient
    recipient = db.query(Recipient).filter(
        Recipient.name_normalized == normalized,
        Recipient.city == city
    ).first()
    
    if recipient:
        # Update NAICS if missing
        if naics_code and not recipient.naics_code:
            recipient.naics_code = naics_code
        if business_type and not recipient.business_type:
            recipient.business_type = business_type
        recipient_cache[cache_key] = recipient.id
        return recipient.id
    
    # Create new recipient with NAICS
    recipient = Recipient(
        name=name,
        name_normalized=normalized,
        naics_code=naics_code,
        business_type=business_type,
        address=row.get("BorrowerAddress", "").strip() or None,
        city=city,
        state=row.get("BorrowerState", "").strip() or "OH",
        zip_code=row.get("BorrowerZip", "").strip() or None,
        business_status="unknown",
    )
    db.add(recipient)
    db.flush()
    
    recipient_cache[cache_key] = recipient.id
    return recipient.id


def discover_csv_files(data_dir: Path) -> list:
    """Discover all PPP CSV files in the data directory"""
    csv_files = []
    
    # Find all CSV files that look like PPP data
    for f in data_dir.glob("*.csv"):
        # Match PPP file patterns
        name_lower = f.name.lower()
        if 'ppp' in name_lower or 'public' in name_lower:
            csv_files.append(f)
    
    # Also check for any CSV file if none matched
    if not csv_files:
        csv_files = list(data_dir.glob("*.csv"))
    
    # Sort files: 150k_plus first, then numbered files in order
    def sort_key(path):
        name = path.name.lower()
        if '150k_plus' in name:
            return (0, name)
        elif 'up_to_150k' in name:
            # Extract number from filename
            import re
            match = re.search(r'_(\d+)_', name)
            num = int(match.group(1)) if match else 99
            return (1, num)
        else:
            return (2, name)
    
    csv_files.sort(key=sort_key)
    return csv_files


def load_existing_loan_numbers(db: Session) -> Set[str]:
    """Load all existing PPP loan numbers to prevent duplicates"""
    print("  Loading existing loan numbers for deduplication...")
    
    existing = set()
    
    # Query all existing PPP source IDs
    results = db.query(Award.source_award_id).filter(
        Award.source == "sba_ppp"
    ).all()
    
    for (source_id,) in results:
        # Extract loan number from source_id (format: ppp_LOANNUMBER)
        if source_id and source_id.startswith("ppp_"):
            loan_num = source_id[4:]  # Remove 'ppp_' prefix
            existing.add(loan_num)
    
    print(f"  Found {len(existing):,} existing loan numbers")
    return existing


# =============================================================================
# IMPORT FUNCTION
# =============================================================================

def process_csv_file(
    db: Session,
    file_path: Path,
    agency_id: int,
    stats: Dict[str, int],
    existing_loans: Set[str],
    recipient_cache: Dict[str, int],
    limit: Optional[int] = None
) -> None:
    """Process a single PPP CSV file, importing Ohio records"""
    
    print(f"\n{'='*60}")
    print(f"Processing: {file_path.name}")
    print(f"{'='*60}")
    
    if not file_path.exists():
        print(f"  ✗ File not found: {file_path}")
        return
    
    file_size = file_path.stat().st_size
    print(f"  File size: {file_size / (1024*1024):.1f} MB")
    
    ohio_count = 0
    row_count = 0
    batch_count = 0
    file_created = 0
    file_skipped = 0
    
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            row_count += 1
            
            # Progress indicator every 100k rows
            if row_count % 100000 == 0:
                print(f"  Scanned {row_count:,} rows, found {ohio_count:,} Ohio records ({file_created:,} new, {file_skipped:,} existing)...")
            
            # Filter for Ohio only
            borrower_state = row.get("BorrowerState", "").strip().upper()
            if borrower_state != "OH":
                continue
            
            ohio_count += 1
            stats["processed"] += 1
            
            # Check limit
            if limit and stats["created"] >= limit:
                print(f"  Reached limit of {limit} records")
                break
            
            try:
                # Get loan number
                loan_number = row.get("LoanNumber", "").strip()
                if not loan_number:
                    stats["skipped"] += 1
                    continue
                
                # CRITICAL: Check if already imported (in-memory check for speed)
                if loan_number in existing_loans:
                    stats["skipped"] += 1
                    file_skipped += 1
                    continue
                
                # Mark as imported to prevent duplicates within this run
                existing_loans.add(loan_number)
                
                source_id = f"ppp_{loan_number}"
                
                # Get/create recipient (with caching)
                recipient_id = get_or_create_recipient(db, row, recipient_cache)
                
                # Parse data
                approval_date = parse_date(row.get("DateApproved"))
                forgiveness_date = parse_date(row.get("ForgivenessDate"))
                initial_amount = parse_amount(row.get("InitialApprovalAmount"))
                current_amount = parse_amount(row.get("CurrentApprovalAmount"))
                forgiveness_amount = parse_amount(row.get("ForgivenessAmount"))
                
                # Build description
                business_type = row.get("BusinessType", "").strip()
                lender = row.get("OriginatingLender", "").strip()
                loan_status = row.get("LoanStatus", "").strip()
                jobs = row.get("JobsReported", "").strip()
                
                desc_parts = [f"PPP Loan"]
                if business_type:
                    desc_parts.append(f"Type: {business_type}")
                if lender:
                    desc_parts.append(f"Lender: {lender}")
                if loan_status:
                    desc_parts.append(f"Status: {loan_status}")
                if jobs:
                    desc_parts.append(f"Jobs: {jobs}")
                if forgiveness_amount > 0:
                    desc_parts.append(f"Forgiven: ${forgiveness_amount:,.0f}")
                
                description = ". ".join(desc_parts)
                
                # Create award record
                award = Award(
                    source="sba_ppp",
                    source_award_id=source_id,
                    recipient_id=recipient_id,
                    agency_id=agency_id,
                    award_type="loan",
                    amount=current_amount or initial_amount,
                    award_date=approval_date.date() if approval_date else None,
                    start_date=approval_date.date() if approval_date else None,
                    end_date=forgiveness_date.date() if forgiveness_date else None,
                    description=description[:500],
                    pop_city=row.get("ProjectCity", "").strip() or None,
                    pop_state=row.get("ProjectState", "").strip() or None,
                    pop_zip=row.get("ProjectZip", "").strip() or None,
                    last_modified=datetime.now(timezone.utc),
                )
                db.add(award)
                stats["created"] += 1
                file_created += 1
                batch_count += 1
                
            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 10:
                    print(f"  Error on row {row_count}: {e}")
                continue
            
            # Commit every 1000 records
            if batch_count >= 1000:
                db.commit()
                batch_count = 0
    
    # Final commit
    db.commit()
    print(f"  ✓ Scanned {row_count:,} total rows")
    print(f"  ✓ Found {ohio_count:,} Ohio records")
    print(f"  ✓ Created {file_created:,} new loans")
    print(f"  ✓ Skipped {file_skipped:,} existing loans (duplicates)")


def clear_ppp_data(db: Session) -> None:
    """Remove all SBA PPP data"""
    print("\nClearing existing SBA PPP data...")
    
    count = db.query(Award).filter(Award.source == "sba_ppp").delete()
    db.commit()
    
    print(f"  Deleted {count:,} PPP loans")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Import SBA PPP loan data for Ohio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-discover and import ALL CSV files in the data directory:
  python -m scripts.import_sba_ppp
  
  # Import with a limit for testing:
  python -m scripts.import_sba_ppp --limit 1000
  
  # Import specific file only:
  python -m scripts.import_sba_ppp --file 150k_plus
  
  # Clear and reimport all:
  python -m scripts.import_sba_ppp --clear

Download CSV files from: https://data.sba.gov/dataset/ppp-foia
Place them in: ./data/sba_ppp/

The script will:
1. Auto-discover all CSV files in the data directory
2. Load existing loan numbers to prevent duplicates
3. Process files in order (150k+ first, then smaller chunks)
4. Skip any loans already in the database
        """
    )
    parser.add_argument("--data-dir", type=str, default="./data/sba_ppp", 
                       help="Directory containing CSV files")
    parser.add_argument("--clear", action="store_true", 
                       help="Clear existing PPP data before import")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit records to import (for testing)")
    parser.add_argument("--file", type=str, default=None,
                       help="Import specific file only (e.g., '150k_plus' or exact filename)")
    
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    
    print("=" * 60)
    print("SBA PPP Loan Import for Ohio")
    print("=" * 60)
    print(f"Data directory: {data_dir.absolute()}")
    print(f"Clear existing: {args.clear}")
    print(f"Limit: {args.limit or 'None'}")
    
    # Check if data directory exists
    if not data_dir.exists():
        print(f"\n⚠ Data directory not found. Creating: {data_dir}")
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nPlease download PPP CSV files from:")
        print("  https://data.sba.gov/dataset/ppp-foia")
        print(f"\nPlace them in: {data_dir.absolute()}")
        sys.exit(1)
    
    # Discover CSV files
    if args.file:
        # Handle specific file request
        filename = FILE_ALIASES.get(args.file, args.file)
        
        # Find matching file
        matching_files = []
        for f in data_dir.glob("*.csv"):
            if filename.lower() in f.name.lower():
                matching_files.append(f)
        
        if not matching_files:
            # Try exact match
            exact_path = data_dir / (filename if filename.endswith('.csv') else f"{filename}.csv")
            if exact_path.exists():
                matching_files = [exact_path]
        
        if not matching_files:
            print(f"\n✗ No matching file found for: {args.file}")
            print(f"\nFiles in {data_dir}:")
            for f in data_dir.glob("*.csv"):
                print(f"  - {f.name}")
            sys.exit(1)
        
        files_to_process = matching_files
    else:
        # Auto-discover all CSV files
        files_to_process = discover_csv_files(data_dir)
    
    if not files_to_process:
        print(f"\n✗ No CSV files found in {data_dir}")
        print("\nDownload from: https://data.sba.gov/dataset/ppp-foia")
        sys.exit(1)
    
    print(f"\nDiscovered {len(files_to_process)} CSV file(s):")
    for f in files_to_process:
        size_mb = f.stat().st_size / (1024*1024)
        print(f"  - {f.name} ({size_mb:.1f} MB)")
    
    # Initialize database
    init_db()
    
    with get_db_context() as db:
        # Clear if requested
        if args.clear:
            clear_ppp_data(db)
        
        # Get SBA agency ID
        agency_id = get_or_create_sba_agency(db)
        
        # Show current state
        current_count = db.query(func.count(Award.id)).filter(Award.source == "sba_ppp").scalar()
        print(f"\nCurrent PPP loans in database: {current_count:,}")
        
        # CRITICAL: Load existing loan numbers for deduplication
        existing_loans = load_existing_loan_numbers(db)
        
        # Recipient cache for performance
        recipient_cache: Dict[str, int] = {}
        
        # Track stats
        stats = {
            "processed": 0,
            "created": 0,
            "skipped": 0,
            "errors": 0,
        }
        
        start_time = time.time()
        
        # Process each CSV file
        for file_path in files_to_process:
            process_csv_file(
                db, 
                file_path, 
                agency_id, 
                stats, 
                existing_loans,
                recipient_cache,
                args.limit
            )
            
            if args.limit and stats["created"] >= args.limit:
                break
        
        elapsed = time.time() - start_time
        
        # Print summary
        print("\n" + "=" * 60)
        print("IMPORT COMPLETE")
        print("=" * 60)
        print(f"Time elapsed: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        print(f"Files processed: {len(files_to_process)}")
        print(f"Ohio records found: {stats['processed']:,}")
        print(f"Records created: {stats['created']:,}")
        print(f"Records skipped (duplicates): {stats['skipped']:,}")
        print(f"Errors: {stats['errors']:,}")
        
        # Print database totals
        total_ppp = db.query(func.count(Award.id)).filter(Award.source == "sba_ppp").scalar()
        total_amount = db.query(func.sum(Award.amount)).filter(Award.source == "sba_ppp").scalar() or 0
        
        print(f"\nPPP Loans in database:")
        print(f"  Total loans: {total_ppp:,}")
        print(f"  Total amount: ${total_amount:,.2f}")


if __name__ == "__main__":
    main()
