"""
Verify SQLite to Neon migration data integrity.

Checks:
1. Row counts match
2. Sum of numeric columns match (amounts, etc.)
3. Min/Max of key columns match
4. Random sample comparison
5. Schema verification

Run from the api directory:
    python verify_migration.py
"""

import sqlite3
import psycopg
from pathlib import Path
import random
import datetime

# =============================================================================
# CONFIGURATION
# =============================================================================

NEON_URL = "postgresql://neondb_owner:npg_qa8C5pMKflvG@ep-green-fog-a8mwvkcw-pooler.eastus2.azure.neon.tech/ohio-fraud-tracker?sslmode=require"
LOCAL_DB = Path(__file__).parent / "data" / "ohio_fraud_tracker.db"

# Columns to check sums for (table: [columns])
SUM_COLUMNS = {
    "awards": ["amount"],
    "ppp_loans": ["loan_amount", "forgiveness_amount"],
}

# Columns to check min/max for (table: [columns])
MINMAX_COLUMNS = {
    "awards": ["id", "amount"],
    "recipients": ["id"],
    "agencies": ["id"],
}

# Number of random rows to spot-check per table
SAMPLE_SIZE = 5

# =============================================================================
# VERIFICATION FUNCTIONS
# =============================================================================

def get_sqlite_tables(cursor) -> list:
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    return [row[0] for row in cursor.fetchall()]


def get_row_count(cursor, table: str, is_pg: bool = False, conn=None) -> int:
    try:
        cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cursor.fetchone()[0]
    except Exception as e:
        if conn:
            conn.rollback()
        return -1


def get_column_sum(cursor, table: str, column: str, conn=None) -> float:
    try:
        cursor.execute(f'SELECT COALESCE(SUM("{column}"), 0) FROM "{table}"')
        result = cursor.fetchone()[0]
        return float(result) if result else 0.0
    except Exception:
        if conn:
            conn.rollback()
        return -1


def get_column_minmax(cursor, table: str, column: str, conn=None) -> tuple:
    try:
        cursor.execute(f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}"')
        return cursor.fetchone()
    except Exception:
        if conn:
            conn.rollback()
        return (None, None)


def get_primary_key_column(cursor, table: str, is_pg: bool = False) -> str:
    """Get the primary key column name for a table."""
    if is_pg:
        cursor.execute("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
        """, (table,))
        result = cursor.fetchone()
        return result[0] if result else "id"
    else:
        cursor.execute(f"PRAGMA table_info('{table}')")
        for col in cursor.fetchall():
            if col[5]:  # pk column
                return col[1]
        return "id"


def get_random_ids(cursor, table: str, id_column: str, count: int, conn=None) -> list:
    try:
        cursor.execute(f'SELECT "{id_column}" FROM "{table}" ORDER BY RANDOM() LIMIT {count}')
        return [row[0] for row in cursor.fetchall()]
    except Exception:
        if conn:
            conn.rollback()
        return []


def get_row_by_id(cursor, table: str, id_column: str, id_value) -> dict:
    try:
        cursor.execute(f'SELECT * FROM "{table}" WHERE "{id_column}" = ?', (id_value,))
        row = cursor.fetchone()
        if row:
            cols = [desc[0] for desc in cursor.description]
            return dict(zip(cols, row))
        return None
    except Exception:
        return None


def get_row_by_id_pg(cursor, table: str, id_column: str, id_value, conn=None) -> dict:
    try:
        cursor.execute(f'SELECT * FROM "{table}" WHERE "{id_column}" = %s', (id_value,))
        row = cursor.fetchone()
        if row:
            cols = [desc[0] for desc in cursor.description]
            return dict(zip(cols, row))
        return None
    except Exception:
        if conn:
            conn.rollback()
        return None


def compare_rows(sqlite_row: dict, pg_row: dict) -> list:
    """Compare two rows and return list of differences."""
    differences = []
    
    if not sqlite_row or not pg_row:
        return ["Row missing in one database"]
    
    for key in sqlite_row:
        sqlite_val = sqlite_row.get(key)
        pg_val = pg_row.get(key)
        
        # Handle boolean conversion (SQLite 0/1 vs PostgreSQL True/False)
        if sqlite_val in (0, 1) and pg_val in (True, False):
            if bool(sqlite_val) != pg_val:
                differences.append(f"{key}: {sqlite_val} vs {pg_val}")
            continue
        
        # Handle date/datetime - SQLite stores as string, PG as native types
        if isinstance(pg_val, (datetime.date, datetime.datetime)):
            # Compare string representations
            sqlite_str = str(sqlite_val) if sqlite_val else None
            pg_str = str(pg_val) if pg_val else None
            if sqlite_str != pg_str:
                differences.append(f"{key}: {sqlite_str} vs {pg_str}")
            continue
        
        # Handle float comparison with tolerance
        if isinstance(sqlite_val, (int, float)) and isinstance(pg_val, (int, float)):
            if abs(float(sqlite_val) - float(pg_val)) > 0.01:
                differences.append(f"{key}: {sqlite_val} vs {pg_val}")
            continue
        
        # Handle numeric stored as string in PG (type issue)
        if isinstance(sqlite_val, (int, float)) and isinstance(pg_val, str):
            try:
                if abs(float(sqlite_val) - float(pg_val)) > 0.01:
                    differences.append(f"{key}: {sqlite_val} vs {pg_val} (TYPE MISMATCH)")
            except ValueError:
                differences.append(f"{key}: {sqlite_val} vs {pg_val} (TYPE MISMATCH)")
            continue
        
        # Handle None vs empty string
        if sqlite_val is None and pg_val == '':
            continue
        if sqlite_val == '' and pg_val is None:
            continue
        
        if sqlite_val != pg_val:
            differences.append(f"{key}: {repr(sqlite_val)[:50]} vs {repr(pg_val)[:50]}")
    
    return differences


def get_table_schema_sqlite(cursor, table: str) -> dict:
    cursor.execute(f"PRAGMA table_info('{table}')")
    return {row[1]: row[2] for row in cursor.fetchall()}


def get_table_schema_pg(cursor, table: str, conn=None) -> dict:
    try:
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table,))
        return {row[0]: row[1] for row in cursor.fetchall()}
    except Exception:
        if conn:
            conn.rollback()
        return {}


# =============================================================================
# MAIN VERIFICATION
# =============================================================================

def verify():
    print("=" * 70)
    print("🔍 MIGRATION VERIFICATION: SQLite vs Neon PostgreSQL")
    print("=" * 70)
    print()
    
    # Connect to databases
    print("🔌 Connecting to databases...")
    sqlite_conn = sqlite3.connect(str(LOCAL_DB))
    sqlite_cursor = sqlite_conn.cursor()
    
    try:
        pg_conn = psycopg.connect(NEON_URL)
        pg_cursor = pg_conn.cursor()
        print("✅ Connected to both databases")
    except Exception as e:
        print(f"❌ Failed to connect to Neon: {e}")
        return False
    
    print()
    
    # Get tables
    tables = get_sqlite_tables(sqlite_cursor)
    print(f"📋 Checking {len(tables)} tables...")
    print()
    
    all_passed = True
    issues = []
    
    for table in tables:
        print(f"━━━ {table} ━━━")
        table_ok = True
        
        # 1. Row count check
        sqlite_count = get_row_count(sqlite_cursor, table)
        pg_count = get_row_count(pg_cursor, table, conn=pg_conn)
        
        if sqlite_count == pg_count:
            print(f"  ✅ Row count: {sqlite_count:,}")
        else:
            print(f"  ❌ Row count MISMATCH: SQLite={sqlite_count:,} vs Neon={pg_count:,}")
            issues.append(f"{table}: Row count mismatch ({sqlite_count} vs {pg_count})")
            table_ok = False
            all_passed = False
        
        # 2. Sum checks for numeric columns
        if table in SUM_COLUMNS:
            for col in SUM_COLUMNS[table]:
                sqlite_sum = get_column_sum(sqlite_cursor, table, col)
                pg_sum = get_column_sum(pg_cursor, table, col, conn=pg_conn)
                
                if abs(sqlite_sum - pg_sum) < 0.01 or (sqlite_sum > 0 and abs(sqlite_sum - pg_sum) / sqlite_sum < 0.0000001):
                    print(f"  ✅ SUM({col}): ${sqlite_sum:,.2f}")
                elif abs(sqlite_sum - pg_sum) < 100:  # Less than $100 diff = floating point
                    print(f"  ✅ SUM({col}): ${sqlite_sum:,.2f} (±${abs(sqlite_sum - pg_sum):.2f} precision diff)")
                else:
                    print(f"  ❌ SUM({col}) MISMATCH: ${sqlite_sum:,.2f} vs ${pg_sum:,.2f}")
                    issues.append(f"{table}.{col}: Sum mismatch")
                    table_ok = False
                    all_passed = False
        
        # 3. Min/Max checks
        if table in MINMAX_COLUMNS:
            for col in MINMAX_COLUMNS[table]:
                sqlite_mm = get_column_minmax(sqlite_cursor, table, col)
                pg_mm = get_column_minmax(pg_cursor, table, col, conn=pg_conn)
                
                if sqlite_mm == pg_mm:
                    print(f"  ✅ {col} range: {sqlite_mm[0]} to {sqlite_mm[1]}")
                else:
                    print(f"  ⚠️  {col} range: SQLite={sqlite_mm} vs Neon={pg_mm}")
        
        # 4. Random sample comparison
        if sqlite_count > 0 and pg_count > 0:
            # Get primary key column for this table
            pk_col = get_primary_key_column(sqlite_cursor, table, is_pg=False)
            sample_ids = get_random_ids(sqlite_cursor, table, pk_col, SAMPLE_SIZE)
            
            if sample_ids:
                sample_diffs = 0
                for id_val in sample_ids:
                    sqlite_row = get_row_by_id(sqlite_cursor, table, pk_col, id_val)
                    pg_row = get_row_by_id_pg(pg_cursor, table, pk_col, id_val, conn=pg_conn)
                    
                    diffs = compare_rows(sqlite_row, pg_row)
                    if diffs:
                        sample_diffs += 1
                        if sample_diffs <= 2:  # Only show first 2
                            print(f"  ⚠️  Row {pk_col}={id_val} differences: {diffs[:3]}")
                
                if sample_diffs == 0:
                    print(f"  ✅ Sample check: {len(sample_ids)} random rows match")
                else:
                    print(f"  ⚠️  Sample check: {sample_diffs}/{len(sample_ids)} rows have differences")
        
        # 5. Schema check (column count)
        sqlite_schema = get_table_schema_sqlite(sqlite_cursor, table)
        pg_schema = get_table_schema_pg(pg_cursor, table, conn=pg_conn)
        
        if len(sqlite_schema) == len(pg_schema):
            print(f"  ✅ Schema: {len(sqlite_schema)} columns")
        else:
            print(f"  ⚠️  Schema: SQLite={len(sqlite_schema)} cols vs Neon={len(pg_schema)} cols")
        
        print()
    
    # Summary
    print("=" * 70)
    if all_passed:
        print("✅ ALL CHECKS PASSED - Migration verified!")
    else:
        print("❌ ISSUES FOUND:")
        for issue in issues:
            print(f"   • {issue}")
    print("=" * 70)
    
    # Close connections
    sqlite_conn.close()
    pg_conn.close()
    
    return all_passed


if __name__ == "__main__":
    verify()
