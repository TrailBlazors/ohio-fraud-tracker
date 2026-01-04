"""
Health check and admin endpoints
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text, func

from app.database import get_db, get_db_info
from app.schemas import HealthCheck
from app.models import Award, Recipient, Agency, FraudFlag, CachedStats

router = APIRouter()


@router.get("/health", response_model=HealthCheck)
async def health_check(db: Session = Depends(get_db)):
    """
    Check API and database health
    """
    db_info = get_db_info()
    
    # Test database connection
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return HealthCheck(
        status="healthy" if db_status == "connected" else "degraded",
        database=f"{db_info['type']} ({db_status})",
        version="0.1.0"
    )


def _refresh_cache(db: Session):
    """Refresh cached stats in database."""
    stats = {}
    
    # Basic counts
    stats["total_awards"] = db.query(func.count(Award.id)).scalar() or 0
    stats["total_amount"] = float(db.query(func.sum(Award.amount)).scalar() or 0)
    stats["total_recipients"] = db.query(func.count(Recipient.id)).scalar() or 0
    stats["total_flagged"] = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.is_resolved == False
    ).scalar() or 0
    stats["total_flags_ever"] = db.query(func.count(FraudFlag.id)).scalar() or 0
    
    # Awards by source
    source_query = db.query(
        Award.source,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).group_by(Award.source).all()
    
    awards_by_source = {
        row.source: {"count": row.count, "total": float(row.total or 0)}
        for row in source_query
    }
    stats["awards_by_source"] = json.dumps(awards_by_source)
    
    # Awards by type
    type_query = db.query(
        Award.award_type,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).group_by(Award.award_type).all()
    
    awards_by_type = {
        row.award_type: {"count": row.count, "total": float(row.total or 0)}
        for row in type_query
    }
    stats["awards_by_type"] = json.dumps(awards_by_type)
    
    # Top agencies
    agency_query = db.query(
        Agency.id,
        Agency.code,
        Agency.name,
        func.count(Award.id).label("total_awards"),
        func.sum(Award.amount).label("total_amount")
    ).join(Award, Award.agency_id == Agency.id)\
     .group_by(Agency.id)\
     .order_by(func.sum(Award.amount).desc())\
     .limit(10).all()
    
    top_agencies = [
        {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "total_awards": row.total_awards,
            "total_amount": float(row.total_amount or 0)
        }
        for row in agency_query
    ]
    stats["top_agencies"] = json.dumps(top_agencies)
    
    # Save to database
    for key, value in stats.items():
        existing = db.query(CachedStats).filter(CachedStats.stat_key == key).first()
        
        if isinstance(value, str):  # JSON
            if existing:
                existing.stat_json = value
                existing.stat_value = 0
                existing.updated_at = datetime.utcnow()
            else:
                db.add(CachedStats(stat_key=key, stat_value=0, stat_json=value))
        else:  # Numeric
            if existing:
                existing.stat_value = value
                existing.stat_json = None
                existing.updated_at = datetime.utcnow()
            else:
                db.add(CachedStats(stat_key=key, stat_value=value))
    
    db.commit()
    return len(stats)


@router.post("/admin/refresh-cache")
async def refresh_cache(db: Session = Depends(get_db)):
    """
    Manually refresh the cached stats.
    """
    try:
        count = _refresh_cache(db)
        return {
            "success": True,
            "message": f"Refreshed {count} cached stats",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/admin/cache-status")
async def cache_status(db: Session = Depends(get_db)):
    """
    Check the status of cached stats.
    """
    cache_rows = db.query(CachedStats).all()
    
    if not cache_rows:
        return {
            "populated": False,
            "message": "Cache is empty. POST to /admin/refresh-cache to populate.",
            "stats": []
        }
    
    stats = []
    for row in cache_rows:
        stats.append({
            "key": row.stat_key,
            "value": row.stat_value if row.stat_value else "(JSON)",
            "updated_at": row.updated_at.isoformat() if row.updated_at else None
        })
    
    oldest = min((row.updated_at for row in cache_rows if row.updated_at), default=None)
    
    return {
        "populated": True,
        "count": len(cache_rows),
        "oldest_update": oldest.isoformat() if oldest else None,
        "stats": stats
    }
