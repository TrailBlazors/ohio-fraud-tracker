"""
Add performance indexes to speed up Red Flags queries.
Run this once after deployment.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine, SessionLocal


def add_indexes():
    """Add performance indexes for common queries."""
    
    indexes = [
        # Critical for top recipients query (GROUP BY recipient_id with SUM)
        ("ix_awards_recipient_amount", "CREATE INDEX IF NOT EXISTS ix_awards_recipient_amount ON awards(recipient_id, amount)"),
        
        # For flagged recipients query
        ("ix_fraud_flags_unresolved", "CREATE INDEX IF NOT EXISTS ix_fraud_flags_unresolved ON fraud_flags(is_resolved, recipient_id) WHERE is_resolved = 0"),
        
        # For sorting by severity
        ("ix_fraud_flags_severity", "CREATE INDEX IF NOT EXISTS ix_fraud_flags_severity ON fraud_flags(severity, created_at DESC)"),
        
        # Covering index for awards aggregation
        ("ix_awards_recipient_full", "CREATE INDEX IF NOT EXISTS ix_awards_recipient_full ON awards(recipient_id, id, amount)"),
        
        # For agency aggregation
        ("ix_awards_agency_amount", "CREATE INDEX IF NOT EXISTS ix_awards_agency_amount ON awards(agency_id, amount)"),
        
        # For source filtering
        ("ix_awards_source_amount", "CREATE INDEX IF NOT EXISTS ix_awards_source_amount ON awards(source, amount)"),
        
        # For date-based queries
        ("ix_awards_date_desc", "CREATE INDEX IF NOT EXISTS ix_awards_date_desc ON awards(award_date DESC)"),
    ]
    
    with engine.connect() as conn:
        for name, sql in indexes:
            try:
                print(f"Creating index: {name}...")
                conn.execute(text(sql))
                conn.commit()
                print(f"  ✓ {name} created")
            except Exception as e:
                print(f"  ⚠ {name}: {e}")
    
    print("\nAnalyzing tables for query optimization...")
    with engine.connect() as conn:
        try:
            conn.execute(text("ANALYZE"))
            conn.commit()
            print("  ✓ ANALYZE complete")
        except Exception as e:
            print(f"  ⚠ ANALYZE: {e}")


def warm_cache():
    """Pre-compute expensive stats and store in cache."""
    import json
    from datetime import datetime
    from sqlalchemy import func, desc
    from app.models import Award, Recipient, Agency, FraudFlag, CachedStats
    
    db = SessionLocal()
    
    try:
        print("\nWarming cache...")
        
        # 1. Top recipients
        print("  Computing top recipients...")
        top_results = db.execute(text("""
            SELECT 
                r.id, r.name, r.city, r.state, r.business_status,
                COUNT(a.id) as award_count,
                SUM(a.amount) as total_amount
            FROM recipients r
            INNER JOIN awards a ON a.recipient_id = r.id
            GROUP BY r.id
            ORDER BY total_amount DESC
            LIMIT 20
        """)).fetchall()
        
        items = []
        for i, row in enumerate(top_results, 1):
            items.append({
                "rank": i,
                "id": row.id,
                "name": row.name,
                "city": row.city,
                "state": row.state,
                "business_status": row.business_status,
                "award_count": row.award_count,
                "total_amount": float(row.total_amount) if row.total_amount else 0
            })
        
        cache_data = {"items": items, "count": len(items)}
        
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "top_recipients_20").first()
        if cached:
            cached.stat_json = json.dumps(cache_data)
            cached.updated_at = datetime.utcnow()
        else:
            db.add(CachedStats(stat_key="top_recipients_20", stat_value=20, stat_json=json.dumps(cache_data)))
        print("  ✓ Top recipients cached")
        
        # 2. Quick stats
        print("  Computing quick stats...")
        totals = db.query(
            func.count(Award.id).label("total_awards"),
            func.sum(Award.amount).label("total_amount")
        ).first()
        
        total_recipients = db.query(func.count(Recipient.id)).scalar() or 0
        total_flagged = db.query(func.count(FraudFlag.id)).filter(FraudFlag.is_resolved == False).scalar() or 0
        total_flags_ever = db.query(func.count(FraudFlag.id)).scalar() or 0
        
        stats = [
            ("total_awards", totals.total_awards or 0),
            ("total_amount", float(totals.total_amount or 0)),
            ("total_recipients", total_recipients),
            ("total_flagged", total_flagged),
            ("total_flags_ever", total_flags_ever),
        ]
        
        for key, value in stats:
            cached = db.query(CachedStats).filter(CachedStats.stat_key == key).first()
            if cached:
                cached.stat_value = value
                cached.updated_at = datetime.utcnow()
            else:
                db.add(CachedStats(stat_key=key, stat_value=value))
        print("  ✓ Quick stats cached")
        
        # 3. Awards by source
        print("  Computing awards by source...")
        source_query = db.query(
            Award.source,
            func.count(Award.id).label("count"),
            func.sum(Award.amount).label("total")
        ).group_by(Award.source).all()
        
        source_data = {
            row.source: {"count": row.count, "total": float(row.total or 0)}
            for row in source_query
        }
        
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "awards_by_source").first()
        if cached:
            cached.stat_json = json.dumps(source_data)
            cached.updated_at = datetime.utcnow()
        else:
            db.add(CachedStats(stat_key="awards_by_source", stat_value=len(source_data), stat_json=json.dumps(source_data)))
        print("  ✓ Awards by source cached")
        
        # 4. Top agencies
        print("  Computing top agencies...")
        agency_query = db.query(
            Agency.id, Agency.code, Agency.name,
            func.count(Award.id).label("total_awards"),
            func.sum(Award.amount).label("total_amount")
        ).join(Award, Award.agency_id == Agency.id)\
         .group_by(Agency.id)\
         .order_by(desc("total_amount"))\
         .limit(10).all()
        
        agency_data = [
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "total_awards": row.total_awards,
                "total_amount": float(row.total_amount or 0)
            }
            for row in agency_query
        ]
        
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "top_agencies").first()
        if cached:
            cached.stat_json = json.dumps(agency_data)
            cached.updated_at = datetime.utcnow()
        else:
            db.add(CachedStats(stat_key="top_agencies", stat_value=len(agency_data), stat_json=json.dumps(agency_data)))
        print("  ✓ Top agencies cached")
        
        db.commit()
        print("\n✓ Cache warming complete!")
        
    except Exception as e:
        db.rollback()
        print(f"\n✗ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Ohio Fraud Tracker - Performance Optimization")
    print("=" * 50)
    
    add_indexes()
    warm_cache()
    
    print("\n" + "=" * 50)
    print("Done! Red Flags pages should now load much faster.")
    print("=" * 50)
