"""
Enrich recipients with business type and NAICS code from PPP data.

Cross-matches recipients by name to copy business_type and naics_code
from PPP loan recipients to recipients from other sources.
"""

from sqlalchemy import text
from app.database import SessionLocal, init_db


def enrich_from_ppp(db, dry_run: bool = False):
    """
    Update recipients without business_type using data from PPP recipients
    with matching names.
    """
    print("Enriching business types from PPP data...")
    print("=" * 60)

    # First, let's see how many we can match
    count_query = text("""
        SELECT COUNT(DISTINCT r1.id)
        FROM recipients r1
        WHERE r1.business_type IS NULL
        AND EXISTS (
            SELECT 1 FROM recipients r2
            JOIN awards a ON a.recipient_id = r2.id
            WHERE a.source = 'sba_ppp'
            AND r2.business_type IS NOT NULL
            AND UPPER(r2.name) = UPPER(r1.name)
            AND r1.id != r2.id
        )
    """)
    potential_matches = db.execute(count_query).scalar()
    print(f"Recipients to update: {potential_matches:,}")

    if dry_run:
        print("\n[DRY RUN] Would update these recipients:")
        sample = db.execute(text("""
            SELECT r1.id, r1.name, r2.business_type, r2.naics_code
            FROM recipients r1
            JOIN recipients r2 ON UPPER(r2.name) = UPPER(r1.name) AND r1.id != r2.id
            JOIN awards a ON a.recipient_id = r2.id
            WHERE a.source = 'sba_ppp'
            AND r1.business_type IS NULL
            AND r2.business_type IS NOT NULL
            LIMIT 10
        """)).fetchall()
        for row in sample:
            print(f"  {row[1][:50]}: -> {row[2]} (NAICS: {row[3]})")
        print(f"  ... and {potential_matches - 10:,} more")
        return {"updated": 0, "dry_run": True, "potential": potential_matches}

    # Update recipients with business_type from PPP matches
    # Use a subquery to get the first matching PPP recipient's data
    update_query = text("""
        UPDATE recipients r1
        SET
            business_type = ppp.business_type,
            naics_code = COALESCE(r1.naics_code, ppp.naics_code)
        FROM (
            SELECT DISTINCT ON (UPPER(r2.name))
                UPPER(r2.name) as upper_name,
                r2.business_type,
                r2.naics_code
            FROM recipients r2
            JOIN awards a ON a.recipient_id = r2.id
            WHERE a.source = 'sba_ppp'
            AND r2.business_type IS NOT NULL
            ORDER BY UPPER(r2.name), r2.id
        ) ppp
        WHERE r1.business_type IS NULL
        AND UPPER(r1.name) = ppp.upper_name
    """)

    result = db.execute(update_query)
    updated = result.rowcount
    db.commit()

    print(f"Updated {updated:,} recipients with business type from PPP data")
    return {"updated": updated, "dry_run": False}


def enrich_naics_only(db, dry_run: bool = False):
    """
    Update recipients that have business_type but missing naics_code.
    """
    print("\nEnriching NAICS codes for recipients with business_type...")
    print("=" * 60)

    count_query = text("""
        SELECT COUNT(DISTINCT r1.id)
        FROM recipients r1
        WHERE r1.naics_code IS NULL
        AND r1.business_type IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM recipients r2
            WHERE r2.naics_code IS NOT NULL
            AND UPPER(r2.name) = UPPER(r1.name)
            AND r1.id != r2.id
        )
    """)
    potential = db.execute(count_query).scalar()
    print(f"Recipients to update: {potential:,}")

    if dry_run:
        return {"updated": 0, "dry_run": True, "potential": potential}

    update_query = text("""
        UPDATE recipients r1
        SET naics_code = (
            SELECT r2.naics_code
            FROM recipients r2
            WHERE r2.naics_code IS NOT NULL
            AND UPPER(r2.name) = UPPER(r1.name)
            AND r1.id != r2.id
            LIMIT 1
        )
        WHERE r1.naics_code IS NULL
        AND r1.business_type IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM recipients r2
            WHERE r2.naics_code IS NOT NULL
            AND UPPER(r2.name) = UPPER(r1.name)
            AND r1.id != r2.id
        )
    """)

    result = db.execute(update_query)
    updated = result.rowcount
    db.commit()

    print(f"Updated {updated:,} recipients with NAICS code")
    return {"updated": updated, "dry_run": False}


def show_stats(db):
    """Show current business type coverage stats."""
    print("\nCurrent business type coverage:")
    print("=" * 60)

    result = db.execute(text("""
        SELECT
            a.source,
            COUNT(DISTINCT r.id) as total,
            COUNT(DISTINCT CASE WHEN r.business_type IS NOT NULL THEN r.id END) as with_type,
            COUNT(DISTINCT CASE WHEN r.naics_code IS NOT NULL THEN r.id END) as with_naics
        FROM recipients r
        JOIN awards a ON a.recipient_id = r.id
        GROUP BY a.source
        ORDER BY a.source
    """)).fetchall()

    for row in result:
        pct_type = (row[2] / row[1] * 100) if row[1] > 0 else 0
        pct_naics = (row[3] / row[1] * 100) if row[1] > 0 else 0
        print(f"{row[0]}:")
        print(f"  Total: {row[1]:,}")
        print(f"  With business_type: {row[2]:,} ({pct_type:.1f}%)")
        print(f"  With naics_code: {row[3]:,} ({pct_naics:.1f}%)")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Enrich recipients with business types from PPP data")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without making changes")
    parser.add_argument("--stats-only", action="store_true", help="Only show current stats")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    try:
        if args.stats_only:
            show_stats(db)
            return

        print("Before enrichment:")
        show_stats(db)

        result1 = enrich_from_ppp(db, dry_run=args.dry_run)
        result2 = enrich_naics_only(db, dry_run=args.dry_run)

        if not args.dry_run:
            print("\nAfter enrichment:")
            show_stats(db)

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Business types updated: {result1['updated']:,}")
        print(f"NAICS codes updated: {result2['updated']:,}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
