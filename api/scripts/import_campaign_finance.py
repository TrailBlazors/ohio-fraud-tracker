"""
Import Ohio Campaign Finance data from Secretary of State.

Downloads contribution data from Ohio SOS FTP and imports it into the database,
then cross-references against recipients to flag political donors.

Data source: https://www6.ohiosos.gov/ords/
Alternative: https://www.publicaccountability.org/datasets/55/oh_contribs/

Data coverage: 1990-2022 (files updated annually)
"""

import sys
import os
import csv
import requests
from datetime import datetime, date
from io import StringIO, BytesIO
from zipfile import ZipFile
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, func
from sqlalchemy.orm import Session
from app.database import engine, SessionLocal
from app.models import (
    CampaignContribution, Politician, Recipient, FraudFlag,
    DataImport, Base, normalize_name
)

# Ohio SOS FTP base URL for campaign finance bulk downloads
OHIO_SOS_FTP_BASE = "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:DOWNLOAD"

# Accountability Project pre-cleaned data (alternative source)
ACCOUNTABILITY_PROJECT_URL = "https://publicaccountability.org/data/oh_contribs.csv.gz"

# Years to import (adjust based on needs - full range is 1990-2022)
DEFAULT_START_YEAR = 2015
DEFAULT_END_YEAR = 2022

# Committee types
COMMITTEE_TYPES = {
    "CAN": "Candidate",
    "PAC": "Political Action Committee",
    "PAR": "Party",
}


def normalize_contributor_name(first: str, middle: str, last: str, suffix: str = None) -> str:
    """Build normalized name from parts."""
    parts = [p.strip() for p in [first, middle, last] if p and p.strip()]
    name = " ".join(parts)
    if suffix and suffix.strip():
        name += f" {suffix.strip()}"
    return normalize_name(name)


def parse_date(date_str: str) -> date | None:
    """Parse various date formats to Python date."""
    if not date_str or date_str.strip() == "":
        return None

    date_str = date_str.strip()

    # Try common formats
    formats = [
        "%m/%d/%Y",  # 01/15/2020
        "%Y-%m-%d",  # 2020-01-15
        "%m-%d-%Y",  # 01-15-2020
        "%Y%m%d",    # 20200115
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    return None


def parse_amount(amount_str: str) -> float:
    """Parse amount string to float."""
    if not amount_str or amount_str.strip() == "":
        return 0.0

    # Remove currency symbols and commas
    cleaned = amount_str.strip().replace("$", "").replace(",", "")

    # Handle negative amounts in parentheses: (100.00) -> -100.00
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]

    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def create_tables():
    """Create the campaign finance tables if they don't exist."""
    print("Creating campaign finance tables...")
    Base.metadata.create_all(engine, tables=[
        CampaignContribution.__table__,
        Politician.__table__,
    ])
    print("  Tables ready")


def download_accountability_data() -> str:
    """Download pre-cleaned data from Accountability Project."""
    import gzip

    print(f"Downloading from Accountability Project...")
    print("  (This is ~500MB compressed, may take a few minutes)")

    response = requests.get(ACCOUNTABILITY_PROJECT_URL, stream=True, timeout=300)
    response.raise_for_status()

    # Decompress gzip
    content = gzip.decompress(response.content)
    size_mb = len(content) / (1024 * 1024)
    print(f"  Downloaded and decompressed: {size_mb:.1f} MB")

    return content.decode("utf-8")


def download_ohio_sos_file(year: int, committee_type: str) -> str | None:
    """
    Download a single CSV file from Ohio SOS.
    Returns CSV content or None if not available.
    """
    # Ohio SOS uses a specific URL pattern
    # This is an approximation - actual URL may need adjustment
    url = f"https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:DOWNLOAD:{committee_type}:{year}"

    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            return response.text
    except Exception as e:
        print(f"    Could not download {committee_type}_{year}: {e}")

    return None


def import_from_csv(csv_content: str, db: Session, source_file: str = "bulk") -> dict:
    """Import contributions from CSV content."""
    stats = {
        "total": 0,
        "imported": 0,
        "skipped": 0,
        "errors": 0,
    }

    # Detect delimiter (comma or tab)
    first_line = csv_content.split("\n")[0]
    delimiter = "\t" if "\t" in first_line else ","

    reader = csv.DictReader(StringIO(csv_content), delimiter=delimiter)

    batch = []
    batch_size = 5000

    # Map common column name variations
    def get_field(row, *names):
        for name in names:
            if name in row and row[name]:
                return row[name].strip()
            # Try lowercase
            if name.lower() in row and row[name.lower()]:
                return row[name.lower()].strip()
        return None

    for row in reader:
        stats["total"] += 1

        try:
            # Extract fields (handle various column naming conventions)
            committee_name = get_field(row, "com_name", "COMMITTEE_NAME", "committee_name", "COM_NAME")
            committee_type = get_field(row, "file_type", "COMMITTEE_TYPE", "committee_type", "FILE_TYPE")

            first = get_field(row, "first", "FIRST", "first_name", "FIRST_NAME") or ""
            middle = get_field(row, "middle", "MIDDLE", "middle_name", "MIDDLE_NAME") or ""
            last = get_field(row, "last", "LAST", "last_name", "LAST_NAME") or ""
            suffix = get_field(row, "suffix", "SUFFIX") or ""

            # For business contributions, name might be in a single field
            contributor_name = get_field(row, "contributor", "CONTRIBUTOR", "non_individual", "NON_INDIVIDUAL")
            if not contributor_name:
                contributor_name = f"{first} {middle} {last}".strip()

            address = get_field(row, "address", "ADDRESS", "address1", "ADDRESS1")
            city = get_field(row, "city", "CITY")
            state = get_field(row, "state", "STATE")
            zip_code = get_field(row, "zip", "ZIP", "zip_code", "ZIP_CODE")

            amount_str = get_field(row, "amount", "AMOUNT", "contribution_amount", "CONTRIBUTION_AMOUNT")
            amount = parse_amount(amount_str) if amount_str else 0.0

            date_str = get_field(row, "date", "DATE", "contribution_date", "CONTRIBUTION_DATE", "event")
            contribution_date = parse_date(date_str) if date_str else None

            report_year_str = get_field(row, "rpt_year", "RPT_YEAR", "report_year", "REPORT_YEAR", "file_year")
            report_year = int(report_year_str) if report_year_str and report_year_str.isdigit() else None

            master_key_str = get_field(row, "master_key", "MASTER_KEY", "committee_id")
            master_key = int(master_key_str) if master_key_str and master_key_str.isdigit() else None

            district_str = get_field(row, "district", "DISTRICT")
            district = int(district_str) if district_str and district_str.isdigit() else None

            # Skip if no committee or amount
            if not committee_name or amount == 0.0:
                stats["skipped"] += 1
                continue

            # Normalize contributor name for matching
            name_normalized = normalize_contributor_name(first, middle, last, suffix)
            if not name_normalized and contributor_name:
                name_normalized = normalize_name(contributor_name)

            contribution = CampaignContribution(
                committee_name=committee_name[:255] if committee_name else None,
                committee_type=committee_type[:10] if committee_type else None,
                master_key=master_key,
                district=district,
                contributor_first=first[:100] if first else None,
                contributor_middle=middle[:100] if middle else None,
                contributor_last=last[:100] if last else None,
                contributor_suffix=suffix[:20] if suffix else None,
                contributor_name=contributor_name[:255] if contributor_name else None,
                contributor_name_normalized=name_normalized[:255] if name_normalized else None,
                address=address[:255] if address else None,
                city=city[:100] if city else None,
                state=state[:2] if state else None,
                zip_code=zip_code[:10] if zip_code else None,
                amount=amount,
                contribution_date=contribution_date,
                report_year=report_year,
                source_file=source_file[:100] if source_file else None,
            )

            batch.append(contribution)
            stats["imported"] += 1

            # Commit in batches
            if len(batch) >= batch_size:
                db.bulk_save_objects(batch)
                db.commit()
                print(f"    Imported {stats['imported']:,} contributions...", end="\r")
                batch = []

        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error on row {stats['total']}: {e}")

    # Final batch
    if batch:
        db.bulk_save_objects(batch)
        db.commit()

    return stats


def build_politicians_table(db: Session):
    """Build politicians lookup table from unique committees."""
    print("\nBuilding politicians table...")

    # Get unique candidate committees
    committees = db.query(
        CampaignContribution.master_key,
        CampaignContribution.committee_name,
        CampaignContribution.committee_type,
        CampaignContribution.district,
        func.sum(CampaignContribution.amount).label("total"),
        func.count(CampaignContribution.id).label("count"),
        func.min(CampaignContribution.report_year).label("min_year"),
        func.max(CampaignContribution.report_year).label("max_year"),
    ).filter(
        CampaignContribution.committee_type == "CAN",
        CampaignContribution.master_key.isnot(None),
    ).group_by(
        CampaignContribution.master_key,
        CampaignContribution.committee_name,
        CampaignContribution.committee_type,
        CampaignContribution.district,
    ).all()

    print(f"  Found {len(committees):,} candidate committees")

    created = 0
    for com in committees:
        # Check if already exists
        existing = db.query(Politician).filter(
            Politician.master_key == com.master_key
        ).first()

        if existing:
            # Update stats
            existing.total_contributions = com.total
            existing.contribution_count = com.count
            existing.years_active = f"{com.min_year}-{com.max_year}" if com.min_year else None
        else:
            # Extract candidate name from committee name
            # Typical format: "Friends of John Smith" or "John Smith for Senate"
            name = com.committee_name
            for prefix in ["Friends of ", "Committee to Elect ", "Citizens for "]:
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            for suffix in [" for Governor", " for Senate", " for House", " for Congress",
                          " for State Representative", " for State Senator", " Campaign Committee"]:
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
                    break

            politician = Politician(
                master_key=com.master_key,
                committee_name=com.committee_name,
                name=name,
                name_normalized=normalize_name(name),
                district=str(com.district) if com.district else None,
                total_contributions=com.total,
                contribution_count=com.count,
                years_active=f"{com.min_year}-{com.max_year}" if com.min_year else None,
            )
            db.add(politician)
            created += 1

    db.commit()
    print(f"  Created {created:,} politician records")


def match_contributors_to_recipients(db: Session) -> dict:
    """
    Cross-reference contributors against recipients.
    Creates fraud flags for matches.
    """
    print("\nMatching contributors to recipients...")

    stats = {
        "checked": 0,
        "matches_found": 0,
        "flags_created": 0,
        "already_flagged": 0,
    }

    # Get distinct contributors with significant donations
    contributors = db.query(
        CampaignContribution.contributor_name_normalized,
        CampaignContribution.city,
        func.sum(CampaignContribution.amount).label("total_donated"),
        func.count(CampaignContribution.id).label("num_contributions"),
        func.min(CampaignContribution.contribution_date).label("first_donation"),
        func.max(CampaignContribution.contribution_date).label("last_donation"),
    ).filter(
        CampaignContribution.contributor_name_normalized.isnot(None),
        CampaignContribution.contributor_name_normalized != "",
        CampaignContribution.amount > 0,
    ).group_by(
        CampaignContribution.contributor_name_normalized,
        CampaignContribution.city,
    ).having(
        func.sum(CampaignContribution.amount) >= 1000  # Only significant donors
    ).all()

    print(f"  Checking {len(contributors):,} significant contributors...")

    for contrib in contributors:
        stats["checked"] += 1

        # Find matching recipients
        matches = db.query(Recipient).filter(
            Recipient.name_normalized == contrib.contributor_name_normalized
        ).all()

        # If we have city, filter further
        if contrib.city and matches:
            city_matches = [m for m in matches if m.city and
                          m.city.lower() == contrib.city.lower()]
            if city_matches:
                matches = city_matches

        for recipient in matches:
            stats["matches_found"] += 1

            # Update the contributions with the match
            db.query(CampaignContribution).filter(
                CampaignContribution.contributor_name_normalized == contrib.contributor_name_normalized,
                CampaignContribution.city == contrib.city,
            ).update({
                "matched_recipient_id": recipient.id,
                "match_confidence": 1.0 if contrib.city else 0.8,
                "match_method": "name_city" if contrib.city else "name_only",
            })

            # Check if already flagged
            existing_flag = db.query(FraudFlag).filter(
                FraudFlag.recipient_id == recipient.id,
                FraudFlag.flag_type == "political_donor"
            ).first()

            if existing_flag:
                stats["already_flagged"] += 1
                continue

            # Get recipient's total awards
            from app.models import Award
            total_awards = db.query(func.sum(Award.amount)).filter(
                Award.recipient_id == recipient.id
            ).scalar() or 0

            # Create fraud flag
            evidence = {
                "total_donated": float(contrib.total_donated),
                "num_contributions": contrib.num_contributions,
                "first_donation": contrib.first_donation.isoformat() if contrib.first_donation else None,
                "last_donation": contrib.last_donation.isoformat() if contrib.last_donation else None,
                "total_awards_received": float(total_awards),
                "donor_city": contrib.city,
            }

            # Determine severity based on amounts
            severity = "low"
            if contrib.total_donated >= 10000:
                severity = "high"
            elif contrib.total_donated >= 5000:
                severity = "medium"

            flag = FraudFlag(
                recipient_id=recipient.id,
                flag_type="political_donor",
                severity=severity,
                description=f"Recipient donated ${contrib.total_donated:,.0f} to political campaigns "
                           f"({contrib.num_contributions} contributions from {contrib.first_donation} to {contrib.last_donation}). "
                           f"Also received ${total_awards:,.0f} in government awards.",
                evidence=str(evidence),
            )

            db.add(flag)
            stats["flags_created"] += 1

            if stats["flags_created"] <= 10:
                print(f"    Match: {recipient.name} donated ${contrib.total_donated:,.0f}, received ${total_awards:,.0f}")

        if stats["checked"] % 1000 == 0:
            print(f"    Checked {stats['checked']:,}...", end="\r")

    db.commit()

    print(f"\n  Matching complete")
    print(f"    - Contributors checked: {stats['checked']:,}")
    print(f"    - Matches found: {stats['matches_found']:,}")
    print(f"    - New flags created: {stats['flags_created']:,}")
    print(f"    - Already flagged: {stats['already_flagged']:,}")

    return stats


def get_import_stats(db: Session):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("Campaign Finance Import Summary")
    print("=" * 60)

    total = db.query(func.count(CampaignContribution.id)).scalar()
    total_amount = db.query(func.sum(CampaignContribution.amount)).scalar() or 0

    print(f"Total contributions: {total:,}")
    print(f"Total amount: ${total_amount:,.0f}")

    # By committee type
    print("\nBy committee type:")
    by_type = db.query(
        CampaignContribution.committee_type,
        func.count(CampaignContribution.id),
        func.sum(CampaignContribution.amount),
    ).group_by(CampaignContribution.committee_type).all()

    for ctype, count, amount in by_type:
        type_name = COMMITTEE_TYPES.get(ctype, ctype or "Unknown")
        print(f"  {type_name}: {count:,} contributions (${amount or 0:,.0f})")

    # Year range
    min_year = db.query(func.min(CampaignContribution.report_year)).scalar()
    max_year = db.query(func.max(CampaignContribution.report_year)).scalar()
    print(f"\nData coverage: {min_year} - {max_year}")

    # Politicians
    politician_count = db.query(func.count(Politician.id)).scalar()
    print(f"Politicians extracted: {politician_count:,}")

    # Matched recipients
    matched = db.query(func.count(CampaignContribution.id)).filter(
        CampaignContribution.matched_recipient_id.isnot(None)
    ).scalar()
    print(f"Contributions matched to recipients: {matched:,}")

    # Flags
    donor_flags = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.flag_type == "political_donor"
    ).scalar()
    print(f"Recipients flagged as political donors: {donor_flags:,}")


def main():
    """Main import process."""
    import argparse

    parser = argparse.ArgumentParser(description="Import Ohio campaign finance data")
    parser.add_argument("--source", choices=["accountability", "ohio_sos", "file"],
                       default="file", help="Data source")
    parser.add_argument("--file", type=str, help="Path to local CSV file")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument("--skip-match", action="store_true", help="Skip recipient matching")
    parser.add_argument("--clear", action="store_true", help="Clear existing data first")

    args = parser.parse_args()

    print("=" * 60)
    print("Ohio Campaign Finance Import")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Create tables
    create_tables()

    db = SessionLocal()

    try:
        # Track import
        data_import = DataImport(
            source="campaign_finance",
            status="running",
        )
        db.add(data_import)
        db.commit()

        # Clear existing data if requested
        if args.clear:
            print("\nClearing existing data...")
            deleted = db.query(CampaignContribution).delete()
            db.query(Politician).delete()
            db.commit()
            print(f"  Cleared {deleted:,} contributions")

        # Import data based on source
        if args.source == "file" and args.file:
            print(f"\nImporting from file: {args.file}")
            with open(args.file, "r", encoding="utf-8", errors="replace") as f:
                csv_content = f.read()
            stats = import_from_csv(csv_content, db, source_file=os.path.basename(args.file))

        elif args.source == "accountability":
            csv_content = download_accountability_data()
            stats = import_from_csv(csv_content, db, source_file="accountability_project")

        else:
            print("\nPlease provide a --file argument or use --source accountability")
            print("\nTo download Ohio SOS data manually:")
            print("  1. Go to https://www.ohiosos.gov/campaign-finance/search/")
            print("  2. Use 'Bulk Export' option")
            print("  3. Download CSV files for desired years")
            print("  4. Run: python import_campaign_finance.py --file path/to/file.csv")
            return

        print(f"\n  Total rows: {stats['total']:,}")
        print(f"  Imported: {stats['imported']:,}")
        print(f"  Skipped: {stats['skipped']:,}")
        print(f"  Errors: {stats['errors']:,}")

        # Build politicians table
        build_politicians_table(db)

        # Match to recipients
        if not args.skip_match:
            match_contributors_to_recipients(db)

        # Update import record
        data_import.status = "completed"
        data_import.completed_at = datetime.utcnow()
        data_import.records_processed = stats["total"]
        data_import.records_created = stats["imported"]
        db.commit()

        # Print summary
        get_import_stats(db)

    except Exception as e:
        print(f"\nError: {e}")
        data_import.status = "failed"
        data_import.error_message = str(e)
        db.commit()
        raise

    finally:
        db.close()

    print("\n" + "=" * 60)
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
