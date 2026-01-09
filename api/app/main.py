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
from app.routers import awards, recipients, stats, health, naics, correlation, tips, ai
from app.middleware import BotBlockerMiddleware

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

# Security: Block malicious bot traffic (WordPress scanners, PHP exploits, etc.)
app.add_middleware(BotBlockerMiddleware)

# =============================================================================
# API ROUTERS - Must be first!
# =============================================================================

app.include_router(health.router, tags=["Health"])
app.include_router(stats.router, prefix="/api", tags=["Statistics"])
app.include_router(awards.router, prefix="/api", tags=["Awards"])
app.include_router(recipients.router, prefix="/api", tags=["Recipients"])
app.include_router(naics.router, prefix="/api", tags=["Business Types"])
app.include_router(correlation.router, prefix="/api", tags=["Correlation & Fraud Detection"])
app.include_router(tips.router, prefix="/api", tags=["Tips"])
app.include_router(ai.router, prefix="/api", tags=["AI Analysis"])


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


@app.get("/duplicates")
async def page_duplicates():
    return serve_page("duplicates")


@app.get("/data-status")
async def page_data_status():
    return serve_page("data-status")


@app.get("/politicians")
async def page_politicians():
    return serve_page("politicians")


@app.get("/submit-tip")
async def page_submit_tip():
    return serve_page("submit-tip")


@app.get("/roadmap")
async def page_roadmap():
    return serve_page("roadmap")


@app.get("/search")
async def page_search():
    return serve_page("search")


@app.get("/favicon.svg")
async def favicon_svg():
    """Serve favicon"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Not found")
    favicon_path = STATIC_DIR / "favicon.svg"
    if favicon_path.is_file():
        return FileResponse(favicon_path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/favicon.ico")
async def favicon_ico():
    """Serve favicon.ico (fallback to SVG)"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Not found")
    # Try .ico first, then fall back to .svg
    ico_path = STATIC_DIR / "favicon.ico"
    if ico_path.is_file():
        return FileResponse(ico_path, media_type="image/x-icon")
    svg_path = STATIC_DIR / "favicon.svg"
    if svg_path.is_file():
        return FileResponse(svg_path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/robots.txt")
async def robots_txt():
    """Serve robots.txt for search engines"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Not found")
    robots_path = STATIC_DIR / "robots.txt"
    if robots_path.is_file():
        return FileResponse(robots_path, media_type="text/plain")
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/sitemap.xml")
async def sitemap_xml():
    """Serve sitemap.xml for search engines"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Not found")
    sitemap_path = STATIC_DIR / "sitemap.xml"
    if sitemap_path.is_file():
        return FileResponse(sitemap_path, media_type="application/xml")
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/red-flags")
async def page_red_flags():
    """Serve red-flags index page"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend not available")
    
    index_path = STATIC_DIR / "red-flags" / "index.html"
    if index_path.is_file():
        return FileResponse(index_path, media_type="text/html")
    
    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/red-flags/top-recipients")
async def page_red_flags_top_recipients():
    """Serve top recipients analysis page"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend not available")

    index_path = STATIC_DIR / "red-flags" / "top-recipients" / "index.html"
    if index_path.is_file():
        return FileResponse(index_path, media_type="text/html")

    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/red-flags/funding-before-formation")
async def page_red_flags_funding_before_formation():
    """Serve funding before formation analysis page"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend not available")

    index_path = STATIC_DIR / "red-flags" / "funding-before-formation" / "index.html"
    if index_path.is_file():
        return FileResponse(index_path, media_type="text/html")

    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/recipients")
async def page_recipients():
    return serve_page("recipients")


@app.get("/recipients/view")
async def page_recipient_view():
    """Serve recipient detail page (query param: ?id=xxx)"""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend not available")
    
    # Try the view page
    for path in [
        STATIC_DIR / "recipients" / "view" / "index.html",
        STATIC_DIR / "recipients" / "view.html",
    ]:
        if path.is_file():
            return FileResponse(path, media_type="text/html")
    
    raise HTTPException(status_code=404, detail="Page not found")


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
    """Initialize database and warm cache on startup (only if cache is empty)"""
    try:
        init_db()
        db_info = get_db_info()
        print(f"✓ API started with {db_info['type']} database")
        if STATIC_DIR.exists():
            print(f"✓ Serving frontend from {STATIC_DIR}")
        else:
            print(f"⚠ Static directory not found: {STATIC_DIR}")

        # Check if cache already exists before warming
        try:
            from app.database import SessionLocal
            from app.models import CachedStats
            db = SessionLocal()
            try:
                # Check for key cached stats that indicate cache is populated
                cache_count = db.query(CachedStats).filter(
                    CachedStats.stat_key.in_(['total_awards', 'top_recipients_20', 'awards_by_source'])
                ).count()

                if cache_count >= 3:
                    print(f"")
                    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    print(f"⚡ FAST DEPLOY: Cache already populated ({cache_count} keys)")
                    print(f"   Skipping cache warmup - using existing cached stats")
                    print(f"   To force refresh: GET /api/stats/cache/warm")
                    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    print(f"")
                else:
                    # Cache is empty or incomplete - warm it
                    print(f"⏳ Cache incomplete ({cache_count}/3 keys), warming cache (this may take a minute)...")
                    from app.routers.stats import warm_cache
                    result = await warm_cache(db)
                    print(f"✓ Cache warmed: {result.get('cached', {})}")
            finally:
                db.close()
        except Exception as cache_err:
            print(f"⚠ Cache check/warming failed (non-fatal): {cache_err}")

    except Exception as e:
        print(f"✗ Startup error: {e}")
        import traceback
        traceback.print_exc()


@app.on_event("shutdown")
async def shutdown_event():
    print("API shutting down")
