"""
Add performance indexes to the database.
Run this once to significantly speed up queries.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine, SessionLocal

def add_indexes():
    """Add missing performance indexes"""
    
    indexes = [
        # Critical for text search on recipients
        ("idx_recipients_name_lower", "CREATE INDEX IF NOT EXISTS idx_recipients_name_lower ON recipients(name COLLATE NOCASE)"),
        ("idx_recipients_city_lower", "CREATE INDEX IF NOT EXISTS idx_recipients_city_lower ON recipients(city COLLATE NOCASE)"),
        
        # Critical for JOINs
        ("idx_awards_recipient_id", "CREATE INDEX IF NOT EXISTS idx_awards_recipient_id ON awards(recipient_id)"),
        ("idx_awards_agency_id", "CREATE INDEX IF NOT EXISTS idx_awards_agency_id ON awards(agency_id)"),
        
        # For filtering and sorting
        ("idx_awards_source", "CREATE INDEX IF NOT EXISTS idx_awards_source ON awards(source)"),
        ("idx_awards_amount_desc", "CREATE INDEX IF NOT EXISTS idx_awards_amount_desc ON awards(amount DESC)"),
        ("idx_awards_date_desc", "CREATE INDEX IF NOT EXISTS idx_awards_date_desc ON awards(award_date DESC)"),
        ("idx_awards_type", "CREATE INDEX IF NOT EXISTS idx_awards_type ON awards(award_type)"),
        
        # Composite indexes for common queries
        ("idx_awards_source_amount", "CREATE INDEX IF NOT EXISTS idx_awards_source_amount ON awards(source, amount DESC)"),
        ("idx_awards_recipient_amount", "CREATE INDEX IF NOT EXISTS idx_awards_recipient_amount ON awards(recipient_id, amount DESC)"),
        
        # For flagged page
        ("idx_fraud_flags_resolved", "CREATE INDEX IF NOT EXISTS idx_fraud_flags_resolved ON fraud_flags(is_resolved)"),
        ("idx_fraud_flags_recipient", "CREATE INDEX IF NOT EXISTS idx_fraud_flags_recipient ON fraud_flags(recipient_id)"),
        ("idx_fraud_flags_severity", "CREATE INDEX IF NOT EXISTS idx_fraud_flags_severity ON fraud_flags(severity DESC)"),
        
        # For cached stats
        ("idx_cached_stats_key", "CREATE INDEX IF NOT EXISTS idx_cached_stats_key ON cached_stats(stat_key)"),
    ]
    
    with engine.connect() as conn:
        for name, sql in indexes:
            try:
                print(f"Creating index: {name}...")
                conn.execute(text(sql))
                conn.commit()
                print(f"  ✓ Created {name}")
            except Exception as e:
                print(f"  ⚠ {name}: {e}")
    
    print("\n✓ Index creation complete!")


def analyze_tables():
    """Run ANALYZE to update query planner statistics"""
    print("\nAnalyzing tables for query optimization...")
    
    with engine.connect() as conn:
        conn.execute(text("ANALYZE"))
        conn.commit()
    
    print("✓ ANALYZE complete!")


def check_table_sizes():
    """Show table sizes"""
    print("\nTable sizes:")
    
    tables = ["awards", "recipients", "agencies", "fraud_flags", "cached_stats"]
    
    with engine.connect() as conn:
        for table in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                print(f"  {table}: {result:,} rows")
            except:
                print(f"  {table}: (not found)")


def refresh_cached_stats():
    """Refresh the cached stats table"""
    import json
    from datetime import datetime
    
    print("\nRefreshing cached stats...")
    
    db = SessionLocal()
    try:
        with engine.connect() as conn:
            # Total awards
            total_awards = conn.execute(text("SELECT COUNT(*) FROM awards")).scalar() or 0
            total_amount = conn.execute(text("SELECT SUM(amount) FROM awards")).scalar() or 0
            total_recipients = conn.execute(text("SELECT COUNT(*) FROM recipients")).scalar() or 0
            total_flagged = conn.execute(text("SELECT COUNT(*) FROM fraud_flags WHERE is_resolved = 0")).scalar() or 0
            total_flags_ever = conn.execute(text("SELECT COUNT(*) FROM fraud_flags")).scalar() or 0
            
            # Awards by source
            source_rows = conn.execute(text("""
                SELECT source, COUNT(*) as count, SUM(amount) as total 
                FROM awards GROUP BY source
            """)).fetchall()
            awards_by_source = {row[0]: {"count": row[1], "total": float(row[2] or 0)} for row in source_rows}
            
            # Awards by type
            type_rows = conn.execute(text("""
                SELECT award_type, COUNT(*) as count, SUM(amount) as total 
                FROM awards GROUP BY award_type
            """)).fetchall()
            awards_by_type = {row[0]: {"count": row[1], "total": float(row[2] or 0)} for row in type_rows}
            
            # Top agencies
            agency_rows = conn.execute(text("""
                SELECT a.id, a.code, a.name, COUNT(aw.id) as total_awards, SUM(aw.amount) as total_amount
                FROM agencies a
                JOIN awards aw ON aw.agency_id = a.id
                GROUP BY a.id
                ORDER BY total_amount DESC
                LIMIT 10
            """)).fetchall()
            top_agencies = [
                {"id": r[0], "code": r[1], "name": r[2], "total_awards": r[3], "total_amount": float(r[4] or 0)}
                for r in agency_rows
            ]
            
            # Insert/update cached stats
            stats = [
                ("total_awards", total_awards, None),
                ("total_amount", total_amount, None),
                ("total_recipients", total_recipients, None),
                ("total_flagged", total_flagged, None),
                ("total_flags_ever", total_flags_ever, None),
                ("awards_by_source", 0, json.dumps(awards_by_source)),
                ("awards_by_type", 0, json.dumps(awards_by_type)),
                ("top_agencies", 0, json.dumps(top_agencies)),
            ]
            
            for key, value, json_val in stats:
                conn.execute(text("""
                    INSERT INTO cached_stats (stat_key, stat_value, stat_json, updated_at)
                    VALUES (:key, :value, :json, :now)
                    ON CONFLICT(stat_key) DO UPDATE SET 
                        stat_value = :value, 
                        stat_json = :json,
                        updated_at = :now
                """), {"key": key, "value": value, "json": json_val, "now": datetime.utcnow()})
            
            conn.commit()
            
            print(f"  ✓ total_awards: {total_awards:,}")
            print(f"  ✓ total_amount: ${total_amount:,.0f}")
            print(f"  ✓ total_recipients: {total_recipients:,}")
            print(f"  ✓ total_flagged: {total_flagged:,}")
            print(f"  ✓ awards_by_source: {len(awards_by_source)} sources")
            print(f"  ✓ awards_by_type: {len(awards_by_type)} types")
            print(f"  ✓ top_agencies: {len(top_agencies)} agencies")
            
    finally:
        db.close()
    
    print("✓ Cached stats refreshed!")


if __name__ == "__main__":
    print("=" * 50)
    print("Database Performance Optimization")
    print("=" * 50)
    
    check_table_sizes()
    add_indexes()
    analyze_tables()
    refresh_cached_stats()
    
    print("\n" + "=" * 50)
    print("Done! Restart the API server to see improvements.")
    print("=" * 50)
