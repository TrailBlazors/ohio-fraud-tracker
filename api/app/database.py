"""
Database connection and session management.

Supports both local SQLite and Turso (libSQL) in production.
"""

import os
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

# Check for Turso URL (production) or use local SQLite
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
    # Production: Use Turso (libSQL)
    # Format: libsql://your-db.turso.io?authToken=xxx
    DATABASE_URL = f"{TURSO_DATABASE_URL}?authToken={TURSO_AUTH_TOKEN}"
    IS_TURSO = True
else:
    # Local development: Use SQLite file
    # Build absolute path to data directory
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(exist_ok=True)
    DB_PATH = DATA_DIR / "ohio_fraud_tracker.db"
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    IS_TURSO = False


# =============================================================================
# ENGINE SETUP
# =============================================================================

def get_engine():
    """Create database engine with appropriate settings"""
    
    if IS_TURSO:
        # Turso uses libsql dialect
        # Requires: pip install libsql-experimental
        engine = create_engine(
            DATABASE_URL,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        )
    else:
        # SQLite with optimizations
        engine = create_engine(
            DATABASE_URL,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            connect_args={"check_same_thread": False},  # Needed for FastAPI
        )
        
        # SQLite performance optimizations
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")  # Better concurrency
            cursor.execute("PRAGMA synchronous=NORMAL")  # Faster writes
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            cursor.execute("PRAGMA foreign_keys=ON")  # Enforce FK constraints
            cursor.close()
    
    return engine


# Create engine and session factory
engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# =============================================================================
# SESSION MANAGEMENT
# =============================================================================

def get_db():
    """
    Dependency for FastAPI routes.
    Yields a database session and ensures cleanup.
    
    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """
    Context manager for scripts/jobs (non-FastAPI).
    
    Usage:
        with get_db_context() as db:
            db.query(Award).filter(...)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# =============================================================================
# INITIALIZATION
# =============================================================================

def init_db():
    """
    Create all database tables.
    Call this once on first run or after schema changes.
    """
    from app.models import Base
    
    Base.metadata.create_all(bind=engine)
    print(f"Database initialized: {'Turso' if IS_TURSO else 'SQLite'}")


def drop_all():
    """Drop all tables (use with caution!)"""
    from app.models import Base
    Base.metadata.drop_all(bind=engine)
    print("All tables dropped")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_db_info() -> dict:
    """Get database connection info (for debugging/status)"""
    return {
        "type": "turso" if IS_TURSO else "sqlite",
        "url": TURSO_DATABASE_URL if IS_TURSO else DATABASE_URL.replace("sqlite:///", ""),
        "is_production": IS_TURSO,
    }
