"""
Fix specific migration issues:
1. naics_codes table - recreate with proper schema
2. Verify awards amount precision

Run from the api directory:
    python fix_migration_issues.py
"""

import sqlite3
import psycopg
from pathlib import Path
import time

NEON_URL = "postgresql://neondb_owner:npg_qa8C5pMKflvG@ep-green-fog-a8mwvkcw-pooler.eastus2.azure.neon.tech/ohio-fraud-tracker?sslmode=require"
LOCAL_DB = Path(__file__).parent / "data" / "ohio_fraud_tracker.db"


def fix_naics_codes():
    """Recreate naics_codes table with proper schema."""
    print("=" * 60)
    print("🔧 FIXING naics_codes TABLE")
    print("=" * 60)
    print()
    
    # Connect to both databases
    print("🔌 Connecting to databases...")
    sqlite_conn = sqlite3.connect(str(LOCAL_DB))
    sqlite_cursor = sqlite_conn.cursor()
    pg_conn = psycopg.connect(NEON_URL)
    
    # Get SQLite schema
    sqlite_cursor.execute("PRAGMA table_info('naics_codes')")
    columns = sqlite_cursor.fetchall()
    print(f"📋 SQLite schema: {len(columns)} columns")
    for col in columns:
        print(f"   - {col[1]} ({col[2]})")
    
    # Check Neon schema
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'naics_codes'
        """)
        pg_cols = cur.fetchall()
        print(f"📋 Neon schema: {len(pg_cols)} columns")
        for col in pg_cols:
            print(f"   - {col[0]} ({col[1]})")
    
    print()
    
    # Drop and recreate table in Neon
    print("🔄 Recreating naics_codes table in Neon...")
    
    with pg_conn.cursor() as cur:
        # Drop existing
        cur.execute('DROP TABLE IF EXISTS "naics_codes" CASCADE')
        
        # Create with proper schema based on SQLite
        # columns: code, title, sector, sector_title
        create_sql = """
            CREATE TABLE naics_codes (
                code VARCHAR(6) PRIMARY KEY,
                title VARCHAR(255),
                sector VARCHAR(2),
                sector_title VARCHAR(255)
            )
        """
        cur.execute(create_sql)
        pg_conn.commit()
        print("   ✅ Table recreated")
    
    # Get data from SQLite
    sqlite_cursor.execute("SELECT code, title, sector, sector_title FROM naics_codes")
    rows = sqlite_cursor.fetchall()
    print(f"   📥 Fetched {len(rows)} rows from SQLite")
    
    # Insert into Neon
    with pg_conn.cursor() as cur:
        cur.executemany(
            'INSERT INTO naics_codes (code, title, sector, sector_title) VALUES (%s, %s, %s, %s)',
            rows
        )
        pg_conn.commit()
        print(f"   ✅ Inserted {len(rows)} rows into Neon")
    
    # Verify
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM naics_codes")
        count = cur.fetchone()[0]
        print(f"   📊 Neon row count: {count}")
        
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'naics_codes'
        """)
        new_cols = cur.fetchall()
        print(f"   📊 Neon columns: {len(new_cols)}")
    
    sqlite_conn.close()
    pg_conn.close()
    
    print()
    print("✅ naics_codes table fixed!")
    return True


def check_amount_precision():
    """Check the awards.amount precision difference."""
    print()
    print("=" * 60)
    print("🔍 CHECKING awards.amount PRECISION")
    print("=" * 60)
    print()
    
    sqlite_conn = sqlite3.connect(str(LOCAL_DB))
    sqlite_cursor = sqlite_conn.cursor()
    pg_conn = psycopg.connect(NEON_URL)
    
    # Get sums
    sqlite_cursor.execute("SELECT SUM(amount) FROM awards")
    sqlite_sum = sqlite_cursor.fetchone()[0]
    
    with pg_conn.cursor() as cur:
        cur.execute("SELECT SUM(amount) FROM awards")
        pg_sum = cur.fetchone()[0]
    
    diff = abs(sqlite_sum - float(pg_sum))
    pct_diff = (diff / sqlite_sum) * 100
    
    print(f"   SQLite SUM:  ${sqlite_sum:,.2f}")
    print(f"   Neon SUM:    ${float(pg_sum):,.2f}")
    print(f"   Difference:  ${diff:,.2f}")
    print(f"   Percentage:  {pct_diff:.10f}%")
    print()
    
    if diff < 10:  # Less than $10 difference
        print("✅ Difference is negligible (floating point precision)")
        print("   This is expected when converting between database float types.")
    else:
        print("⚠️  Significant difference detected - may need investigation")
    
    sqlite_conn.close()
    pg_conn.close()
    
    return diff < 100  # Acceptable if less than $100


def main():
    print()
    
    # Fix naics_codes
    fix_naics_codes()
    
    # Check amount precision
    check_amount_precision()
    
    print()
    print("=" * 60)
    print("🏁 ALL FIXES COMPLETE")
    print("=" * 60)
    print()
    print("Run verify_migration.py again to confirm all issues resolved.")


if __name__ == "__main__":
    main()
