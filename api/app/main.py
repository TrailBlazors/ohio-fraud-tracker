"""
Ohio Fraud Tracker - FastAPI Application

REST API for querying government funding data.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import get_db_info, init_db
from app.routers import awards, recipients, stats, health, naics, correlation

# =============================================================================
# APP CONFIGURATION
# =============================================================================

app = FastAPI(
    title="Ohio Fraud Tracker API",
    description="Track federal grants, loans, and contracts in Ohio",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration - allow frontend to call API
# Using allow_origins=["*"] since this is a public API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Must be False when using "*"
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTERS
# =============================================================================

app.include_router(health.router, tags=["Health"])
app.include_router(stats.router, prefix="/api", tags=["Statistics"])
app.include_router(awards.router, prefix="/api", tags=["Awards"])
app.include_router(recipients.router, prefix="/api", tags=["Recipients"])
app.include_router(naics.router, prefix="/api", tags=["Business Types"])
app.include_router(correlation.router, prefix="/api", tags=["Correlation & Fraud Detection"])


# =============================================================================
# STARTUP / SHUTDOWN
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    # Only create tables if they don't exist
    try:
        init_db()
        db_info = get_db_info()
        print(f"API started with {db_info['type']} database")
    except Exception as e:
        print(f"Database initialization error: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("API shutting down")


# =============================================================================
# ROOT ENDPOINT
# =============================================================================

@app.get("/")
async def root():
    """API root - basic info"""
    return {
        "name": "Ohio Fraud Tracker API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
