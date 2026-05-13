"""
Import OIG LEIE (List of Excluded Individuals/Entities) data.

Downloads the federal exclusion list and imports it into the database,
then cross-references against existing recipients to flag any matches.

Data source: https://oig.hhs.gov/exclusions/exclusions_list.asp
"""

import sys
import os
import csv
import requests
from datetime import datetime, date
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, func
from sqlalchemy.orm import Session
from app.database import engine, SessionLocal
from app.models import ExcludedEntity, Recipient, FraudFlag, Base

# LEIE Download URL (updated monthly)
LEIE_URL = "https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv"

# LEIE CSV columns (based on OIG record layout)
# The CSV has these columns in order:
LEIE_COLUMNS = [
    "LASTNAME",      # Last name (individuals)
    "FIRSTNAME",     # First name (individuals)
    "MIDNAME",       # Middle name (individuals)
    "BUSNAME",       # Business name (entities)
    "GENERAL",       # INDIV or ENTITY
    "SPECIALTY",     # Medical specialty
    "UPIN",          # Unique Physician ID (legacy)
    "NPI",           # National Provider Identifier
    "DOB",           # Date of birth (YYYYMMDD format)
    "ADDRESS",       # Street address
    "CITY",          # City
    "STATE",         # State code
    "ZIP",           # ZIP code
    "EXCLTYPE",      # Exclusion type code
    "EXCLDATE",      # Exclusion date (YYYYMMDD)
    "REINDATE",      # Reinstatement date (YYYYMMDD) - empty if still excluded
    "WAIVERDATE",    # Waiver date (YYYYMMDD)
    "WVRSTATE",      # Waiver state
]


def download_leie() -> str:
    """Download the LEIE CSV file from OIG website."""
    print(f"Downloading LEIE from {LEIE_URL}...")
    
    response = requests.get(LEIE_URL, timeout=60)
    response.raise_for_status()
    
    # The file is typically ~15-20 MB
    size_mb = len(response.content) / (1024 * 1024)
    print(f"  Downloaded {size_mb:.1f} MB")
    
    return response.text


def parse_date(date_str: str) -> date | None:
    """Parse LEIE date format (YYYYMMDD) to Python date."""
    if not date_str or date_str.strip() == "":
        return None
    try:
        # Format is YYYYMMDD
        return datetime.strptime(date_str.strip(), "%Y%m%d").date()
    except ValueError:
        return None


def normalize_name(name: str) -> str:
    """Normalize name for matching."""
    if not name:
        return ""
    # Lowercase, remove common suffixes, strip whitespace and punctuation
    normalized = name.lower().strip()
    # Remove punctuation
    for char in [",", ".", "'", '"', "-"]:
        normalized = normalized.replace(char, " ")
    # Remove common business suffixes
    for suffix in [" llc", " inc", " corp", " ltd", " co", " company", 
                   " incorporated", " corporation", " limited", " pllc",
                   " pc", " pa", " md", " do", " dds", " dpm"]:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    # Collapse multiple spaces
    normalized = " ".join(normalized.split())
    return normalized.strip()


def create_tables():
    """Drop and recreate the excluded_entities table to ensure sequence is correct."""
    print("Recreating excluded_entities table...")
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS excluded_entities CASCADE"))
        conn.commit()
    Base.metadata.create_all(engine, tables=[ExcludedEntity.__table__])
    print("  ✓ Table ready")


def import_leie_data(csv_content: str, db: Session) -> dict:
    """Import LEIE CSV data into the database."""
    print("Importing LEIE data...")
    
    # Parse CSV
    reader = csv.DictReader(StringIO(csv_content))
    
    stats = {
        "total": 0,
        "individuals": 0,
        "entities": 0,
        "ohio_records": 0,
        "errors": 0,
    }
    
    batch = []
    batch_size = 1000
    
    for row in reader:
        stats["total"] += 1
        
        try:
            # Build normalized name
            if row.get("BUSNAME"):
                name_normalized = normalize_name(row["BUSNAME"])
            else:
                # Combine individual name parts
                name_parts = [
                    row.get("FIRSTNAME", ""),
                    row.get("MIDNAME", ""),
                    row.get("LASTNAME", "")
                ]
                name_normalized = normalize_name(" ".join(p for p in name_parts if p))
            
            batch.append({
                "last_name": row.get("LASTNAME", "").strip() or None,
                "first_name": row.get("FIRSTNAME", "").strip() or None,
                "middle_name": row.get("MIDNAME", "").strip() or None,
                "business_name": row.get("BUSNAME", "").strip() or None,
                "name_normalized": name_normalized or None,
                "general_type": row.get("GENERAL", "").strip() or None,
                "specialty": row.get("SPECIALTY", "").strip() or None,
                "upin": row.get("UPIN", "").strip() or None,
                "npi": row.get("NPI", "").strip() or None,
                "dob": parse_date(row.get("DOB", "")),
                "address": row.get("ADDRESS", "").strip() or None,
                "city": row.get("CITY", "").strip() or None,
                "state": row.get("STATE", "").strip() or None,
                "zip_code": row.get("ZIP", "").strip() or None,
                "exclusion_type": row.get("EXCLTYPE", "").strip() or None,
                "exclusion_date": parse_date(row.get("EXCLDATE", "")),
                "reinstatement_date": parse_date(row.get("REINDATE", "")),
                "waiver_date": parse_date(row.get("WAIVERDATE", "")),
                "waiver_state": row.get("WVRSTATE", "").strip() or None,
            })
            
            # Track stats
            if row.get("GENERAL") == "INDIV":
                stats["individuals"] += 1
            else:
                stats["entities"] += 1
            
            if row.get("STATE") == "OH":
                stats["ohio_records"] += 1
            
            # Commit in batches
            if len(batch) >= batch_size:
                db.bulk_insert_mappings(ExcludedEntity, batch)
                db.commit()
                print(f"    Imported {stats['total']:,} records...", end="\r")
                batch = []
                
        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error on row {stats['total']}: {e}")
    
    # Final batch
    if batch:
        db.bulk_insert_mappings(ExcludedEntity, batch)
        db.commit()
    
    print(f"  ✓ Imported {stats['total']:,} total records")
    print(f"    - Individuals: {stats['individuals']:,}")
    print(f"    - Entities: {stats['entities']:,}")
    print(f"    - Ohio records: {stats['ohio_records']:,}")
    if stats["errors"]:
        print(f"    - Errors: {stats['errors']:,}")
    
    return stats


def match_recipients(db: Session) -> dict:
    """
    Cross-reference excluded entities against recipients.
    Creates fraud flags for any matches found.
    """
    print("\nMatching excluded entities against recipients...")
    
    stats = {
        "checked": 0,
        "matches_found": 0,
        "flags_created": 0,
        "already_flagged": 0,
    }
    
    # Get all excluded entities (focus on Ohio + nearby states, plus entities)
    excluded = db.query(ExcludedEntity).filter(
        (ExcludedEntity.state.in_(["OH", "KY", "IN", "PA", "WV", "MI"])) |
        (ExcludedEntity.general_type == "ENTITY")
    ).all()
    
    print(f"  Checking {len(excluded):,} excluded entities...")
    
    for exc in excluded:
        stats["checked"] += 1
        
        if not exc.name_normalized:
            continue
        
        # Find matching recipients by normalized name
        # Use LIKE for partial matching on business names
        matches = db.query(Recipient).filter(
            Recipient.name_normalized.ilike(f"%{exc.name_normalized}%")
        ).all()
        
        # If we have city, filter further
        if exc.city and matches:
            city_matches = [m for m in matches if m.city and 
                          m.city.lower() == exc.city.lower()]
            if city_matches:
                matches = city_matches
        
        for recipient in matches:
            stats["matches_found"] += 1
            
            # Check if already flagged
            existing_flag = db.query(FraudFlag).filter(
                FraudFlag.recipient_id == recipient.id,
                FraudFlag.flag_type == "excluded_provider"
            ).first()
            
            if existing_flag:
                stats["already_flagged"] += 1
                continue
            
            # Create fraud flag
            evidence = {
                "excluded_name": exc.business_name or f"{exc.first_name} {exc.last_name}",
                "excluded_type": exc.general_type,
                "exclusion_date": exc.exclusion_date.isoformat() if exc.exclusion_date else None,
                "exclusion_type": exc.exclusion_type,
                "specialty": exc.specialty,
                "npi": exc.npi,
                "excluded_city": exc.city,
                "excluded_state": exc.state,
            }
            
            flag = FraudFlag(
                recipient_id=recipient.id,
                flag_type="excluded_provider",
                severity="high",
                description=f"Recipient matches OIG excluded entity: {evidence['excluded_name']}. "
                           f"Excluded from federal healthcare programs on {evidence['exclusion_date']}. "
                           f"Exclusion type: {exc.exclusion_type}.",
                evidence=str(evidence),
            )
            
            db.add(flag)
            stats["flags_created"] += 1
            
            print(f"    ⚠ MATCH: {recipient.name} ({recipient.city}) -> {evidence['excluded_name']}")
        
        if stats["checked"] % 1000 == 0:
            print(f"    Checked {stats['checked']:,}...", end="\r")
    
    db.commit()
    
    print(f"\n  ✓ Matching complete")
    print(f"    - Entities checked: {stats['checked']:,}")
    print(f"    - Matches found: {stats['matches_found']:,}")
    print(f"    - New flags created: {stats['flags_created']:,}")
    print(f"    - Already flagged: {stats['already_flagged']:,}")
    
    return stats


def add_indexes():
    """Add indexes for faster matching."""
    print("\nAdding indexes...")
    
    indexes = [
        ("idx_excluded_name_norm", "CREATE INDEX IF NOT EXISTS idx_excluded_name_norm ON excluded_entities(name_normalized)"),
        ("idx_excluded_state", "CREATE INDEX IF NOT EXISTS idx_excluded_state ON excluded_entities(state)"),
        ("idx_excluded_npi", "CREATE INDEX IF NOT EXISTS idx_excluded_npi ON excluded_entities(npi)"),
    ]
    
    with engine.connect() as conn:
        for name, sql in indexes:
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"  ✓ {name}")
            except Exception as e:
                print(f"  ⚠ {name}: {e}")


def get_exclusion_stats(db: Session):
    """Print summary statistics."""
    print("\n" + "=" * 50)
    print("LEIE Import Summary")
    print("=" * 50)
    
    total = db.query(func.count(ExcludedEntity.id)).scalar()
    ohio = db.query(func.count(ExcludedEntity.id)).filter(ExcludedEntity.state == "OH").scalar()
    entities = db.query(func.count(ExcludedEntity.id)).filter(ExcludedEntity.general_type == "ENTITY").scalar()
    individuals = db.query(func.count(ExcludedEntity.id)).filter(ExcludedEntity.general_type == "INDIV").scalar()
    
    print(f"Total excluded entities: {total:,}")
    print(f"  - Ohio records: {ohio:,}")
    print(f"  - Individuals: {individuals:,}")
    print(f"  - Business entities: {entities:,}")
    
    # Flags created
    excluded_flags = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.flag_type == "excluded_provider"
    ).scalar()
    print(f"\nRecipients flagged as excluded: {excluded_flags:,}")
    
    # Most common exclusion types
    print("\nTop exclusion types:")
    type_counts = db.query(
        ExcludedEntity.exclusion_type,
        func.count(ExcludedEntity.id)
    ).group_by(ExcludedEntity.exclusion_type).order_by(
        func.count(ExcludedEntity.id).desc()
    ).limit(5).all()
    
    exclusion_type_names = {
        "1128a1": "Conviction: Program-related crimes",
        "1128a2": "Conviction: Patient abuse/neglect",
        "1128a3": "Conviction: Healthcare fraud felony",
        "1128a4": "Conviction: Controlled substance felony",
        "1128b1": "Misdemeanor: Healthcare fraud",
        "1128b2": "Misdemeanor: Controlled substance",
        "1128b4": "License revocation/suspension",
        "1128b5": "Exclusion by another federal agency",
        "1128b6": "Excess charges, services",
        "1128b7": "Fraud, kickbacks",
        "1128b14": "Default on health education loan",
        "1128b15": "Entities owned/controlled by excluded",
        "1128b16": "Affiliation with excluded entity",
    }
    
    for exc_type, count in type_counts:
        type_name = exclusion_type_names.get(exc_type, exc_type)
        print(f"  {exc_type}: {count:,} ({type_name})")


def main():
    """Main import process."""
    print("=" * 50)
    print("OIG LEIE Import")
    print("=" * 50)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Create tables
    create_tables()
    
    # Download LEIE
    csv_content = download_leie()
    
    # Import data
    db = SessionLocal()
    try:
        import_stats = import_leie_data(csv_content, db)
        
        # Add indexes
        add_indexes()
        
        # Match against recipients
        match_stats = match_recipients(db)
        
        # Print summary
        get_exclusion_stats(db)
        
    finally:
        db.close()
    
    print("\n" + "=" * 50)
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)


if __name__ == "__main__":
    main()
