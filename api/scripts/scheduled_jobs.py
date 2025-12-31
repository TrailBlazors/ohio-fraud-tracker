"""
Scheduled Correlation Jobs

Run via cron (Linux) or Task Scheduler (Windows).

Jobs:
1. Weekly full scan - Run complete correlation analysis
2. Hourly quick scan - Check newly imported data

Usage:
    python -m scripts.scheduled_jobs weekly
    python -m scripts.scheduled_jobs hourly
    python -m scripts.scheduled_jobs status

Cron examples (Linux):
    # Weekly Sunday at 3 AM
    0 3 * * 0 cd /path/to/ohio-fraud-tracker && /path/to/venv/bin/python -m scripts.scheduled_jobs weekly
    
    # Hourly
    0 * * * * cd /path/to/ohio-fraud-tracker && /path/to/venv/bin/python -m scripts.scheduled_jobs hourly
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_weekly_full_scan(db):
    """
    Weekly job: Run complete correlation analysis.
    """
    from src.correlation.engine import CorrelationEngine
    
    logger.info("=" * 60)
    logger.info("WEEKLY FULL SCAN")
    logger.info("=" * 60)
    
    engine = CorrelationEngine(db)
    
    # Run full scan
    flags = engine.run_full_scan()
    
    # Save flags
    saved = 0
    if flags:
        saved = engine.save_flags_to_db(flags)
    
    # Summarize
    by_type = {}
    by_severity = {}
    for flag in flags:
        by_type[flag.flag_type.value] = by_type.get(flag.flag_type.value, 0) + 1
        by_severity[flag.severity.value] = by_severity.get(flag.severity.value, 0) + 1
    
    results = {
        "job": "weekly_full_scan",
        "timestamp": datetime.utcnow().isoformat(),
        "flags_found": len(flags),
        "flags_saved": saved,
        "by_severity": by_severity,
        "by_type": by_type
    }
    
    logger.info(f"Weekly scan complete: {json.dumps(results, indent=2)}")
    return results


def run_hourly_quick_scan(db):
    """
    Hourly job: Quick scan of recently imported data.
    """
    from src.correlation.post_import import quick_scan_new_data
    
    logger.info("=" * 60)
    logger.info("HOURLY QUICK SCAN")
    logger.info("=" * 60)
    
    results = quick_scan_new_data(db, since_hours=2)  # Overlap for safety
    
    logger.info(f"Hourly scan complete: {results}")
    return results


def show_status(db):
    """
    Show current database and flag status.
    """
    from api.app.models import Award, Recipient, FraudFlag
    from sqlalchemy import func
    
    logger.info("=" * 60)
    logger.info("DATABASE STATUS")
    logger.info("=" * 60)
    
    # Counts
    total_recipients = db.query(func.count(Recipient.id)).scalar() or 0
    total_awards = db.query(func.count(Award.id)).scalar() or 0
    total_amount = db.query(func.sum(Award.amount)).scalar() or 0
    
    print(f"\nDatabase:")
    print(f"  Recipients: {total_recipients:,}")
    print(f"  Awards: {total_awards:,}")
    print(f"  Total Amount: ${total_amount:,.2f}")
    
    # Awards by source
    sources = db.query(
        Award.source,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).group_by(Award.source).all()
    
    if sources:
        print(f"\nBy Source:")
        for s in sources:
            print(f"  {s.source}: {s.count:,} awards (${s.total:,.2f})")
    
    # Fraud flags
    total_flags = db.query(func.count(FraudFlag.id)).scalar() or 0
    unresolved = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.is_resolved == False
    ).scalar() or 0
    
    print(f"\nFraud Flags:")
    print(f"  Total: {total_flags:,}")
    print(f"  Unresolved: {unresolved:,}")
    
    # Flags by severity
    severity_counts = db.query(
        FraudFlag.severity,
        func.count(FraudFlag.id).label("count")
    ).filter(
        FraudFlag.is_resolved == False
    ).group_by(FraudFlag.severity).all()
    
    if severity_counts:
        print(f"\nUnresolved by Severity:")
        for s in severity_counts:
            print(f"  {s.severity}: {s.count}")
    
    return {
        "recipients": total_recipients,
        "awards": total_awards,
        "total_amount": total_amount,
        "flags": total_flags,
        "unresolved_flags": unresolved
    }


def main():
    parser = argparse.ArgumentParser(description="Run scheduled correlation jobs")
    parser.add_argument("job", choices=["weekly", "hourly", "status"],
                       help="Job to run")
    parser.add_argument("--output", type=str,
                       help="Output results to JSON file")
    
    args = parser.parse_args()
    
    # Initialize database
    from app.database import get_db_context, init_db
    init_db()
    
    # Run the job
    with get_db_context() as db:
        if args.job == "weekly":
            results = run_weekly_full_scan(db)
        elif args.job == "hourly":
            results = run_hourly_quick_scan(db)
        elif args.job == "status":
            results = show_status(db)
    
    # Output to file if requested
    if args.output and results:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
