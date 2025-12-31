"""
Add performance indexes for awards queries.

Run this once to speed up the grants/awards pages.

Usage:
    python -m scripts.add_indexes
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import engine


def add_indexes():
    """Add indexes to speed up common queries."""
    
    indexes = [
        # Speed up ORDER BY amount
        "CREATE INDEX IF NOT EXISTS ix_awards_amount ON awards (amount)",
        
        # Speed up ORDER BY award_date
        "CREATE INDEX IF NOT EXISTS ix_awards_date ON awards (award_date)",
        
        # Speed up source filtering + amount sort (grants page)
        "CREATE INDEX IF NOT EXISTS ix_awards_source_amount ON awards (source, amount)",
        
        # Speed up recipient joins (may already exist)
        "CREATE INDEX IF NOT EXISTS ix_awards_recipient_id ON awards (recipient_id)",
        
        # Speed up agency joins  
        "CREATE INDEX IF NOT EXISTS ix_awards_agency_id ON awards (agency_id)",
        
        # Composite index for common query pattern
        "CREATE INDEX IF NOT EXISTS ix_awards_source_date ON awards (source, award_date)",
    ]
    
    print("Adding performance indexes...")
    
    with engine.connect() as conn:
        for idx_sql in indexes:
            try:
                conn.execute(text(idx_sql))
                idx_name = idx_sql.split("INDEX IF NOT EXISTS ")[1].split(" ON")[0]
                print(f"  ✓ {idx_name}")
            except Exception as e:
                print(f"  ✗ Error: {e}")
        conn.commit()
    
    print("\nDone! Restart the API to see improvements.")


if __name__ == "__main__":
    add_indexes()
