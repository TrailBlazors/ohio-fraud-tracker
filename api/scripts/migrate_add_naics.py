"""
Database Migration: Add NAICS support

Adds:
1. naics_code and business_type columns to recipients table
2. naics_codes lookup table

Usage:
    python -m scripts.migrate_add_naics
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import get_db_context, engine, init_db
from app.models import Base, NaicsCode


def migrate():
    print("=" * 60)
    print("Migration: Add NAICS Support")
    print("=" * 60)
    
    with get_db_context() as db:
        # Check if naics_code column exists in recipients
        try:
            db.execute(text("SELECT naics_code FROM recipients LIMIT 1"))
            print("✓ naics_code column already exists in recipients")
        except Exception:
            print("Adding naics_code column to recipients...")
            db.execute(text("ALTER TABLE recipients ADD COLUMN naics_code VARCHAR(6)"))
            db.commit()
            print("✓ Added naics_code column")
        
        # Check if business_type column exists
        try:
            db.execute(text("SELECT business_type FROM recipients LIMIT 1"))
            print("✓ business_type column already exists in recipients")
        except Exception:
            print("Adding business_type column to recipients...")
            db.execute(text("ALTER TABLE recipients ADD COLUMN business_type VARCHAR(100)"))
            db.commit()
            print("✓ Added business_type column")
        
        # Create NAICS index if it doesn't exist
        try:
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_recipients_naics ON recipients(naics_code)"))
            db.commit()
            print("✓ Created naics_code index")
        except Exception as e:
            print(f"Index creation note: {e}")
    
    # Create naics_codes table
    print("\nCreating naics_codes table...")
    try:
        NaicsCode.__table__.create(engine, checkfirst=True)
        print("✓ naics_codes table ready")
    except Exception as e:
        print(f"Table creation note: {e}")
    
    print("\n✓ Migration complete!")
    print("\nNext steps:")
    print("  1. Run: python -m scripts.import_naics")
    print("  2. Re-import PPP data to populate NAICS codes: python -m scripts.import_sba_ppp --clear")


if __name__ == "__main__":
    migrate()
