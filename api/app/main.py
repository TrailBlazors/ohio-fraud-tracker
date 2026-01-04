"""
Ohio Fraud Tracker - FastAPI Application

REST API for querying government funding data.
"""

import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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
# STATIC FILES (Frontend)
# =============================================================================

# Check if static directory exists (production build)
STATIC_DIR = Path("/app/static")
if STATIC_DIR.exists():
    # Serve static assets
    app.mount("/_assets", StaticFiles(directory=STATIC_DIR / "_assets"), name="assets")
    
    # Catch-all route for frontend pages
    @app.get("/{path:path}")
    async def serve_frontend(request: Request, path: str):
        # Skip API routes
        if path.startswith("api/") or path in ["docs", "redoc", "openapi.json", "health"]:
            return None
        
        # Try to serve the exact file
        file_path = STATIC_DIR / path
        if file_path.is_file():
            return FileResponse(file_path)
        
        # Try with .html extension
        html_path = STATIC_DIR / f"{path}.html"
        if html_path.is_file():
            return FileResponse(html_path)
        
        # Try index.html in directory
        index_path = STATIC_DIR / path / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        
        # Fallback to root index.html
        root_index = STATIC_DIR / "index.html"
        if root_index.is_file():
            return FileResponse(root_index)
        
        return {"error": "Not found"}

    @app.get("/")
    async def serve_index():
        index_path = STATIC_DIR / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return {"name": "Ohio Fraud Tracker API", "docs": "/docs"}


# =============================================================================
# STARTUP / SHUTDOWN
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    try:
        init_db()
        db_info = get_db_info()
        print(f"API started with {db_info['type']} database")
        if STATIC_DIR.exists():
            print(f"Serving frontend from {STATIC_DIR}")
    except Exception as e:
        print(f"Database initialization error: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("API shutting down")
