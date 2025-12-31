"""
USAspending Bulk Import Script

Pulls all Ohio grants, loans, and contracts from USAspending.gov
and imports them into the local database.

Usage:
    python -m scripts.import_usaspending

Options:
    --start-year    Starting fiscal year (default: 2015)
    --end-year      Ending fiscal year (default: current)
    --award-types   Comma-separated types: grants,loans,contracts (default: grants,loans)
    --clear         Clear existing USAspending data before import
    --resume        Resume from last successful year (checks existing data)
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any
import time

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.database import get_db_context, init_db
from app.models import Award, Recipient, Agency, SubAgency, DataImport, normalize_name

# Import the USAspending client we already built
from src.data_sources.usaspending import (
    USASpendingClient,
    USASpendingConfig,
    GRANT_TYPES,
    LOAN_TYPES,
    CONTRACT_TYPES,
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Map from Award Type text to our type
AWARD_TYPE_TEXT_MAPPING = {
    "BLOCK GRANT": "block_grant",
    "FORMULA GRANT": "formula_grant",
    "PROJECT GRANT": "project_grant",
    "COOPERATIVE AGREEMENT": "cooperative_agreement",
    "DIRECT PAYMENT": "direct_payment",
    "DIRECT LOAN": "direct_loan",
    "GUARANTEED/INSURED LOAN": "guaranteed_loan",
    "INSURANCE": "insurance",
    "OTHER": "other",
}

# Agency code mapping (USAspending uses full names, we want codes)
AGENCY_CODES = {
    "Department of Health and Human Services": "HHS",
    "Department of Education": "ED",
    "Department of Transportation": "DOT",
    "Department of Housing and Urban Development": "HUD",
    "Department of Energy": "DOE",
    "National Science Foundation": "NSF",
    "Department of Agriculture": "USDA",
    "Environmental Protection Agency": "EPA",
    "Department of Justice": "DOJ",
    "Department of Labor": "DOL",
    "Department of Defense": "DOD",
    "Department of the Treasury": "TRES",
    "Department of Commerce": "DOC",
    "Department of the Interior": "DOI",
    "Department of Veterans Affairs": "VA",
    "Department of Homeland Security": "DHS",
    "Small Business Administration": "SBA",
    "National Aeronautics and Space Administration": "NASA",
    "Social Security Administration": "SSA",
    "Agency for International Development": "USAID",
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_or_create_agency(db: Session, name: str) -> Optional[int]:
    """Get or create agency by name, return ID"""
    if not name:
        return None
    
    code = AGENCY_CODES.get(name, name[:10].upper().replace(" ", ""))
    
    agency = db.query(Agency).filter(Agency.code == code).first()
    if agency:
        return agency.id
    
    agency = Agency(code=code, name=name)
    db.add(agency)
    db.flush()
    return agency.id


def get_or_create_sub_agency(db: Session, agency_id: int, name: str) -> Optional[int]:
    """Get or create sub-agency by name, return ID"""
    if not name or not agency_id:
        return None
    
    sub = db.query(SubAgency).filter(
        SubAgency.agency_id == agency_id,
        SubAgency.name == name
    ).first()
    
    if sub:
        return sub.id
    
    sub = SubAgency(agency_id=agency_id, name=name)
    db.add(sub)
    db.flush()
    return sub.id


def get_or_create_recipient(db: Session, award_data, new_ids_tracker: dict = None) -> int:
    """Get or create recipient from award data, return ID"""
    
    name = award_data.recipient_name or "Unknown Recipient"
    normalized = normalize_name(name)
    city = award_data.recipient_city
    
    recipient = db.query(Recipient).filter(
        Recipient.name_normalized == normalized,
        Recipient.city == city
    ).first()
    
    if recipient:
        return recipient.id
    
    recipient = Recipient(
        name=name,
        name_normalized=normalized,
        city=city,
        state=award_data.recipient_state or "OH",
        business_status="unknown",
    )
    db.add(recipient)
    db.flush()
    
    # Track new recipient for post-import analysis
    if new_ids_tracker is not None:
        new_ids_tracker["recipients"].add(recipient.id)
    
    return recipient.id


def parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse date string to date object"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def map_award_type(award_type_text: str) -> str:
    """Map USAspending award type text to our type"""
    if not award_type_text:
        return "other"
    
    type_part = award_type_text.split("(")[0].strip().upper()
    return AWARD_TYPE_TEXT_MAPPING.get(type_part, "other")


def get_years_with_data(db: Session, source: str = "usaspending") -> set:
    """Get set of years that have data imported"""
    results = db.query(
        extract('year', Award.award_date)
    ).filter(
        Award.source == source,
        Award.award_date.isnot(None)
    ).distinct().all()
    
    return {int(r[0]) for r in results if r[0]}


# =============================================================================
# IMPORT FUNCTIONS
# =============================================================================

def import_year(
    db: Session,
    client: USASpendingClient,
    group_name: str,
    award_types: List[str],
    year: int,
    stats: Dict[str, int],
    new_ids_tracker: dict = None,
) -> bool:
    """Import a single year of data. Returns True if successful."""
    
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    
    print(f"\n--- {group_name.upper()} {year} ---")
    
    batch_num = 0
    year_count = 0
    year_created = 0
    
    try:
        for batch in client.iter_awards(
            state="OH",
            award_types=award_types,
            start_date=start_date,
            end_date=end_date,
            max_records=None
        ):
            batch_num += 1
            year_count += len(batch)
            
            for award_data in batch:
                stats["processed"] += 1
                
                try:
                    source_id = award_data.generated_internal_id or award_data.award_id
                    
                    if not source_id:
                        stats["skipped"] += 1
                        continue
                    
                    existing = db.query(Award).filter(
                        Award.source == "usaspending",
                        Award.source_award_id == source_id
                    ).first()
                    
                    if existing:
                        existing.amount = award_data.total_obligation
                        existing.description = (award_data.description or "")[:500]
                        existing.last_modified = datetime.now(timezone.utc)
                        stats["updated"] += 1
                        continue
                    
                    agency_id = get_or_create_agency(db, award_data.awarding_agency)
                    sub_agency_id = get_or_create_sub_agency(
                        db, agency_id, award_data.awarding_sub_agency
                    ) if agency_id else None
                    recipient_id = get_or_create_recipient(db, award_data, new_ids_tracker)
                    
                    award = Award(
                        source="usaspending",
                        source_award_id=source_id,
                        recipient_id=recipient_id,
                        agency_id=agency_id,
                        sub_agency_id=sub_agency_id,
                        award_type=map_award_type(award_data.award_type),
                        amount=award_data.total_obligation or 0,
                        award_date=parse_date(award_data.start_date),
                        start_date=parse_date(award_data.start_date),
                        end_date=parse_date(award_data.end_date),
                        description=(award_data.description or "")[:500],
                        cfda_number=award_data.cfda_number,
                        pop_city=award_data.place_of_performance_city,
                        pop_state=award_data.place_of_performance_state,
                        last_modified=datetime.now(timezone.utc),
                    )
                    db.add(award)
                    db.flush()  # Get award ID
                    
                    # Track new award for post-import analysis
                    if new_ids_tracker is not None:
                        new_ids_tracker["awards"].add(award.id)
                    
                    stats["created"] += 1
                    year_created += 1
                    
                except Exception as e:
                    stats["errors"] += 1
                    print(f"    Error: {e}")
                    continue
            
            # Commit after each batch
            db.commit()
            print(f"  Batch {batch_num}: {len(batch)} awards (year total: {year_count}, created: {year_created})")
        
        print(f"  ✓ Year {year} complete: {year_count} processed, {year_created} new")
        return True
        
    except Exception as e:
        print(f"  ✗ Year {year} FAILED: {e}")
        db.rollback()
        return False


def import_award_group(
    db: Session,
    client: USASpendingClient,
    group_name: str,
    award_types: List[str],
    start_year: int,
    end_year: int,
    stats: Dict[str, int],
    skip_years: set = None,
    new_ids_tracker: dict = None,
):
    """Import a group of award types, year by year"""
    
    print(f"\n{'='*60}")
    print(f"Importing Ohio {group_name} from {start_year} to {end_year}...")
    print(f"Award type codes: {award_types}")
    if skip_years:
        print(f"Skipping years with existing data: {sorted(skip_years)}")
    print(f"{'='*60}")
    
    failed_years = []
    
    for year in range(start_year, end_year + 1):
        if skip_years and year in skip_years:
            print(f"\n--- Skipping {year} (already has data) ---")
            continue
        
        success = import_year(db, client, group_name, award_types, year, stats, new_ids_tracker)
        
        if not success:
            failed_years.append(year)
            print(f"\n⚠️  Pausing for 30 seconds before continuing...")
            time.sleep(30)
    
    if failed_years:
        print(f"\n⚠️  Failed years: {failed_years}")
        print("Run the import again to retry these years.")


def clear_usaspending_data(db: Session):
    """Remove all USAspending data to allow fresh import"""
    print("\nClearing existing USAspending data...")
    
    count = db.query(Award).filter(Award.source == "usaspending").delete()
    db.commit()
    
    print(f"  Deleted {count} awards")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Import USAspending data for Ohio")
    parser.add_argument("--start-year", type=int, default=2015, help="Starting fiscal year")
    parser.add_argument("--end-year", type=int, default=datetime.now().year, help="Ending fiscal year")
    parser.add_argument("--award-types", default="grants,loans", help="Comma-separated: grants,loans,contracts")
    parser.add_argument("--clear", action="store_true", help="Clear existing data before import")
    parser.add_argument("--resume", action="store_true", help="Skip years that already have data")
    parser.add_argument("--skip-correlation", action="store_true", help="Skip post-import correlation analysis")
    
    args = parser.parse_args()
    
    # Build award type groups
    type_groups = {}
    for t in args.award_types.split(","):
        t = t.strip().lower()
        if t == "grants":
            type_groups["grants"] = GRANT_TYPES
        elif t == "loans":
            type_groups["loans"] = LOAN_TYPES
        elif t == "contracts":
            type_groups["contracts"] = CONTRACT_TYPES
    
    if not type_groups:
        print("Error: No valid award types specified")
        sys.exit(1)
    
    print("=" * 60)
    print("USAspending Import for Ohio")
    print("=" * 60)
    print(f"Date range: {args.start_year} to {args.end_year}")
    print(f"Award type groups: {list(type_groups.keys())}")
    print(f"Clear existing: {args.clear}")
    print(f"Resume mode: {args.resume}")
    print(f"Run correlation: {not args.skip_correlation}")
    
    # Initialize database
    init_db()
    
    # Create slower client for bulk import
    config = USASpendingConfig(
        rate_limit_per_minute=30,  # Slower rate
        timeout=60,
        max_retries=5,
        retry_delay=5.0
    )
    client = USASpendingClient(config=config)
    
    with get_db_context() as db:
        # Clear if requested
        if args.clear:
            clear_usaspending_data(db)
            skip_years = set()
        elif args.resume:
            skip_years = get_years_with_data(db)
            print(f"\nYears with existing data: {sorted(skip_years) if skip_years else 'None'}")
        else:
            skip_years = set()
        
        # Show current database state
        total_awards = db.query(func.count(Award.id)).scalar()
        print(f"\nCurrent database: {total_awards:,} awards")
        
        # Track stats
        stats = {
            "processed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
        }
        
        # Track new IDs for post-import correlation
        new_ids_tracker = {
            "recipients": set(),
            "awards": set()
        }
        
        start_time = time.time()
        
        try:
            # Import each award type group
            for group_name, award_types in type_groups.items():
                import_award_group(
                    db, client, group_name, award_types,
                    args.start_year, args.end_year, stats, skip_years,
                    new_ids_tracker
                )
            
            elapsed = time.time() - start_time
            
            # Print summary
            print("\n" + "=" * 60)
            print("IMPORT COMPLETE")
            print("=" * 60)
            print(f"Time elapsed: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
            print(f"Records processed: {stats['processed']:,}")
            print(f"Records created: {stats['created']:,}")
            print(f"Records updated: {stats['updated']:,}")
            print(f"Records skipped: {stats['skipped']:,}")
            print(f"Errors: {stats['errors']:,}")
            
            # Print database totals
            total_awards = db.query(func.count(Award.id)).scalar()
            total_recipients = db.query(func.count(Recipient.id)).scalar()
            total_amount = db.query(func.sum(Award.amount)).scalar() or 0
            
            print(f"\nDatabase totals:")
            print(f"  Total awards: {total_awards:,}")
            print(f"  Total recipients: {total_recipients:,}")
            print(f"  Total amount: ${total_amount:,.2f}")
            
            # Run post-import correlation analysis
            if not args.skip_correlation and (new_ids_tracker["recipients"] or new_ids_tracker["awards"]):
                print("\n" + "=" * 60)
                print("POST-IMPORT CORRELATION ANALYSIS")
                print("=" * 60)
                
                try:
                    from src.correlation.post_import import run_post_import_analysis
                    
                    correlation_results = run_post_import_analysis(
                        db=db,
                        source="usaspending",
                        new_recipient_ids=list(new_ids_tracker["recipients"]),
                        new_award_ids=list(new_ids_tracker["awards"]),
                    )
                    
                    print(f"\nCorrelation Results:")
                    print(f"  New recipients analyzed: {correlation_results['new_recipients']}")
                    print(f"  New awards analyzed: {correlation_results['new_awards']}")
                    print(f"  Flags created: {correlation_results['flags_created']}")
                    if correlation_results.get('flags_by_type'):
                        print(f"  By type: {correlation_results['flags_by_type']}")
                        
                except Exception as e:
                    print(f"\n⚠️  Correlation analysis failed: {e}")
                    print("Run 'python -m scripts.run_correlation' manually to analyze")
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Import interrupted by user")
            print("Run with --resume to continue from where you left off")
            db.commit()  # Save progress
            
        except Exception as e:
            print(f"\nIMPORT FAILED: {e}")
            db.commit()  # Save progress
            print("Run with --resume to continue from where you left off")
            raise


if __name__ == "__main__":
    main()
