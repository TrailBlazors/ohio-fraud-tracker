"""
Check SQLite table sizes to see what's using space.

Run: python check_db_size.py
"""

import sqlite3
from pathlib import Path

LOCAL_DB = Path(__file__).parent / "data" / "ohio_fraud_tracker.db"

def check_sizes():
    print(f"📁 Database: {LOCAL_DB}")
    print(f"📊 Total size: {LOCAL_DB.stat().st_size / (1024*1024*1024):.2f} GB")
    print()
    
    conn = sqlite3.connect(str(LOCAL_DB))
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
    """)
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"{'Table':<40} {'Rows':>15} {'Est. Size':>15}")
    print("-" * 70)
    
    table_info = []
    for table in tables:
        cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
        row_count = cursor.fetchone()[0]
        
        # Estimate size by sampling
        cursor.execute(f'SELECT * FROM "{table}" LIMIT 100')
        sample = cursor.fetchall()
        if sample:
            avg_row_size = sum(len(str(row)) for row in sample) / len(sample)
            est_size_mb = (row_count * avg_row_size) / (1024 * 1024)
        else:
            est_size_mb = 0
        
        table_info.append((table, row_count, est_size_mb))
    
    # Sort by estimated size descending
    table_info.sort(key=lambda x: x[2], reverse=True)
    
    total_rows = 0
    for table, rows, size_mb in table_info:
        total_rows += rows
        if size_mb > 1024:
            size_str = f"{size_mb/1024:.2f} GB"
        else:
            size_str = f"{size_mb:.2f} MB"
        print(f"{table:<40} {rows:>15,} {size_str:>15}")
    
    print("-" * 70)
    print(f"{'TOTAL':<40} {total_rows:>15,}")
    
    conn.close()
    
    print()
    print("💡 To fit in Neon free tier (512 MB), consider migrating only")
    print("   the smaller tables or upgrading to the Launch plan.")

if __name__ == "__main__":
    print("=" * 50)
    print("📊 SQLITE DATABASE SIZE CHECK")
    print("=" * 50)
    print()
    check_sizes()
