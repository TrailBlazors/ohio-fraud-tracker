"""
Fix Neon schema issues - add sequences for auto-increment columns
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import SessionLocal, IS_POSTGRES

def fix_sequences():
    """Add sequences to tables that need auto-increment IDs"""
    
    if not IS_POSTGRES:
        print("Not connected to Postgres - skipping")
        return
    
    db = SessionLocal()
    
    # Tables that need SERIAL/sequence fix
    tables_to_fix = [
        "data_imports",
        "fraud_flags",
        "cached_stats",
    ]
    
    for table in tables_to_fix:
        try:
            # Check if sequence exists
            result = db.execute(text(f"""
                SELECT pg_get_serial_sequence('{table}', 'id')
            """)).scalar()
            
            if result:
                print(f"  ✓ {table} already has sequence: {result}")
            else:
                print(f"  Fixing {table}...")
                
                # Create sequence
                seq_name = f"{table}_id_seq"
                db.execute(text(f"""
                    CREATE SEQUENCE IF NOT EXISTS {seq_name}
                """))
                
                # Get max ID
                max_id = db.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar()
                
                # Set sequence to max + 1
                db.execute(text(f"""
                    SELECT setval('{seq_name}', {max_id + 1}, false)
                """))
                
                # Alter column to use sequence
                db.execute(text(f"""
                    ALTER TABLE {table} 
                    ALTER COLUMN id SET DEFAULT nextval('{seq_name}')
                """))
                
                # Set sequence ownership
                db.execute(text(f"""
                    ALTER SEQUENCE {seq_name} OWNED BY {table}.id
                """))
                
                db.commit()
                print(f"  ✓ Fixed {table}")
                
        except Exception as e:
            print(f"  ✗ Error fixing {table}: {e}")
            db.rollback()
    
    db.close()
    print("\nDone!")


if __name__ == "__main__":
    print("Fixing Neon sequences for auto-increment...\n")
    fix_sequences()
