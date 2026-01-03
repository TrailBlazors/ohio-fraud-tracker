"""
Fix Neon database schema and add indexes for performance.

Issues to fix:
1. Some columns stored as TEXT instead of proper types
2. Missing indexes for common queries

Run from the api directory:
    python fix_neon_schema.py
"""

import psycopg
import time

NEON_URL = "postgresql://neondb_owner:npg_qa8C5pMKflvG@ep-green-fog-a8mwvkcw-pooler.eastus2.azure.neon.tech/ohio-fraud-tracker?sslmode=require"


def get_column_types(conn, table: str) -> dict:
    """Get column names and types for a table."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns 
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table,))
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def fix_column_type(conn, table: str, column: str, new_type: str):
    """Convert a column to a new type."""
    print(f"   Converting {table}.{column} to {new_type}...")
    
    with conn.cursor() as cur:
        # Use ALTER COLUMN with USING for type conversion
        cur.execute(f"""
            ALTER TABLE "{table}" 
            ALTER COLUMN "{column}" TYPE {new_type} 
            USING "{column}"::{new_type}
        """)
    conn.commit()
    print(f"   ✅ Done")


def create_index(conn, table: str, columns: list, name: str = None, unique: bool = False):
    """Create an index if it doesn't exist."""
    if name is None:
        name = f"idx_{table}_{'_'.join(columns)}"
    
    col_list = ', '.join(f'"{c}"' for c in columns)
    unique_str = "UNIQUE " if unique else ""
    
    with conn.cursor() as cur:
        # Check if index exists
        cur.execute("""
            SELECT 1 FROM pg_indexes 
            WHERE tablename = %s AND indexname = %s
        """, (table, name))
        
        if cur.fetchone():
            print(f"   ⏭️  Index {name} already exists")
            return
        
        print(f"   Creating {unique_str.lower()}index {name} on {table}({col_list})...")
        cur.execute(f'CREATE {unique_str}INDEX "{name}" ON "{table}" ({col_list})')
    conn.commit()
    print(f"   ✅ Done")


def main():
    print("=" * 60)
    print("🔧 FIX NEON SCHEMA AND ADD INDEXES")
    print("=" * 60)
    print()
    
    print("🔌 Connecting to Neon...")
    conn = psycopg.connect(NEON_URL)
    print("✅ Connected")
    print()
    
    # ==========================================================================
    # 1. FIX COLUMN TYPES
    # ==========================================================================
    print("📋 CHECKING COLUMN TYPES")
    print("-" * 40)
    
    # Expected types for key columns
    expected_types = {
        "awards": {
            "amount": "double precision",
            "id": "bigint",
            "recipient_id": "bigint",
            "agency_id": "bigint",
        },
        "cached_stats": {
            "stat_value": "double precision",
        },
        "recipients": {
            "id": "bigint",
        },
        "fraud_flags": {
            "id": "bigint",
            "award_id": "bigint",
            "recipient_id": "bigint",
        },
    }
    
    for table, columns in expected_types.items():
        print(f"\n{table}:")
        current_types = get_column_types(conn, table)
        
        for column, expected in columns.items():
            if column not in current_types:
                print(f"   ⚠️  Column {column} not found")
                continue
                
            actual = current_types[column][0]
            if actual != expected:
                print(f"   🔄 {column}: {actual} → {expected}")
                try:
                    fix_column_type(conn, table, column, expected)
                except Exception as e:
                    print(f"   ❌ Error: {e}")
                    conn.rollback()
            else:
                print(f"   ✅ {column}: {actual}")
    
    # ==========================================================================
    # 2. CREATE INDEXES (matching models.py)
    # ==========================================================================
    print()
    print("📋 CREATING INDEXES")
    print("-" * 40)
    
    indexes = [
        # Awards - single column (from index=True)
        ("awards", ["source"]),
        ("awards", ["recipient_id"]),
        ("awards", ["agency_id"]),
        ("awards", ["award_type"]),
        ("awards", ["amount"]),
        ("awards", ["award_date"]),
        ("awards", ["cfda_number"]),
        
        # Awards - composite (from __table_args__)
        ("awards", ["source", "source_award_id"], "ix_awards_source_id", True),  # unique=True
        ("awards", ["award_date", "amount"], "ix_awards_date_amount"),
        ("awards", ["award_type", "award_date"], "ix_awards_type_date"),
        ("awards", ["recipient_id", "award_date"], "ix_awards_recipient_date"),
        
        # Recipients - single column
        ("recipients", ["uei"]),
        ("recipients", ["duns"]),
        ("recipients", ["ein"]),
        ("recipients", ["ohio_entity_number"]),
        ("recipients", ["name"]),
        ("recipients", ["name_normalized"]),
        ("recipients", ["naics_code"]),
        ("recipients", ["city"]),
        
        # Recipients - composite
        ("recipients", ["name_normalized", "city"], "ix_recipients_name_city"),
        ("recipients", ["business_status"], "ix_recipients_status"),
        
        # NAICS codes
        ("naics_codes", ["sector"], "ix_naics_sector"),
        
        # Sub-agencies
        ("sub_agencies", ["agency_id"], "ix_sub_agencies_agency"),
        
        # Fraud flags - single column
        ("fraud_flags", ["recipient_id"]),
        ("fraud_flags", ["award_id"]),
        ("fraud_flags", ["flag_type"]),
        
        # Fraud flags - composite
        ("fraud_flags", ["flag_type", "severity"], "ix_fraud_flags_type_severity"),
        
        # Data imports
        ("data_imports", ["source", "status"], "ix_data_imports_source_status"),
        
        # Cached stats
        ("cached_stats", ["stat_key"]),
        
        # Excluded entities - single column
        ("excluded_entities", ["last_name"]),
        ("excluded_entities", ["business_name"]),
        ("excluded_entities", ["name_normalized"]),
        ("excluded_entities", ["npi"]),
        ("excluded_entities", ["city"]),
        ("excluded_entities", ["state"]),
        ("excluded_entities", ["exclusion_date"]),
        
        # Excluded entities - composite
        ("excluded_entities", ["name_normalized", "state"], "ix_excluded_name_state"),
    ]
    
    for item in indexes:
        table = item[0]
        columns = item[1]
        name = item[2] if len(item) > 2 else None
        unique = item[3] if len(item) > 3 else False
        try:
            create_index(conn, table, columns, name, unique)
        except Exception as e:
            print(f"   ❌ Error creating index on {table}: {e}")
            conn.rollback()
    
    # ==========================================================================
    # 3. ANALYZE TABLES
    # ==========================================================================
    print()
    print("📋 ANALYZING TABLES")
    print("-" * 40)
    
    tables = ["awards", "recipients", "agencies", "fraud_flags", "cached_stats"]
    
    for table in tables:
        print(f"   Analyzing {table}...")
        with conn.cursor() as cur:
            cur.execute(f'ANALYZE "{table}"')
        conn.commit()
    
    print("   ✅ Done")
    
    # ==========================================================================
    # SUMMARY
    # ==========================================================================
    print()
    print("=" * 60)
    print("✅ SCHEMA FIXES COMPLETE")
    print("=" * 60)
    
    conn.close()


if __name__ == "__main__":
    main()
