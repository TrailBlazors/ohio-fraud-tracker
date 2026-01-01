"""
Drop the unused ppp_loans table.

Usage:
    python -m scripts.drop_ppp_loans
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import engine


def drop_table():
    print("Dropping ppp_loans table...")
    
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS ppp_loans"))
        conn.commit()
    
    print("✓ Done. PPP data remains in the awards table with source='sba_ppp'.")


if __name__ == "__main__":
    drop_table()
