"""
Refresh Cached Stats

Pre-computes dashboard statistics and stores them in cached_stats table.
Run this after data imports or on a schedule.

Usage:
    python -m scripts.refresh_stats
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func
from app.database import get_db_context, init_db
from app.models import Award, Recipient, Agency, FraudFlag, CachedStats


def refresh_stats():
    """Compute and cache all dashboard stats."""
    print("=" * 60)
    print("REFRESHING CACHED STATS")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    init_db()
    
    with get_db_context() as db:
        stats = {}
        
        # Basic counts
        print("\nComputing totals...")
        stats["total_awards"] = db.query(func.count(Award.id)).scalar() or 0
        stats["total_amount"] = float(db.query(func.sum(Award.amount)).scalar() or 0)
        stats["total_recipients"] = db.query(func.count(Recipient.id)).scalar() or 0
        stats["total_flagged"] = db.query(func.count(FraudFlag.id)).filter(
            FraudFlag.is_resolved == False
        ).scalar() or 0
        stats["total_flags_ever"] = db.query(func.count(FraudFlag.id)).scalar() or 0
        
        print(f"  Total awards: {stats['total_awards']:,}")
        print(f"  Total amount: ${stats['total_amount']:,.0f}")
        print(f"  Total recipients: {stats['total_recipients']:,}")
        
        # Awards by source
        print("\nComputing by source...")
        source_query = db.query(
            Award.source,
            func.count(Award.id).label("count"),
            func.sum(Award.amount).label("total")
        ).group_by(Award.source).all()
        
        awards_by_source = {
            row.source: {"count": row.count, "total": float(row.total or 0)}
            for row in source_query
        }
        stats["awards_by_source"] = json.dumps(awards_by_source)
        
        for source, data in awards_by_source.items():
            print(f"  {source}: {data['count']:,} awards, ${data['total']:,.0f}")
        
        # Awards by type
        print("\nComputing by type...")
        type_query = db.query(
            Award.award_type,
            func.count(Award.id).label("count"),
            func.sum(Award.amount).label("total")
        ).group_by(Award.award_type).all()
        
        awards_by_type = {
            row.award_type: {"count": row.count, "total": float(row.total or 0)}
            for row in type_query
        }
        stats["awards_by_type"] = json.dumps(awards_by_type)
        
        # Top agencies
        print("\nComputing top agencies...")
        agency_query = db.query(
            Agency.id,
            Agency.code,
            Agency.name,
            func.count(Award.id).label("total_awards"),
            func.sum(Award.amount).label("total_amount")
        ).join(Award, Award.agency_id == Agency.id)\
         .group_by(Agency.id)\
         .order_by(func.sum(Award.amount).desc())\
         .limit(10).all()
        
        top_agencies = [
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "total_awards": row.total_awards,
                "total_amount": float(row.total_amount or 0)
            }
            for row in agency_query
        ]
        stats["top_agencies"] = json.dumps(top_agencies)
        
        for agency in top_agencies[:5]:
            print(f"  {agency['code']}: ${agency['total_amount']:,.0f}")
        
        # Save to database
        print("\nSaving to cache...")
        for key, value in stats.items():
            existing = db.query(CachedStats).filter(CachedStats.stat_key == key).first()
            
            if isinstance(value, str):  # JSON
                if existing:
                    existing.stat_json = value
                    existing.stat_value = 0
                    existing.updated_at = datetime.utcnow()
                else:
                    db.add(CachedStats(stat_key=key, stat_value=0, stat_json=value))
            else:  # Numeric
                if existing:
                    existing.stat_value = value
                    existing.stat_json = None
                    existing.updated_at = datetime.utcnow()
                else:
                    db.add(CachedStats(stat_key=key, stat_value=value))
        
        db.commit()
        print(f"\n✓ Cached {len(stats)} stats")
        print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    refresh_stats()
