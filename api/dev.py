"""
Ohio Fraud Tracker - Development Commands

Quick access to common operations.

Usage:
    python dev.py start          # Start API server
    python dev.py status         # Show database status  
    python dev.py import-usa     # Import USAspending data
    python dev.py correlate      # Run correlation analysis
    python dev.py shell          # Open Python shell with models loaded
"""

import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

PYTHON = os.path.join(SCRIPT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON):
    PYTHON = "python"


def run(cmd, **kwargs):
    """Run a command"""
    print(f"\n> {cmd}\n")
    subprocess.run(cmd, shell=True, **kwargs)


def cmd_start():
    """Start the API server"""
    run(f'"{PYTHON}" run.py')


def cmd_status():
    """Show database status"""
    from app.database import get_db_context
    from app.models import Award, Recipient, FraudFlag
    from sqlalchemy import func
    
    print("\n" + "=" * 50)
    print("DATABASE STATUS")
    print("=" * 50)
    
    with get_db_context() as db:
        awards = db.query(func.count(Award.id)).scalar() or 0
        recipients = db.query(func.count(Recipient.id)).scalar() or 0
        flags = db.query(func.count(FraudFlag.id)).scalar() or 0
        total = db.query(func.sum(Award.amount)).scalar() or 0
        
        print(f"\nTotals:")
        print(f"  Awards:      {awards:,}")
        print(f"  Recipients:  {recipients:,}")
        print(f"  Fraud Flags: {flags:,}")
        print(f"  Total $:     ${total:,.2f}")
        
        # By source
        sources = db.query(
            Award.source,
            func.count(Award.id).label("count"),
            func.sum(Award.amount).label("total")
        ).group_by(Award.source).all()
        
        if sources:
            print(f"\nBy Source:")
            for src in sources:
                print(f"  {src.source:20} {src.count:>8,} awards  ${src.total:>15,.2f}")


def cmd_import_usa():
    """Import USAspending data"""
    run(f'"{PYTHON}" -m scripts.import_usaspending --resume')


def cmd_import_ohio():
    """Import Ohio Checkbook data"""
    print("\nOhio Checkbook Import")
    print("=" * 50)
    print("\nUsage:")
    print("  python -m scripts.import_ohio_checkbook --file <csv_file>")
    print("  python -m scripts.import_ohio_checkbook --folder data/ohio_checkbook/")
    print("\nTo get data:")
    print("  1. Go to https://checkbook.ohio.gov/State/")
    print("  2. Apply filters and click 'Download CSV'")
    print("  3. Save to data/ohio_checkbook/ folder")


def cmd_correlate():
    """Run correlation analysis"""
    run(f'"{PYTHON}" -m scripts.run_correlation --save')


def cmd_shell():
    """Open interactive shell with models"""
    print("\nStarting interactive shell...")
    print("Available: db, Award, Recipient, Agency, FraudFlag")
    print()
    
    from app.database import get_db_context
    from app.models import Award, Recipient, Agency, FraudFlag
    
    with get_db_context() as db:
        import code
        code.interact(local={
            "db": db,
            "Award": Award,
            "Recipient": Recipient,
            "Agency": Agency,
            "FraudFlag": FraudFlag,
        })


def cmd_help():
    """Show help"""
    print(__doc__)
    print("\nAvailable commands:")
    for name, func in COMMANDS.items():
        doc = func.__doc__ or ""
        print(f"  {name:15} {doc}")


COMMANDS = {
    "start": cmd_start,
    "status": cmd_status,
    "import-usa": cmd_import_usa,
    "import-ohio": cmd_import_ohio,
    "correlate": cmd_correlate,
    "shell": cmd_shell,
    "help": cmd_help,
}


def main():
    if len(sys.argv) < 2:
        cmd_help()
        return
    
    cmd = sys.argv[1].lower()
    
    if cmd in COMMANDS:
        # Remove command from argv so sub-scripts work
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        COMMANDS[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        cmd_help()


if __name__ == "__main__":
    main()
