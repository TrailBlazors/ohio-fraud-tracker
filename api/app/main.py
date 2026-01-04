"""
Ohio Fraud Tracker - FastAPI Application

REST API for querying government funding data.
"""

import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

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

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API ROUTERS - Must be first!
# =============================================================================

app.include_router(health.router, tags=["Health"])
app.include_router(stats.router, prefix="/api", tags=["Statistics"])
app.include_router(awards.router, prefix="/api", tags=["Awards"])
app.include_router(recipients.router, prefix="/api", tags=["Recipients"])
app.include_router(naics.router, prefix="/api", tags=["Business Types"])
app.include_router(correlation.router, prefix="/api", tags=["Correlation & Fraud Detection"])


# =============================================================================
# STATIC FILES CONFIGURATION
# =============================================================================

STATIC_DIR = Path("/app/static")
FRONTEND_PAGES = {"about", "grants", "loans", "recipients", "flagged", "data-status", "politicians"}


# =============================================================================
# FRONTEND ROUTES - Explicit, non-conflicting with API
# =============================================================================

@app.get("/")
async def serve_index():
    """Serve the main index.html page"""
    if STATIC_DIR.exists():
        index_path = STATIC_DIR / "index.html"
        if index_path.is_file():
            return FileResponse(index_path, media_type="text/html")
    return {"name": "Ohio Fraud Tracker API", "docs": "/docs"}


@app.get("/about")
@app.get("/grants")
@app.get("/loans") 
@app.get("/flagged")
@app.get("/data-status")
@app.get("/politicians")
async def serve_frontend_page(request: Request):
    """Serve frontend pages"""
    page = request.url.path.strip("/")
    if STATIC_DIR.exists():
        # Try page/index.html (Astro's default output)
        index_path = STATIC_DIR / page / "index.html"
        if index_path.is_file():
            return FileResponse(index_path, media_type="text/html")
        # Try page.html
        html_path = STATIC_DIR / f"{page}.html"
        if html_path.is_file():
            return FileResponse(html_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/recipients")
async def serve_recipients_list():
    """Serve recipients list page"""
    if STATIC_DIR.exists():
        for path in [STATIC_DIR / "recipients" / "index.html", STATIC_DIR / "recipients.html"]:
            if path.is_file():
                return FileResponse(path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/recipients/{recipient_id}")
async def serve_recipient_detail(recipient_id: str):
    """Serve recipient detail page (client-side rendered)"""
    if STATIC_DIR.exists():
        # Astro builds dynamic routes to a single file
        for path in [
            STATIC_DIR / "recipients" / "[id]" / "index.html",
            STATIC_DIR / "recipients" / "[id].html",
            STATIC_DIR / "recipients" / "index.html",  # Fallback
        ]:
            if path.is_file():
                return FileResponse(path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Page not found")


# =============================================================================
# STATIC ASSETS - Mount after explicit routes
# =============================================================================

if STATIC_DIR.exists():
    # Serve _assets directory for JS/CSS
    assets_dir = STATIC_DIR / "_assets"
    if assets_dir.exists():
        app.mount("/_assets", StaticFiles(directory=assets_dir), name="assets")
    
    # Serve other static files (favicon, etc.)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_files")


# =============================================================================
# STARTUP / SHUTDOWN
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    try:
        init_db()
        db_info = get_db_info()
        print(f"✓ API started with {db_info['type']} database")
        if STATIC_DIR.exists():
            print(f"✓ Serving frontend from {STATIC_DIR}")
            print(f"  Contents: {[p.name for p in STATIC_DIR.iterdir()]}")
        else:
            print(f"✗ Static directory not found: {STATIC_DIR}")
    except Exception as e:
        print(f"✗ Database initialization error: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("API shutting down")
