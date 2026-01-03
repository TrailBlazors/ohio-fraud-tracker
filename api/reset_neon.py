"""
Reset Neon database - drops all tables to start fresh.

Run: python reset_neon.py
"""

import psycopg

NEON_URL = "postgresql://neondb_owner:npg_qa8C5pMKflvG@ep-green-fog-a8mwvkcw-pooler.eastus2.azure.neon.tech/ohio-fraud-tracker?sslmode=require"

def get_db_size(conn) -> float:
    """Get current database size in MB."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database())")
        size_bytes = cur.fetchone()[0]
        return size_bytes / (1024 * 1024)

def reset():
    print("🔌 Connecting to Neon...")
    conn = psycopg.connect(NEON_URL)
    
    # Check current size
    current_size = get_db_size(conn)
    print(f"📊 Current database size: {current_size:.2f} MB")
    
    print("🔍 Finding all tables...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        tables = [row[0] for row in cur.fetchall()]
    
    if not tables:
        print("✅ No tables found - database is already empty")
        conn.close()
        return
    
    print(f"📋 Found {len(tables)} tables: {', '.join(tables)}")
    
    print("🗑️  Dropping all tables...")
    with conn.cursor() as cur:
        # Drop all tables with CASCADE
        for table in tables:
            try:
                cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
                print(f"   ✅ Dropped: {table}")
            except Exception as e:
                print(f"   ⚠️  Error dropping {table}: {e}")
    
    conn.commit()
    
    # Run VACUUM to reclaim space (note: may not immediately reflect in size)
    print("🧹 Running VACUUM to reclaim space...")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("VACUUM")
    
    # Check size after
    final_size = get_db_size(conn)
    print(f"📊 Database size after reset: {final_size:.2f} MB")
    
    conn.close()
    
    print()
    print("✅ Database reset complete!")

if __name__ == "__main__":
    print("=" * 50)
    print("🗑️  NEON DATABASE RESET")
    print("=" * 50)
    reset()
