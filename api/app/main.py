"""
Ohio Fraud Tracker - FastAPI Application

REST API for querying government funding data.
"""

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
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


def serve_page(page_name: str):
    """Helper to serve a frontend page"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend not available")
    
    # Try page/index.html (Astro's default output)
    index_path = STATIC_DIR / page_name / "index.html"
    if index_path.is_file():
        return FileResponse(index_path, media_type="text/html")
    
    # Try page.html
    html_path = STATIC_DIR / f"{page_name}.html"
    if html_path.is_file():
        return FileResponse(html_path, media_type="text/html")
    
    raise HTTPException(status_code=404, detail="Page not found")


# =============================================================================
# FRONTEND ROUTES
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
async def page_about():
    return serve_page("about")


@app.get("/grants")
async def page_grants():
    return serve_page("grants")


@app.get("/loans")
async def page_loans():
    return serve_page("loans")


@app.get("/flagged")
async def page_flagged():
    return serve_page("flagged")


@app.get("/data-status")
async def page_data_status():
    return serve_page("data-status")


@app.get("/politicians")
async def page_politicians():
    return serve_page("politicians")


@app.get("/recipients")
async def page_recipients():
    return serve_page("recipients")


@app.get("/recipients/{recipient_id}")
async def page_recipient_detail(recipient_id: str):
    """Serve recipient detail page (client-side rendered)"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend not available")
    
    # Astro builds dynamic routes - try various paths
    for path in [
        STATIC_DIR / "recipients" / "[id]" / "index.html",
        STATIC_DIR / "recipients" / "[id].html",
        STATIC_DIR / "recipients" / "index.html",
    ]:
        if path.is_file():
            return FileResponse(path, media_type="text/html")
    
    raise HTTPException(status_code=404, detail="Page not found")


# =============================================================================
# STATIC ASSETS - Mount after explicit routes
# =============================================================================

if STATIC_DIR.exists():
    assets_dir = STATIC_DIR / "_assets"
    if assets_dir.exists():
        app.mount("/_assets", StaticFiles(directory=assets_dir), name="assets")


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
        else:
            print(f"⚠ Static directory not found: {STATIC_DIR}")
    except Exception as e:
        print(f"✗ Startup error: {e}")
        import traceback
        traceback.print_exc()


@app.on_event("shutdown")
async def shutdown_event():
    print("API shutting down")
