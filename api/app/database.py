"""
Database connection and session management.

Supports both local SQLite (development) and PostgreSQL/Neon (production).
"""

import os
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

# Load .env from project root (parent of api/) - only for local dev
# In Vercel, env vars are injected directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv("DATABASE_URL")

IS_POSTGRES = False

if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
    IS_POSTGRES = True
    # Handle Neon pooler connection string
    if "channel_binding=require" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("&channel_binding=require", "")
    # Use psycopg3 driver (not psycopg2)
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
else:
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
    
    if IS_POSTGRES:
        engine = create_engine(
            DATABASE_URL,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
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
    print(f"Database initialized: {'PostgreSQL (Neon)' if IS_POSTGRES else 'SQLite'}")


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
        "type": "postgresql" if IS_POSTGRES else "sqlite",
        "is_production": IS_POSTGRES,
    }
