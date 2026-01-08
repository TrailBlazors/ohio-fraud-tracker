"""
Analyze duplicate records in the database.
"""

from app.database import SessionLocal, init_db
from sqlalchemy import text

def main():
    init_db()
    db = SessionLocal()

    print("DUPLICATE ANALYSIS")
    print("=" * 80)

    # Look at a specific example
    print("\nExample: BUCKEYE POWER SALES CO INC on 2023-12-21")
    print("-" * 80)

    result = db.execute(text("""
        SELECT a.id, a.amount, a.description, a.award_type, ag.name as agency
        FROM awards a
        JOIN recipients r ON a.recipient_id = r.id
        LEFT JOIN agencies ag ON a.agency_id = ag.id
        WHERE a.source = 'ohio_checkbook'
        AND r.name = 'BUCKEYE POWER SALES CO INC'
        AND a.award_date = '2023-12-21'
        LIMIT 15
    """)).fetchall()

    for r in result:
        desc = (r[2] or "")[:50]
        agency = (r[4] or "")[:30]
        print(f"ID:{r[0]:8} | ${r[1]:>12,.2f} | {r[3]:15} | {agency:30} | {desc}")

    # Check if descriptions are different
    print("\n" + "=" * 80)
    print("Are duplicates actually different transactions?")
    print("-" * 80)

    result2 = db.execute(text("""
        SELECT
            COUNT(*) as total_dupe_groups,
            SUM(CASE WHEN unique_desc = cnt THEN 1 ELSE 0 END) as all_different_desc,
            SUM(CASE WHEN unique_desc = 1 THEN 1 ELSE 0 END) as all_same_desc
        FROM (
            SELECT
                recipient_id, amount, award_date,
                COUNT(*) as cnt,
                COUNT(DISTINCT COALESCE(description, '')) as unique_desc
            FROM awards
            WHERE source = 'ohio_checkbook'
            GROUP BY recipient_id, amount, award_date
            HAVING COUNT(*) > 1
        ) t
    """)).fetchone()

    print(f"Total duplicate groups: {result2[0]:,}")
    print(f"Groups where ALL descriptions are different: {result2[1]:,}")
    print(f"Groups where ALL descriptions are same: {result2[2]:,}")

    # Sample where descriptions ARE different (legitimate multiple payments)
    print("\n" + "=" * 80)
    print("Sample: Same recipient/amount/date but DIFFERENT descriptions (LEGITIMATE)")
    print("-" * 80)

    result3 = db.execute(text("""
        SELECT r.name, a.amount, a.award_date, a.description
        FROM awards a
        JOIN recipients r ON a.recipient_id = r.id
        WHERE a.source = 'ohio_checkbook'
        AND (a.recipient_id, a.amount, a.award_date) IN (
            SELECT recipient_id, amount, award_date
            FROM awards
            WHERE source = 'ohio_checkbook'
            GROUP BY recipient_id, amount, award_date
            HAVING COUNT(*) > 1 AND COUNT(DISTINCT COALESCE(description, '')) = COUNT(*)
            LIMIT 1
        )
        LIMIT 5
    """)).fetchall()

    for r in result3:
        print(f"{r[0][:40]:40} | ${r[1]:>10,.2f} | {r[2]} | {(r[3] or '')[:40]}")

    # Sample where descriptions ARE same (potential true duplicates)
    print("\n" + "=" * 80)
    print("Sample: Same recipient/amount/date AND same description (POTENTIAL DUPLICATES)")
    print("-" * 80)

    result4 = db.execute(text("""
        SELECT r.name, a.amount, a.award_date, a.description, COUNT(*) as cnt
        FROM awards a
        JOIN recipients r ON a.recipient_id = r.id
        WHERE a.source = 'ohio_checkbook'
        GROUP BY r.name, a.recipient_id, a.amount, a.award_date, a.description
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 10
    """)).fetchall()

    for r in result4:
        print(f"{r[0][:35]:35} | ${r[1]:>10,.2f} | {r[2]} | x{r[4]} | {(r[3] or '')[:30]}")

    db.close()


if __name__ == "__main__":
    main()
