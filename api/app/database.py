"""
Database connection and session management.

Uses PostgreSQL (Neon) for all environments.
"""

import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

# Handle Neon pooler connection string
if "channel_binding=require" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("&channel_binding=require", "")

# =============================================================================
# ENGINE SETUP
# =============================================================================

engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

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
    print("Database initialized: PostgreSQL (Neon)")


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
        "type": "postgresql",
        "is_production": True,
    }
