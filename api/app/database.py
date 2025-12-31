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

# Determine if we can use Turso (need both credentials AND the libsql package)
IS_TURSO = False
DATABASE_URL = None

if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
    # Check if libsql dialect is available
    try:
        from sqlalchemy.dialects import registry
        registry.load("sqlite.libsql")
        # If we get here, libsql is available
        turso_host = TURSO_DATABASE_URL.replace("libsql://", "")
        DATABASE_URL = f"sqlite+libsql://{turso_host}?authToken={TURSO_AUTH_TOKEN}&secure=true"
        IS_TURSO = True
    except Exception:
        # libsql not available, fall back to SQLite
        pass

if not IS_TURSO:
    # Local development: Use SQLite file
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(exist_ok=True)
    DB_PATH = DATA_DIR / "ohio_fraud_tracker.db"
    DATABASE_URL = f"sqlite:///{DB_PATH}"


# =============================================================================
# ENGINE SETUP
# =============================================================================

def get_engine():
    """Create database engine with appropriate settings"""
    
    if IS_TURSO:
        engine = create_engine(
            DATABASE_URL,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        )
    else:
        # SQLite with optimizations
        engine = create_engine(
            DATABASE_URL,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            connect_args={"check_same_thread": False},
        )
        
        # SQLite performance optimizations
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    
    return engine


# Create engine and session factory
engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# =============================================================================
# SESSION MANAGEMENT
# =============================================================================

def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """Context manager for scripts/jobs (non-FastAPI)."""
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
    """Create all database tables."""
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
