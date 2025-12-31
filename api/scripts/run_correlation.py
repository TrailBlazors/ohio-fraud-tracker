"""
Run Correlation Analysis

Scans the database for fraud indicators by cross-referencing data sources.

Usage:
    python -m scripts.run_correlation
    python -m scripts.run_correlation --save
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import get_db_context, init_db


def main():
    parser = argparse.ArgumentParser(description="Run fraud correlation analysis")
    parser.add_argument("--save", action="store_true", 
                       help="Save flags to database")
    parser.add_argument("--show-multi-source", action="store_true",
                       help="Show recipients receiving from multiple sources")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("FRAUD CORRELATION ANALYSIS")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Save flags: {args.save}")
    print()
    
    init_db()
    
    with get_db_context() as db:
        from src.correlation.engine import CorrelationEngine
        
        engine = CorrelationEngine(db)
        
        # Run the scan
        flags = engine.run_full_scan()
        
        # Summarize results
        print("\n" + "=" * 60)
        print("RESULTS SUMMARY")
        print("=" * 60)
        
        by_type = {}
        by_severity = {}
        for flag in flags:
            by_type[flag.flag_type.value] = by_type.get(flag.flag_type.value, 0) + 1
            by_severity[flag.severity.value] = by_severity.get(flag.severity.value, 0) + 1
        
        print(f"\nTotal flags found: {len(flags)}")
        
        if by_severity:
            print("\nBy Severity:")
            for sev in ["critical", "high", "medium", "low"]:
                if sev in by_severity:
                    print(f"  {sev.upper():10} {by_severity[sev]}")
        
        if by_type:
            print("\nBy Type:")
            for typ, count in sorted(by_type.items(), key=lambda x: -x[1]):
                print(f"  {typ:40} {count}")
        
        # Show critical/high flags
        critical_high = [f for f in flags if f.severity.value in ["critical", "high"]]
        if critical_high:
            print(f"\n{'='*60}")
            print(f"TOP CRITICAL/HIGH FLAGS ({min(15, len(critical_high))} of {len(critical_high)})")
            print("=" * 60)
            
            for flag in critical_high[:15]:
                print(f"\n[{flag.severity.value.upper()}] {flag.flag_type.value}")
                print(f"  {flag.description}")
                if flag.evidence:
                    for key, val in list(flag.evidence.items())[:3]:
                        print(f"    {key}: {val}")
        
        # Multi-source recipients
        if args.show_multi_source:
            print(f"\n{'='*60}")
            print("MULTI-SOURCE RECIPIENTS")
            print("=" * 60)
            
            multi = engine.find_multi_source_recipients(min_sources=2)
            print(f"\nFound {len(multi)} recipients with funding from 2+ sources")
            
            for r in multi[:10]:
                print(f"\n  {r['recipient_name']} ({r['city']})")
                print(f"    Total: ${r['total_amount']:,.2f} from {r['source_count']} sources")
                for src in r['by_source']:
                    print(f"      - {src['source']}: ${src['amount']:,.2f} ({src['count']} awards)")
        
        # Save if requested
        if args.save and flags:
            saved = engine.save_flags_to_db(flags)
            print(f"\n✓ Saved {saved} new flags to database")
        
        print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
