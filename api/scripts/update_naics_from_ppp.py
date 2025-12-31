"""
Update Recipients with NAICS Codes from PPP Data

This script reads PPP CSV files and updates existing recipients with their
NAICS codes and business types WITHOUT reimporting or modifying award data.

This preserves data integrity while adding industry classification.

Usage:
    python -m scripts.update_naics_from_ppp

Options:
    --data-dir      Directory containing PPP CSV files (default: ./data/sba_ppp)
    --dry-run       Show what would be updated without making changes
    --limit         Limit number of files to process (for testing)
"""

import sys
import argparse
import csv
from pathlib import Path
from typing import Dict, Set
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func
from app.database import get_db_context, init_db
from app.models import Recipient, normalize_name


def discover_csv_files(data_dir: Path) -> list:
    """Discover all PPP CSV files in the data directory"""
    csv_files = []
    
    for f in data_dir.glob("*.csv"):
        name_lower = f.name.lower()
        if 'ppp' in name_lower or 'public' in name_lower:
            csv_files.append(f)
    
    if not csv_files:
        csv_files = list(data_dir.glob("*.csv"))
    
    # Sort: 150k_plus first, then numbered files
    def sort_key(path):
        name = path.name.lower()
        if '150k_plus' in name:
            return (0, name)
        elif 'up_to_150k' in name:
            import re
            match = re.search(r'_(\d+)_', name)
            num = int(match.group(1)) if match else 99
            return (1, num)
        return (2, name)
    
    csv_files.sort(key=sort_key)
    return csv_files


def build_recipient_lookup(db) -> Dict[str, int]:
    """Build lookup of (normalized_name, city) -> recipient_id"""
    print("Building recipient lookup table...")
    
    lookup = {}
    
    # Query all recipients
    recipients = db.query(
        Recipient.id,
        Recipient.name_normalized,
        Recipient.city
    ).all()
    
    for r in recipients:
        key = f"{r.name_normalized}|{r.city or ''}"
        lookup[key] = r.id
    
    print(f"  Loaded {len(lookup):,} recipients into lookup")
    return lookup


def extract_naics_from_csv(file_path: Path, recipient_lookup: Dict[str, int]) -> Dict[int, Dict]:
    """
    Extract NAICS codes from a PPP CSV file.
    Returns: {recipient_id: {"naics_code": str, "business_type": str}}
    """
    updates = {}
    row_count = 0
    ohio_count = 0
    matched_count = 0
    
    print(f"\n  Processing: {file_path.name}")
    
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            row_count += 1
            
            if row_count % 100000 == 0:
                print(f"    Scanned {row_count:,} rows, matched {matched_count:,} Ohio recipients...")
            
            # Filter for Ohio
            state = row.get("BorrowerState", "").strip().upper()
            if state != "OH":
                continue
            
            ohio_count += 1
            
            # Get NAICS and business type
            naics_code = row.get("NAICSCode", "").strip() or None
            business_type = row.get("BusinessType", "").strip() or None
            
            # Skip if no NAICS code
            if not naics_code:
                continue
            
            # Match to recipient
            name = row.get("BorrowerName", "")
            if not name:
                continue
                
            normalized = normalize_name(name)
            city = row.get("BorrowerCity", "").strip() or None
            
            key = f"{normalized}|{city or ''}"
            
            if key in recipient_lookup:
                recipient_id = recipient_lookup[key]
                
                # Only store if we don't already have data for this recipient
                # or if this entry has more complete data
                if recipient_id not in updates:
                    updates[recipient_id] = {
                        "naics_code": naics_code,
                        "business_type": business_type
                    }
                    matched_count += 1
                elif updates[recipient_id]["naics_code"] is None and naics_code:
                    updates[recipient_id]["naics_code"] = naics_code
                    if business_type:
                        updates[recipient_id]["business_type"] = business_type
    
    print(f"    Scanned {row_count:,} total rows")
    print(f"    Found {ohio_count:,} Ohio records")
    print(f"    Matched {matched_count:,} recipients with NAICS codes")
    
    return updates


def main():
    parser = argparse.ArgumentParser(
        description="Update recipients with NAICS codes from PPP data"
    )
    parser.add_argument("--data-dir", type=str, default="./data/sba_ppp",
                       help="Directory containing PPP CSV files")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be updated without making changes")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of CSV files to process")
    
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    
    print("=" * 60)
    print("Update Recipients with NAICS Codes")
    print("=" * 60)
    print(f"Data directory: {data_dir.absolute()}")
    print(f"Dry run: {args.dry_run}")
    
    if not data_dir.exists():
        print(f"\n✗ Data directory not found: {data_dir}")
        sys.exit(1)
    
    # Discover CSV files
    csv_files = discover_csv_files(data_dir)
    
    if args.limit:
        csv_files = csv_files[:args.limit]
    
    if not csv_files:
        print(f"\n✗ No CSV files found in {data_dir}")
        sys.exit(1)
    
    print(f"\nFound {len(csv_files)} CSV file(s) to process")
    
    init_db()
    
    with get_db_context() as db:
        # Check current state
        total_recipients = db.query(func.count(Recipient.id)).scalar()
        with_naics = db.query(func.count(Recipient.id)).filter(
            Recipient.naics_code.isnot(None),
            Recipient.naics_code != ""
        ).scalar()
        
        print(f"\nCurrent state:")
        print(f"  Total recipients: {total_recipients:,}")
        print(f"  With NAICS codes: {with_naics:,} ({100*with_naics/total_recipients:.1f}%)")
        print(f"  Missing NAICS: {total_recipients - with_naics:,}")
        
        # Build lookup
        recipient_lookup = build_recipient_lookup(db)
        
        # Collect all updates from all CSV files
        all_updates = {}
        
        start_time = time.time()
        
        for csv_file in csv_files:
            file_updates = extract_naics_from_csv(csv_file, recipient_lookup)
            
            # Merge updates (don't overwrite existing)
            for recipient_id, data in file_updates.items():
                if recipient_id not in all_updates:
                    all_updates[recipient_id] = data
                else:
                    # Fill in missing data
                    if all_updates[recipient_id]["naics_code"] is None and data["naics_code"]:
                        all_updates[recipient_id]["naics_code"] = data["naics_code"]
                    if all_updates[recipient_id]["business_type"] is None and data["business_type"]:
                        all_updates[recipient_id]["business_type"] = data["business_type"]
        
        print(f"\n{'='*60}")
        print(f"NAICS Data Collected")
        print(f"{'='*60}")
        print(f"Total recipients to update: {len(all_updates):,}")
        
        if args.dry_run:
            print("\n[DRY RUN] No changes made.")
            print("\nSample updates (first 10):")
            for i, (rid, data) in enumerate(list(all_updates.items())[:10]):
                recipient = db.query(Recipient.name, Recipient.city).filter(
                    Recipient.id == rid
                ).first()
                print(f"  {recipient.name} ({recipient.city})")
                print(f"    NAICS: {data['naics_code']} | Type: {data['business_type']}")
        else:
            # Apply updates in batches
            print("\nApplying updates...")
            
            batch_size = 1000
            updated_count = 0
            
            recipient_ids = list(all_updates.keys())
            
            for i in range(0, len(recipient_ids), batch_size):
                batch_ids = recipient_ids[i:i + batch_size]
                
                for recipient_id in batch_ids:
                    data = all_updates[recipient_id]
                    
                    # Only update if recipient doesn't already have NAICS
                    db.query(Recipient).filter(
                        Recipient.id == recipient_id,
                        (Recipient.naics_code.is_(None)) | (Recipient.naics_code == "")
                    ).update({
                        Recipient.naics_code: data["naics_code"],
                        Recipient.business_type: data["business_type"]
                    }, synchronize_session=False)
                    
                    updated_count += 1
                
                db.commit()
                
                if (i + batch_size) % 10000 == 0 or i + batch_size >= len(recipient_ids):
                    print(f"  Processed {min(i + batch_size, len(recipient_ids)):,} / {len(recipient_ids):,}")
            
            elapsed = time.time() - start_time
            
            # Final stats
            final_with_naics = db.query(func.count(Recipient.id)).filter(
                Recipient.naics_code.isnot(None),
                Recipient.naics_code != ""
            ).scalar()
            
            print(f"\n{'='*60}")
            print("UPDATE COMPLETE")
            print(f"{'='*60}")
            print(f"Time elapsed: {elapsed:.1f} seconds")
            print(f"Recipients processed: {len(all_updates):,}")
            print(f"\nFinal state:")
            print(f"  Total recipients: {total_recipients:,}")
            print(f"  With NAICS codes: {final_with_naics:,} ({100*final_with_naics/total_recipients:.1f}%)")
            print(f"  Newly updated: {final_with_naics - with_naics:,}")


if __name__ == "__main__":
    main()
