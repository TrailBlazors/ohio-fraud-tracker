"""
Fix the awards.amount column type in Neon.

The amount column was incorrectly stored as TEXT instead of DOUBLE PRECISION.
This script fixes it by:
1. Adding a new numeric column
2. Copying data with type conversion
3. Dropping the old column
4. Renaming the new column

Run from the api directory:
    python fix_amount_column.py
"""

import psycopg
import time

NEON_URL = "postgresql://neondb_owner:npg_qa8C5pMKflvG@ep-green-fog-a8mwvkcw-pooler.eastus2.azure.neon.tech/ohio-fraud-tracker?sslmode=require"

def fix_amount_column():
    print("=" * 60)
    print("🔧 FIXING awards.amount COLUMN TYPE")
    print("=" * 60)
    print()
    
    print("🔌 Connecting to Neon...")
    conn = psycopg.connect(NEON_URL)
    
    # Check current column type
    with conn.cursor() as cur:
        cur.execute("""
            SELECT data_type 
            FROM information_schema.columns 
            WHERE table_name = 'awards' AND column_name = 'amount'
        """)
        result = cur.fetchone()
        current_type = result[0] if result else "unknown"
        print(f"📊 Current amount column type: {current_type}")
        
        if current_type in ('double precision', 'numeric', 'real'):
            print("✅ Column is already numeric type. No fix needed!")
            conn.close()
            return True
    
    print()
    print("⚠️  Column is TEXT - needs to be converted to DOUBLE PRECISION")
    print()
    
    # Get row count
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM awards")
        total_rows = cur.fetchone()[0]
        print(f"📋 Total rows to update: {total_rows:,}")
    
    print()
    print("🔄 Starting conversion (this may take a while)...")
    print()
    
    start_time = time.time()
    
    try:
        with conn.cursor() as cur:
            # Step 1: Add new column
            print("   Step 1/4: Adding new column 'amount_new'...")
            cur.execute("ALTER TABLE awards ADD COLUMN amount_new DOUBLE PRECISION")
            conn.commit()
            print("   ✅ New column added")
            
            # Step 2: Update in batches
            print("   Step 2/4: Copying data (in batches)...")
            
            batch_size = 100000
            offset = 0
            updated = 0
            
            while offset < total_rows:
                cur.execute(f"""
                    UPDATE awards 
                    SET amount_new = CAST(amount AS DOUBLE PRECISION)
                    WHERE id IN (
                        SELECT id FROM awards 
                        ORDER BY id 
                        LIMIT {batch_size} OFFSET {offset}
                    )
                """)
                conn.commit()
                
                updated += batch_size
                pct = min(100, (updated / total_rows) * 100)
                elapsed = time.time() - start_time
                rate = updated / elapsed if elapsed > 0 else 0
                print(f"      ... {min(updated, total_rows):,}/{total_rows:,} ({pct:.1f}%) - {rate:,.0f} rows/sec", end="\r")
                
                offset += batch_size
            
            print()
            print("   ✅ Data copied")
            
            # Step 3: Drop old column
            print("   Step 3/4: Dropping old 'amount' column...")
            cur.execute("ALTER TABLE awards DROP COLUMN amount")
            conn.commit()
            print("   ✅ Old column dropped")
            
            # Step 4: Rename new column
            print("   Step 4/4: Renaming 'amount_new' to 'amount'...")
            cur.execute("ALTER TABLE awards RENAME COLUMN amount_new TO amount")
            conn.commit()
            print("   ✅ Column renamed")
        
        elapsed = time.time() - start_time
        print()
        print("=" * 60)
        print(f"✅ FIX COMPLETE in {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        print("=" * 60)
        
        # Verify
        with conn.cursor() as cur:
            cur.execute("""
                SELECT data_type 
                FROM information_schema.columns 
                WHERE table_name = 'awards' AND column_name = 'amount'
            """)
            new_type = cur.fetchone()[0]
            print(f"📊 New amount column type: {new_type}")
            
            cur.execute("SELECT SUM(amount), MIN(amount), MAX(amount) FROM awards")
            sum_val, min_val, max_val = cur.fetchone()
            print(f"📊 SUM(amount): ${sum_val:,.2f}")
            print(f"📊 Range: ${min_val:,.2f} to ${max_val:,.2f}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        conn.rollback()
        conn.close()
        return False


if __name__ == "__main__":
    fix_amount_column()
