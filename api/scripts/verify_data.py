"""
Data Verification Script

Compares our aggregated data against official sources to ensure accuracy.
"""

import json
import urllib.request
import urllib.error
from decimal import Decimal
from app.database import SessionLocal, init_db
from app.models import Award, Recipient, Agency
from sqlalchemy import func, text

API_BASE = "https://ohiofraud.org"


def verify_internal_consistency(db):
    """Check that our aggregations match the raw data."""
    print("\n" + "="*60)
    print("INTERNAL CONSISTENCY CHECKS")
    print("="*60)

    # 1. Total awards count
    live_count = db.query(func.count(Award.id)).scalar() or 0

    # 2. Total amount
    live_amount = db.query(func.sum(Award.amount)).scalar() or 0

    # 3. By source breakdown
    source_query = db.query(
        Award.source,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).group_by(Award.source).all()

    source_counts = {row.source: row.count for row in source_query}
    source_totals = {row.source: float(row.total or 0) for row in source_query}

    # Get cached values
    with urllib.request.urlopen(f"{API_BASE}/api/stats/quick") as resp:
        cached = json.loads(resp.read().decode())

    print(f"\n1. Award Counts:")
    print(f"   Live DB count:   {live_count:,}")
    print(f"   Cached count:    {cached['total_awards']:,}")
    print(f"   Match: {'OK' if live_count == cached['total_awards'] else 'MISMATCH!'}")

    print(f"\n2. Total Amount:")
    print(f"   Live DB sum:     ${live_amount:,.2f}")
    print(f"   Cached sum:      ${cached['total_amount']:,.2f}")
    diff = abs(live_amount - cached['total_amount'])
    pct = (diff / live_amount * 100) if live_amount > 0 else 0
    print(f"   Difference:      ${diff:,.2f} ({pct:.4f}%)")
    print(f"   Match: {'OK' if pct < 0.01 else 'MISMATCH (>0.01%)!'}")

    print(f"\n3. Sum of Sources = Total:")
    source_sum = sum(source_totals.values())
    print(f"   Sum of sources:  ${source_sum:,.2f}")
    print(f"   Total amount:    ${float(live_amount):,.2f}")
    diff = abs(source_sum - float(live_amount))
    print(f"   Match: {'OK' if diff < 1 else 'MISMATCH!'}")

    print(f"\n4. By Source Breakdown:")
    for source, count in source_counts.items():
        print(f"   {source}: {count:,} records, ${source_totals[source]:,.2f}")

    return {
        "live_count": live_count,
        "cached_count": cached['total_awards'],
        "live_amount": float(live_amount),
        "cached_amount": cached['total_amount'],
        "by_source": source_totals
    }


def verify_against_usaspending():
    """Compare our USAspending data against their official API."""
    print("\n" + "="*60)
    print("USASPENDING.GOV COMPARISON")
    print("="*60)

    # Get our data
    with urllib.request.urlopen(f"{API_BASE}/api/stats/data-status") as resp:
        our_data = json.loads(resp.read().decode())

    usa_source = next((s for s in our_data['sources'] if s['key'] == 'usaspending'), None)
    if not usa_source:
        print("No USAspending data found in our database")
        return

    our_count = usa_source['record_count']
    our_amount = usa_source['total_amount']

    print(f"\nOur USAspending data:")
    print(f"   Records: {our_count:,}")
    print(f"   Amount:  ${our_amount:,.2f}")

    # Query USAspending API for Ohio totals
    # Note: Their API returns all-time data by default
    try:
        req_data = json.dumps({
            "filters": {
                "place_of_performance_locations": [{"country": "USA", "state": "OH"}],
                "award_type_codes": ["02", "03", "04", "05", "06", "07", "08", "09", "10", "11"]
            }
        }).encode()
        req = urllib.request.Request(
            "https://api.usaspending.gov/api/v2/search/spending_by_award_count/",
            data=req_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            their_data = json.loads(resp.read().decode())

        print(f"\nUSAspending.gov official counts (all time):")
        for award_type, count in their_data.get('results', {}).items():
            if count > 0:
                print(f"   {award_type}: {count:,}")

        total_their = sum(their_data.get('results', {}).values())
        print(f"   TOTAL: {total_their:,}")

        print(f"\nComparison:")
        print(f"   We imported {our_count:,} of their {total_their:,} records")
        if total_their > 0:
            pct = our_count / total_their * 100
            print(f"   Coverage: {pct:.1f}%")

        print(f"\n   Note: We focus on grants/loans/contracts, not direct payments.")
        print(f"   Direct payments alone account for ~{their_data.get('results', {}).get('direct_payments', 0):,} records.")

    except Exception as e:
        print(f"   Error querying USAspending API: {e}")


def verify_ppp_data():
    """Verify PPP loan data against known totals."""
    print("\n" + "="*60)
    print("SBA PPP LOAN VERIFICATION")
    print("="*60)

    # Get our data
    with urllib.request.urlopen(f"{API_BASE}/api/stats/data-status") as resp:
        our_data = json.loads(resp.read().decode())

    ppp_source = next((s for s in our_data['sources'] if s['key'] == 'sba_ppp'), None)
    if not ppp_source:
        print("No PPP data found in our database")
        return

    our_count = ppp_source['record_count']
    our_amount = ppp_source['total_amount']

    print(f"\nOur PPP data:")
    print(f"   Loans: {our_count:,}")
    print(f"   Amount: ${our_amount:,.2f}")

    # Known Ohio PPP totals (from SBA reports)
    # Source: https://www.sba.gov/funding-programs/loans/covid-19-relief-options/paycheck-protection-program
    # Ohio received approximately 350,000+ PPP loans totaling ~$27B
    print(f"\nKnown PPP totals for Ohio (approximate):")
    print(f"   Expected loans: ~350,000+")
    print(f"   Expected amount: ~$27-28 billion")

    print(f"\nComparison:")
    print(f"   Our count ({our_count:,}) vs expected (~350,000): {'OK - Close' if 340000 < our_count < 360000 else 'REVIEW'}")
    print(f"   Our amount (${our_amount/1e9:.2f}B) vs expected (~$27B): {'OK - Close' if 25e9 < our_amount < 30e9 else 'REVIEW'}")


def check_data_quality(db):
    """Check for common data quality issues."""
    print("\n" + "="*60)
    print("DATA QUALITY CHECKS")
    print("="*60)

    # 1. Null amounts
    null_amounts = db.query(func.count(Award.id)).filter(Award.amount.is_(None)).scalar() or 0
    print(f"\n1. Awards with NULL amount: {null_amounts:,}")

    # 2. Zero amounts
    zero_amounts = db.query(func.count(Award.id)).filter(Award.amount == 0).scalar() or 0
    print(f"2. Awards with $0 amount: {zero_amounts:,}")

    # 3. Negative amounts
    negative_amounts = db.query(func.count(Award.id)).filter(Award.amount < 0).scalar() or 0
    print(f"3. Awards with negative amount: {negative_amounts:,}")

    # 4. Extremely large amounts (>$1B single award)
    huge_amounts = db.query(func.count(Award.id)).filter(Award.amount > 1_000_000_000).scalar() or 0
    print(f"4. Awards > $1 billion: {huge_amounts:,}")

    # 5. Recipients without names
    null_names = db.query(func.count(Recipient.id)).filter(
        (Recipient.name.is_(None)) | (Recipient.name == "")
    ).scalar() or 0
    print(f"5. Recipients without names: {null_names:,}")

    # 6. Orphaned awards (no recipient)
    orphaned = db.query(func.count(Award.id)).filter(Award.recipient_id.is_(None)).scalar() or 0
    print(f"6. Awards without recipient: {orphaned:,}")

    # 7. Duplicate check - same recipient, amount, date
    print(f"\n7. Checking for potential duplicates...")
    dupe_query = text("""
        SELECT COUNT(*) FROM (
            SELECT recipient_id, amount, award_date, COUNT(*) as cnt
            FROM awards
            WHERE recipient_id IS NOT NULL AND amount IS NOT NULL AND award_date IS NOT NULL
            GROUP BY recipient_id, amount, award_date
            HAVING COUNT(*) > 1
        ) dupes
    """)
    try:
        dupe_count = db.execute(dupe_query).scalar() or 0
        print(f"   Potential duplicate groups: {dupe_count:,}")
    except Exception as e:
        print(f"   Could not check duplicates: {e}")


def spot_check_records(db):
    """Spot check a few specific records."""
    print("\n" + "="*60)
    print("SPOT CHECK - LARGEST AWARDS")
    print("="*60)

    # Get top 5 largest awards
    top_awards = db.query(Award, Recipient).join(
        Recipient, Award.recipient_id == Recipient.id
    ).order_by(Award.amount.desc()).limit(5).all()

    print("\nTop 5 largest awards:")
    for i, (award, recipient) in enumerate(top_awards, 1):
        print(f"\n{i}. ${award.amount:,.2f}")
        print(f"   Recipient: {recipient.name}")
        print(f"   Source: {award.source}")
        print(f"   Date: {award.award_date}")
        print(f"   Description: {(award.description or '')[:100]}...")


def main():
    print("="*60)
    print("OHIO FRAUD TRACKER - DATA VERIFICATION REPORT")
    print("="*60)

    init_db()
    db = SessionLocal()

    try:
        # Run all checks
        verify_internal_consistency(db)
        verify_against_usaspending()
        verify_ppp_data()
        check_data_quality(db)
        spot_check_records(db)

        print("\n" + "="*60)
        print("VERIFICATION COMPLETE")
        print("="*60)

    finally:
        db.close()


if __name__ == "__main__":
    main()
