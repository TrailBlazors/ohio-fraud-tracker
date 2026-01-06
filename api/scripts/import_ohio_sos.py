"""
Ohio Secretary of State Business Filings Importer

Imports business registration data from Ohio SOS bulk downloads.
Download from: https://www.ohiosos.gov/businesses/business-reports/download-business-report/

Available reports:
- Corporations (for-profit and non-profit)
- LLCs
- LLPs
- Limited Partnerships
- Professional Associations

Usage:
    python -m scripts.import_ohio_sos --file ../data/ohio-sos/corporations.csv
    python -m scripts.import_ohio_sos --folder ../data/ohio-sos/
    python -m scripts.import_ohio_sos --folder ../data/ohio-sos/ --match
"""

import sys
import csv
import argparse
import re
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, Set

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import get_db_context, init_db
from app.models import OhioSOSBusiness, Recipient, normalize_name


# =============================================================================
# STATUS MAPPING
# =============================================================================

STATUS_MAP = {
    "ACT": "active",
    "ACTIVE": "active",
    "CAN": "cancelled",
    "CANCELLED": "cancelled",
    "CANCEL": "cancelled",
    "DIS": "dissolved",
    "DISSOLVED": "dissolved",
    "DISSOLUTION": "dissolved",
    "INACTIVE": "inactive",
    "INA": "inactive",
    "EXP": "expired",
    "EXPIRED": "expired",
    "MER": "merged",
    "MERGED": "merged",
    "REV": "revoked",
    "REVOKED": "revoked",
    "SUS": "suspended",
    "SUSPENDED": "suspended",
    "CON": "converted",
    "CONVERTED": "converted",
}


def normalize_status(status_str: str) -> str:
    """Normalize status to standard values"""
    if not status_str:
        return "unknown"
    status_upper = status_str.strip().upper()
    return STATUS_MAP.get(status_upper, status_str.lower()[:30])


def parse_date(date_str: str) -> Optional[date]:
    """Parse date string from various formats"""
    if not date_str or date_str.strip() == "":
        return None

    date_str = str(date_str).strip()

    # Handle datetime with time component
    if ' ' in date_str:
        date_str = date_str.split(' ')[0]

    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%Y%m%d",
        "%d-%b-%Y",
        "%d-%b-%y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    return None


def normalize_sos_name(name: str) -> str:
    """Normalize business name for matching (more aggressive than recipient normalization)"""
    if not name:
        return ""

    # Uppercase first for consistency
    normalized = name.upper().strip()

    # Remove common suffixes
    suffixes = [
        " LLC", " L.L.C.", " L.L.C", " L L C",
        " INC", " INC.", " INCORPORATED",
        " CORP", " CORP.", " CORPORATION",
        " LTD", " LTD.", " LIMITED",
        " CO", " CO.", " COMPANY",
        " LLP", " L.L.P.", " L.L.P",
        " LP", " L.P.", " L.P",
        " PC", " P.C.", " P.C",
        " PLLC", " P.L.L.C.",
        " PA", " P.A.",
        " THE",
        " OF OHIO",
        " OHIO",
    ]

    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]

    # Remove punctuation
    normalized = re.sub(r'[.,\-\'\"&()]', ' ', normalized)

    # Collapse whitespace
    normalized = ' '.join(normalized.split())

    return normalized.strip().lower()


def detect_entity_type(row: Dict, filename: str) -> str:
    """Detect entity type from row data or filename"""
    # Check explicit type column
    entity_type = row.get("entity_type", "") or row.get("type", "") or row.get("business_type", "")
    if entity_type:
        return entity_type.strip()[:50]

    # Infer from filename
    filename_lower = filename.lower()
    if "llc" in filename_lower:
        return "LLC"
    elif "corp" in filename_lower:
        return "Corporation"
    elif "llp" in filename_lower:
        return "LLP"
    elif "lp" in filename_lower or "limited_partner" in filename_lower:
        return "Limited Partnership"
    elif "nonprofit" in filename_lower or "non-profit" in filename_lower:
        return "Nonprofit"
    elif "professional" in filename_lower:
        return "Professional Association"

    return "Unknown"


def find_column(row: Dict, *possible_names) -> str:
    """Find value from multiple possible column names"""
    for name in possible_names:
        # Try exact match
        if name in row:
            return row[name] or ""
        # Try case-insensitive
        for key in row.keys():
            if key.lower() == name.lower():
                return row[key] or ""
    return ""


def import_sos_file(
    db: Session,
    filepath: Path,
    stats: Dict[str, int],
    existing_entity_numbers: Set[str],
) -> None:
    """Import a single Ohio SOS CSV file"""

    file_created = 0
    file_updated = 0
    file_skipped = 0

    print(f"\n  Processing: {filepath.name}")

    try:
        # Count total rows first
        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            total_rows = sum(1 for _ in f) - 1

        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.DictReader(f)

            batch = []
            batch_size = 2000

            for i, row in enumerate(reader):
                stats["processed"] += 1

                # Find entity number (primary key)
                entity_number = find_column(
                    row,
                    "entity_number", "entity_no", "charter_number", "charter_no",
                    "filing_number", "file_number", "registration_number", "reg_number",
                    "business_number", "id", "entity_id"
                )

                if not entity_number or entity_number.strip() == "":
                    stats["skipped"] += 1
                    file_skipped += 1
                    continue

                entity_number = entity_number.strip()[:20]

                # Find entity name
                entity_name = find_column(
                    row,
                    "entity_name", "business_name", "name", "company_name",
                    "legal_name", "filing_name", "organization_name"
                )

                if not entity_name or entity_name.strip() == "":
                    stats["skipped"] += 1
                    file_skipped += 1
                    continue

                entity_name = entity_name.strip()[:255]

                # Check if exists
                is_update = entity_number in existing_entity_numbers

                # Parse other fields
                status = normalize_status(find_column(row, "status", "entity_status", "business_status", "state"))
                status_date = parse_date(find_column(row, "status_date", "status_change_date"))
                formation_date = parse_date(find_column(row, "formation_date", "date_formed", "date_of_formation", "incorporation_date", "filing_date", "original_date"))
                expiration_date = parse_date(find_column(row, "expiration_date", "exp_date", "dissolution_date"))

                entity_type = detect_entity_type(row, filepath.name)

                # Agent info
                agent_name = find_column(row, "agent_name", "registered_agent", "statutory_agent", "agent")[:255] if find_column(row, "agent_name", "registered_agent", "statutory_agent", "agent") else None
                agent_address = find_column(row, "agent_address", "agent_street", "agent_address1")[:255] if find_column(row, "agent_address", "agent_street", "agent_address1") else None
                agent_city = find_column(row, "agent_city")[:100] if find_column(row, "agent_city") else None
                agent_state = find_column(row, "agent_state")[:2] if find_column(row, "agent_state") else None
                agent_zip = find_column(row, "agent_zip", "agent_zipcode", "agent_postal")[:10] if find_column(row, "agent_zip", "agent_zipcode", "agent_postal") else None

                # Principal office
                principal_address = find_column(row, "principal_address", "principal_street", "business_address", "mailing_address", "address")[:255] if find_column(row, "principal_address", "principal_street", "business_address", "mailing_address", "address") else None
                principal_city = find_column(row, "principal_city", "business_city", "city")[:100] if find_column(row, "principal_city", "business_city", "city") else None
                principal_state = find_column(row, "principal_state", "business_state", "state")[:2] if find_column(row, "principal_state", "business_state") else "OH"
                principal_zip = find_column(row, "principal_zip", "business_zip", "zip", "zipcode")[:10] if find_column(row, "principal_zip", "business_zip", "zip", "zipcode") else None

                if is_update:
                    # Update existing record
                    db.query(OhioSOSBusiness).filter(
                        OhioSOSBusiness.entity_number == entity_number
                    ).update({
                        "entity_name": entity_name,
                        "entity_name_normalized": normalize_sos_name(entity_name),
                        "entity_type": entity_type,
                        "status": status,
                        "status_date": status_date,
                        "formation_date": formation_date,
                        "expiration_date": expiration_date,
                        "agent_name": agent_name,
                        "agent_address": agent_address,
                        "agent_city": agent_city,
                        "agent_state": agent_state,
                        "agent_zip": agent_zip,
                        "principal_address": principal_address,
                        "principal_city": principal_city,
                        "principal_state": principal_state,
                        "principal_zip": principal_zip,
                        "source_file": filepath.name,
                        "updated_at": datetime.utcnow(),
                    })
                    stats["updated"] += 1
                    file_updated += 1
                else:
                    # Create new record
                    sos_business = OhioSOSBusiness(
                        entity_number=entity_number,
                        entity_name=entity_name,
                        entity_name_normalized=normalize_sos_name(entity_name),
                        entity_type=entity_type,
                        status=status,
                        status_date=status_date,
                        formation_date=formation_date,
                        expiration_date=expiration_date,
                        agent_name=agent_name,
                        agent_address=agent_address,
                        agent_city=agent_city,
                        agent_state=agent_state,
                        agent_zip=agent_zip,
                        principal_address=principal_address,
                        principal_city=principal_city,
                        principal_state=principal_state,
                        principal_zip=principal_zip,
                        source_file=filepath.name,
                    )
                    batch.append(sos_business)
                    existing_entity_numbers.add(entity_number)
                    stats["created"] += 1
                    file_created += 1

                # Batch insert
                if len(batch) >= batch_size:
                    db.bulk_save_objects(batch)
                    db.commit()

                    pct = (i + 1) / total_rows * 100
                    print(f"    {i+1:,}/{total_rows:,} ({pct:.0f}%) - Created: {file_created:,}, Updated: {file_updated:,}")
                    batch = []

            # Final batch
            if batch:
                db.bulk_save_objects(batch)
                db.commit()

        print(f"    ✓ Done: {file_created:,} created, {file_updated:,} updated, {file_skipped:,} skipped")

    except Exception as e:
        print(f"    ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        stats["errors"] += 1


def run_matching(db: Session) -> Dict[str, int]:
    """Match Ohio SOS businesses to recipients"""
    from scripts.match_ohio_sos import match_all_recipients
    return match_all_recipients(db)


def main():
    parser = argparse.ArgumentParser(description="Import Ohio SOS business filings")
    parser.add_argument("--file", type=str, help="Single CSV file to import")
    parser.add_argument("--folder", type=str, help="Folder containing CSV files to import")
    parser.add_argument("--match", action="store_true", help="Run recipient matching after import")

    args = parser.parse_args()

    if not args.file and not args.folder:
        print("Error: Must specify --file or --folder")
        print("\nUsage:")
        print("  python -m scripts.import_ohio_sos --folder ../data/ohio-sos/")
        print("  python -m scripts.import_ohio_sos --file ../data/ohio-sos/corporations.csv")
        print("  python -m scripts.import_ohio_sos --folder ../data/ohio-sos/ --match")
        print("\nDownload data from:")
        print("  https://www.ohiosos.gov/businesses/business-reports/download-business-report/")
        sys.exit(1)

    print("=" * 70)
    print("Ohio Secretary of State Business Filings Import")
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
            csv_files = list(folder.glob("*.csv"))
            files_to_import.extend(csv_files)
        else:
            print(f"Error: Folder not found: {args.folder}")
            sys.exit(1)

    if not files_to_import:
        print("No CSV files found to import")
        sys.exit(1)

    print(f"\nFound {len(files_to_import)} CSV files to import:")
    for f in files_to_import:
        print(f"  - {f.name}")

    stats = {
        "processed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    with get_db_context() as db:
        # Create table if not exists
        print("\nEnsuring ohio_sos_businesses table exists...")
        try:
            from app.models import Base
            from app.database import engine
            OhioSOSBusiness.__table__.create(engine, checkfirst=True)
            print("  ✓ Table ready")
        except Exception as e:
            print(f"  Note: {e}")

        # Load existing entity numbers
        print("\nLoading existing records...")
        try:
            existing_entity_numbers = set(
                row[0] for row in db.query(OhioSOSBusiness.entity_number).all()
            )
            print(f"  Found {len(existing_entity_numbers):,} existing SOS records")
        except Exception:
            existing_entity_numbers = set()
            print("  No existing records (new table)")

        print("\n" + "-" * 70)
        print("IMPORTING FILES")
        print("-" * 70)

        for i, filepath in enumerate(files_to_import):
            print(f"\n[{i+1}/{len(files_to_import)}]", end="")
            import_sos_file(db, filepath, stats, existing_entity_numbers)

        # Summary
        print("\n" + "=" * 70)
        print("IMPORT COMPLETE")
        print("=" * 70)
        print(f"Records processed:  {stats['processed']:,}")
        print(f"Records created:    {stats['created']:,}")
        print(f"Records updated:    {stats['updated']:,}")
        print(f"Records skipped:    {stats['skipped']:,}")
        print(f"Errors:             {stats['errors']}")

        # Total in DB
        try:
            total_sos = db.query(func.count(OhioSOSBusiness.id)).scalar() or 0
            print(f"\nTotal SOS records in DB: {total_sos:,}")
        except Exception:
            pass

        # Run matching if requested
        if args.match and stats['created'] > 0:
            print("\n" + "=" * 70)
            print("RECIPIENT MATCHING")
            print("=" * 70)
            try:
                match_results = run_matching(db)
                print(f"Recipients matched: {match_results.get('matched', 0):,}")
                print(f"Match methods: {match_results.get('by_method', {})}")
            except Exception as e:
                print(f"Matching failed: {e}")
                print("Run separately with: python -m scripts.match_ohio_sos")


if __name__ == "__main__":
    main()
