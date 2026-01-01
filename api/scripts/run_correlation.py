"""
Run Correlation Analysis

Scans for fraud indicators:
- Duplicate awards (same recipient, amount, date)
- Outlier amounts (5x above average)
- Multiple recipients at same address
- Inactive businesses receiving funds

Usage:
    python -m scripts.run_correlation
    python -m scripts.run_correlation --dry-run   # Don't save to DB
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_db_context, init_db


def run_correlation(dry_run: bool = False):
    print("=" * 60)
    print("CORRELATION ANALYSIS")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Dry run: {dry_run}")
    
    init_db()
    
    with get_db_context() as db:
        try:
            from src.correlation.engine import CorrelationEngine
            
            engine = CorrelationEngine(db)
            print("\nRunning full scan...")
            flags = engine.run_full_scan()
            
            print(f"\n✓ Found {len(flags)} potential issues")
            
            # Summarize by type
            by_type = {}
            by_severity = {}
            for flag in flags:
                t = flag.flag_type.value
                s = flag.severity.value
                by_type[t] = by_type.get(t, 0) + 1
                by_severity[s] = by_severity.get(s, 0) + 1
            
            if by_type:
                print("\nBy type:")
                for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
                    print(f"  {t}: {count}")
            
            if by_severity:
                print("\nBy severity:")
                for s, count in sorted(by_severity.items()):
                    print(f"  {s}: {count}")
            
            # Save if not dry run
            if not dry_run and flags:
                print("\nSaving to database...")
                saved_count = engine.save_flags_to_db(flags)
                print(f"✓ Saved {saved_count} flags")
            elif dry_run:
                print("\n(Dry run - not saved)")
            
            print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
        except ImportError as e:
            print(f"\n✗ Import error: {e}")
            print("\nMake sure the correlation engine exists at src/correlation/engine.py")
            sys.exit(1)
        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run correlation analysis")
    parser.add_argument("--dry-run", action="store_true", help="Don't save flags to database")
    args = parser.parse_args()
    
    run_correlation(dry_run=args.dry_run)
