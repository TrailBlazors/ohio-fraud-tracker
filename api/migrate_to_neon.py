"""
Migrate SQLite database to Neon PostgreSQL.

Run from the api directory:
    python migrate_to_neon.py
"""

import sqlite3
import psycopg
from pathlib import Path
import time

# =============================================================================
# CONFIGURATION
# =============================================================================

# Neon connection string
NEON_URL = "postgresql://neondb_owner:npg_qa8C5pMKflvG@ep-green-fog-a8mwvkcw-pooler.eastus2.azure.neon.tech/ohio-fraud-tracker?sslmode=require"

# Local SQLite database
LOCAL_DB = Path(__file__).parent / "data" / "ohio_fraud_tracker.db"

# Batch size for inserts (adjust if memory issues)
BATCH_SIZE = 1000

# How often to check storage (every N tables)
STORAGE_CHECK_INTERVAL = 5

# =============================================================================
# TYPE MAPPING: SQLite → PostgreSQL
# =============================================================================

SQLITE_TO_PG_TYPES = {
    "INTEGER": "BIGINT",
    "TEXT": "TEXT",
    "REAL": "DOUBLE PRECISION",
    "BLOB": "BYTEA",
    "NUMERIC": "NUMERIC",
    "BOOLEAN": "BOOLEAN",
    "DATETIME": "TIMESTAMP",
    "DATE": "DATE",
    "VARCHAR": "VARCHAR",
}

def convert_type(sqlite_type: str) -> str:
    """Convert SQLite type to PostgreSQL type."""
    sqlite_type = sqlite_type.upper() if sqlite_type else "TEXT"
    
    # Handle VARCHAR(n)
    if "VARCHAR" in sqlite_type:
        return sqlite_type
    
    # Handle specific types
    for sqlite_t, pg_t in SQLITE_TO_PG_TYPES.items():
        if sqlite_t in sqlite_type:
            return pg_t
    
    return "TEXT"

# =============================================================================
# STORAGE MONITORING
# =============================================================================

def get_storage_info(conn) -> dict:
    """Get current database storage usage."""
    with conn.cursor() as cur:
        # Get database size
        cur.execute("SELECT pg_database_size(current_database())")
        size_bytes = cur.fetchone()[0]
        size_mb = size_bytes / (1024 * 1024)
        size_gb = size_bytes / (1024 * 1024 * 1024)
        
    return {
        "size_mb": size_mb,
        "size_gb": size_gb,
    }

def print_storage_status(conn, prefix=""):
    """Print current storage status."""
    info = get_storage_info(conn)
    
    if info["size_gb"] >= 1:
        size_str = f"{info['size_gb']:.2f} GB"
    else:
        size_str = f"{info['size_mb']:.1f} MB"
    
    print(f"{prefix}💾 Storage used: {size_str}")

# =============================================================================
# MIGRATION FUNCTIONS
# =============================================================================

def get_sqlite_tables(cursor) -> list:
    """Get all table names from SQLite."""
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    return [row[0] for row in cursor.fetchall()]


def get_table_schema(cursor, table_name: str) -> list:
    """Get column info for a table."""
    cursor.execute(f"PRAGMA table_info('{table_name}')")
    return cursor.fetchall()  # (cid, name, type, notnull, default, pk)


def create_pg_table(pg_cursor, table_name: str, columns: list):
    """Create PostgreSQL table from SQLite schema."""
    
    col_defs = []
    pk_cols = []
    
    for col in columns:
        cid, name, col_type, notnull, default, pk = col
        
        pg_type = convert_type(col_type)
        
        # Build column definition
        col_def = f'"{name}" {pg_type}'
        
        if notnull:
            col_def += " NOT NULL"
        
        if default is not None:
            col_def += f" DEFAULT {default}"
        
        if pk:
            pk_cols.append(name)
        
        col_defs.append(col_def)
    
    # Add primary key constraint
    if pk_cols:
        col_defs.append(f'PRIMARY KEY ({", ".join(f"{c}" for c in pk_cols)})')
    
    # Create table
    create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n  ' + ",\n  ".join(col_defs) + "\n)"
    
    pg_cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')
    pg_cursor.execute(create_sql)


def migrate_table_data(sqlite_cursor, pg_conn, table_name: str, columns: list) -> int:
    """Migrate data from SQLite table to PostgreSQL. Returns rows_migrated."""
    
    col_names = [col[1] for col in columns]
    col_list = ", ".join(f'"{c}"' for c in col_names)
    
    # Count rows
    sqlite_cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    total_rows = sqlite_cursor.fetchone()[0]
    
    if total_rows == 0:
        print(f"   (empty table)")
        return 0
    
    print(f"   {total_rows:,} rows to migrate...")
    
    # Fetch and insert in batches
    sqlite_cursor.execute(f'SELECT {col_list} FROM "{table_name}"')
    
    migrated = 0
    start_time = time.time()
    
    # Prepare insert statement
    placeholders = ", ".join(["%s"] * len(col_names))
    insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})'
    
    while True:
        rows = sqlite_cursor.fetchmany(BATCH_SIZE)
        if not rows:
            break
        
        try:
            with pg_conn.cursor() as pg_cursor:
                pg_cursor.executemany(insert_sql, rows)
            pg_conn.commit()
            migrated += len(rows)
            
            # Progress update
            elapsed = time.time() - start_time
            rate = migrated / elapsed if elapsed > 0 else 0
            pct = (migrated / total_rows) * 100
            print(f"   ... {migrated:,}/{total_rows:,} ({pct:.1f}%) - {rate:.0f} rows/sec", end="\r")
            
        except Exception as e:
            print(f"\n   ⚠️  Error inserting batch: {e}")
            pg_conn.rollback()
            # Try inserting one by one to find problem row
            with pg_conn.cursor() as pg_cursor:
                for row in rows:
                    try:
                        pg_cursor.execute(insert_sql, row)
                        pg_conn.commit()
                        migrated += 1
                    except Exception as e2:
                        print(f"\n   ⚠️  Skipped row: {e2}")
                        pg_conn.rollback()
    
    elapsed = time.time() - start_time
    print(f"\n   ✅ {migrated:,} rows migrated in {elapsed:.1f}s")
    return migrated


# =============================================================================
# MAIN MIGRATION
# =============================================================================

def migrate():
    """Run the full migration."""
    
    print("=" * 60)
    print("🚀 SQLITE → NEON POSTGRESQL MIGRATION")
    print("=" * 60)
    print()
    
    # Check local database
    if not LOCAL_DB.exists():
        print(f"❌ Local database not found: {LOCAL_DB}")
        return False
    
    local_size_gb = LOCAL_DB.stat().st_size / (1024 * 1024 * 1024)
    print(f"📁 Source: {LOCAL_DB} ({local_size_gb:.2f} GB)")
    print(f"☁️  Target: Neon PostgreSQL")
    print()
    
    # Connect to SQLite
    print("🔌 Connecting to SQLite...")
    sqlite_conn = sqlite3.connect(str(LOCAL_DB))
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    print("🔌 Connecting to Neon...")
    try:
        pg_conn = psycopg.connect(NEON_URL)
        print("✅ Connected to Neon!")
    except Exception as e:
        print(f"❌ Failed to connect to Neon: {e}")
        return False
    
    # Show initial storage
    print()
    print_storage_status(pg_conn, prefix="📊 Initial ")
    print()
    
    # Get tables
    tables = get_sqlite_tables(sqlite_cursor)
    print(f"📋 Found {len(tables)} tables: {', '.join(tables)}")
    print()
    
    # Migrate each table
    total_rows = 0
    total_migrated_rows = 0
    start_time = time.time()
    
    for i, table in enumerate(tables, 1):
        print(f"[{i}/{len(tables)}] Migrating '{table}'...")
        
        # Get schema
        columns = get_table_schema(sqlite_cursor, table)
        
        # Create table in PostgreSQL
        try:
            with pg_conn.cursor() as pg_cursor:
                create_pg_table(pg_cursor, table, columns)
            pg_conn.commit()
        except Exception as e:
            print(f"   ❌ Failed to create table: {e}")
            pg_conn.rollback()
            continue
        
        # Migrate data
        rows = migrate_table_data(sqlite_cursor, pg_conn, table, columns)
        total_rows += rows
        
        # Show storage after each table
        print_storage_status(pg_conn, prefix="   ")
        print()
    
    # Final storage check
    print("=" * 60)
    print("📊 FINAL STORAGE STATUS")
    print_storage_status(pg_conn, prefix="   ")
    
    # Close connections
    sqlite_conn.close()
    pg_conn.close()
    
    # Summary
    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print("📊 MIGRATION COMPLETE")
    print(f"   Tables: {len(tables)}")
    print(f"   Total rows: {total_rows:,}")
    print(f"   Time: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    success = migrate()
    
    if success:
        print()
        print("✅ Migration successful!")
        print()
        print("Next steps:")
        print("1. Your .env already has the DATABASE_URL set")
        print("2. Your app will automatically use Neon!")
    else:
        print()
        print("❌ Migration failed. Check errors above.")
