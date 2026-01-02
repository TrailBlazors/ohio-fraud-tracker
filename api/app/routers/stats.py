"""
Statistics and dashboard endpoints
"""

import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models import Award, Recipient, Agency, FraudFlag, CachedStats
from app.schemas import DashboardStats, AwardListItem, AgencySummary

router = APIRouter()

# Simple in-memory cache with TTL
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 300  # 5 minutes


def get_cached(key: str):
    """Get value from cache if not expired."""
    if key in _cache:
        timestamp, value = _cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return value
    return None


def set_cached(key: str, value: Any):
    """Store value in cache with current timestamp."""
    _cache[key] = (time.time(), value)


@router.get("/stats/quick")
async def get_quick_stats(db: Session = Depends(get_db)):
    """
    Fast stats for initial page load - reads from cache table.
    If cache is empty, falls back to computing (slower).
    """
    import json
    
    # Check memory cache first
    cached = get_cached("quick_stats")
    if cached:
        return cached
    
    # Try to read from database cache
    cache_rows = db.query(CachedStats).filter(
        CachedStats.stat_key.in_([
            "total_awards", "total_amount", "total_recipients", 
            "total_flagged", "total_flags_ever", "awards_by_source"
        ])
    ).all()
    
    if cache_rows:
        cache_dict = {row.stat_key: row for row in cache_rows}
        
        total_awards = int(cache_dict.get("total_awards", CachedStats(stat_value=0)).stat_value)
        total_flags_ever = int(cache_dict.get("total_flags_ever", CachedStats(stat_value=0)).stat_value)
        
        if total_flags_ever > 0:
            correlation_status = "run"
        elif total_awards > 0:
            correlation_status = "not_run"
        else:
            correlation_status = "no_data"
        
        awards_by_source = {}
        if "awards_by_source" in cache_dict and cache_dict["awards_by_source"].stat_json:
            awards_by_source = json.loads(cache_dict["awards_by_source"].stat_json)
        
        result = {
            "total_awards": total_awards,
            "total_amount": cache_dict.get("total_amount", CachedStats(stat_value=0)).stat_value,
            "total_recipients": int(cache_dict.get("total_recipients", CachedStats(stat_value=0)).stat_value),
            "total_flagged": int(cache_dict.get("total_flagged", CachedStats(stat_value=0)).stat_value),
            "correlation_status": correlation_status,
            "awards_by_source": awards_by_source,
        }
        set_cached("quick_stats", result)
        return result
    
    # Fallback: compute stats (slow)
    totals = db.query(
        func.count(Award.id).label("total_awards"),
        func.sum(Award.amount).label("total_amount")
    ).first()
    
    total_recipients = db.query(func.count(Recipient.id)).scalar() or 0
    total_flagged = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.is_resolved == False
    ).scalar() or 0
    
    total_flags_ever = db.query(func.count(FraudFlag.id)).scalar() or 0
    total_awards = totals.total_awards or 0
    if total_flags_ever > 0:
        correlation_status = "run"
    elif total_awards > 0:
        correlation_status = "not_run"
    else:
        correlation_status = "no_data"
    
    source_query = db.query(
        Award.source,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).group_by(Award.source).all()
    
    awards_by_source = {
        row.source: {"count": row.count, "total": float(row.total or 0)}
        for row in source_query
    }
    
    result = {
        "total_awards": total_awards,
        "total_amount": float(totals.total_amount or 0),
        "total_recipients": total_recipients,
        "total_flagged": total_flagged,
        "correlation_status": correlation_status,
        "awards_by_source": awards_by_source,
    }
    set_cached("quick_stats", result)
    return result


@router.get("/stats/top-agencies")
async def get_top_agencies(db: Session = Depends(get_db)):
    """Top agencies - reads from cache if available."""
    import json
    
    cached = get_cached("top_agencies")
    if cached:
        return cached
    
    # Try database cache
    cache_row = db.query(CachedStats).filter(CachedStats.stat_key == "top_agencies").first()
    if cache_row and cache_row.stat_json:
        result = json.loads(cache_row.stat_json)
        set_cached("top_agencies", result)
        return result
    
    # Fallback: compute
    agency_query = db.query(
        Agency.id,
        Agency.code,
        Agency.name,
        func.count(Award.id).label("total_awards"),
        func.sum(Award.amount).label("total_amount")
    ).join(Award, Award.agency_id == Agency.id)\
     .group_by(Agency.id)\
     .order_by(desc("total_amount"))\
     .limit(10).all()
    
    result = [
        {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "total_awards": row.total_awards,
            "total_amount": float(row.total_amount or 0)
        }
        for row in agency_query
    ]
    set_cached("top_agencies", result)
    return result


@router.get("/stats/recent-awards")
async def get_recent_awards(db: Session = Depends(get_db)):
    """Recent awards - loaded separately for speed."""
    cached = get_cached("recent_awards")
    if cached:
        return cached
    
    recent_query = db.query(Award, Recipient, Agency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)\
        .order_by(desc(Award.award_date))\
        .limit(10).all()
    
    result = [
        {
            "id": award.id,
            "source": award.source,
            "award_type": award.award_type,
            "amount": award.amount,
            "description": award.description,
            "recipient_name": recipient.name,
            "recipient_city": recipient.city,
            "agency_code": agency.code if agency else None,
            "agency_name": agency.name if agency else None,
            "award_date": award.award_date.isoformat() if award.award_date else None,
            "cfda_number": award.cfda_number
        }
        for award, recipient, agency in recent_query
    ]
    set_cached("recent_awards", result)
    return result


@router.get("/stats/awards-by-type")
async def get_awards_by_type(db: Session = Depends(get_db)):
    """Awards by type breakdown - reads from cache if available."""
    import json
    
    cached = get_cached("awards_by_type")
    if cached:
        return cached
    
    # Try database cache
    cache_row = db.query(CachedStats).filter(CachedStats.stat_key == "awards_by_type").first()
    if cache_row and cache_row.stat_json:
        result = json.loads(cache_row.stat_json)
        set_cached("awards_by_type", result)
        return result
    
    # Fallback: compute
    type_query = db.query(
        Award.award_type,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).group_by(Award.award_type).all()
    
    result = {
        row.award_type: {"count": row.count, "total": float(row.total or 0)}
        for row in type_query
    }
    set_cached("awards_by_type", result)
    return result


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(db: Session = Depends(get_db)):
    """
    Get homepage dashboard statistics
    """
    # Check cache first
    cached = get_cached("dashboard_stats")
    if cached:
        return cached
    
    # Total counts
    total_awards = db.query(func.count(Award.id)).scalar() or 0
    total_amount = db.query(func.sum(Award.amount)).scalar() or 0
    total_recipients = db.query(func.count(Recipient.id)).scalar() or 0
    total_flagged = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.is_resolved == False
    ).scalar() or 0
    
    # Determine correlation status
    total_flags_ever = db.query(func.count(FraudFlag.id)).scalar() or 0
    if total_flags_ever > 0:
        correlation_status = "run"
    elif total_awards > 0:
        correlation_status = "not_run"  # Has data but no correlation done
    else:
        correlation_status = "no_data"
    
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
    
    # Top agencies
    agency_query = db.query(
        Agency.id,
        Agency.code,
        Agency.name,
        func.count(Award.id).label("total_awards"),
        func.sum(Award.amount).label("total_amount")
    ).join(Award, Award.agency_id == Agency.id)\
     .group_by(Agency.id)\
     .order_by(desc("total_amount"))\
     .limit(10).all()
    
    top_agencies = [
        AgencySummary(
            id=row.id,
            code=row.code,
            name=row.name,
            total_awards=row.total_awards,
            total_amount=float(row.total_amount or 0)
        )
        for row in agency_query
    ]
    
    # Recent awards
    recent_query = db.query(Award, Recipient, Agency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)\
        .order_by(desc(Award.award_date))\
        .limit(10).all()
    
    recent_awards = [
        AwardListItem(
            id=award.id,
            source=award.source,
            award_type=award.award_type,
            amount=award.amount,
            description=award.description,
            recipient_name=recipient.name,
            recipient_city=recipient.city,
            agency_code=agency.code if agency else None,
            agency_name=agency.name if agency else None,
            award_date=award.award_date,
            cfda_number=award.cfda_number
        )
        for award, recipient, agency in recent_query
    ]
    
    result = DashboardStats(
        total_awards=total_awards,
        total_amount=float(total_amount),
        total_recipients=total_recipients,
        total_flagged=total_flagged,
        correlation_status=correlation_status,
        awards_by_type=awards_by_type,
        awards_by_source=awards_by_source,
        top_agencies=top_agencies,
        recent_awards=recent_awards
    )
    set_cached("dashboard_stats", result)
    return result


@router.get("/stats/agencies")
async def get_agency_stats(db: Session = Depends(get_db)):
    """
    Get all agencies - fast version for dropdowns.
    Just returns code/name, no expensive award counts.
    """
    # Check memory cache first
    cached = get_cached("agencies_list")
    if cached:
        return cached
    
    # Fast query - no JOINs, no aggregation
    query = db.query(
        Agency.id,
        Agency.code,
        Agency.name
    ).order_by(Agency.code).all()
    
    result = [
        AgencySummary(
            id=row.id,
            code=row.code,
            name=row.name,
            total_awards=0,
            total_amount=0.0
        )
        for row in query
    ]
    set_cached("agencies_list", result)
    return result


@router.get("/stats/by-year")
async def get_stats_by_year(db: Session = Depends(get_db)):
    """
    Get award totals by year
    """
    query = db.query(
        func.strftime("%Y", Award.award_date).label("year"),
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).filter(Award.award_date.isnot(None))\
     .group_by("year")\
     .order_by(desc("year")).all()
    
    return [
        {
            "year": row.year,
            "count": row.count,
            "total": float(row.total or 0)
        }
        for row in query
    ]


@router.get("/stats/by-city")
async def get_stats_by_city(
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """
    Get award totals by city
    """
    query = db.query(
        Recipient.city,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).join(Award, Award.recipient_id == Recipient.id)\
     .filter(Recipient.city.isnot(None))\
     .group_by(Recipient.city)\
     .order_by(desc("total"))\
     .limit(limit).all()
    
    return [
        {
            "city": row.city,
            "count": row.count,
            "total": float(row.total or 0)
        }
        for row in query
    ]


@router.get("/stats/data-coverage")
async def get_data_coverage(db: Session = Depends(get_db)):
    """
    Get data coverage info: year ranges and counts by source
    """
    # Check cache first
    cached = get_cached("data_coverage")
    if cached:
        return cached
    
    from sqlalchemy import extract, func, and_
    
    # Get year ranges and counts by source
    sources = {}
    
    # Get distinct sources
    source_list = db.query(Award.source).distinct().all()
    
    for (source,) in source_list:
        # Get min/max year and count for this source
        stats = db.query(
            func.min(func.strftime("%Y", Award.award_date)).label("min_year"),
            func.max(func.strftime("%Y", Award.award_date)).label("max_year"),
            func.count(Award.id).label("count"),
            func.sum(Award.amount).label("total")
        ).filter(
            Award.source == source,
            Award.award_date.isnot(None)
        ).first()
        
        sources[source] = {
            "min_year": stats.min_year,
            "max_year": stats.max_year,
            "count": stats.count or 0,
            "total": float(stats.total or 0)
        }
    
    result = {
        "sources": sources,
        "total_awards": db.query(func.count(Award.id)).scalar() or 0,
        "total_amount": float(db.query(func.sum(Award.amount)).scalar() or 0)
    }
    set_cached("data_coverage", result)
    return result


@router.get("/stats/data-status")
async def get_data_status(db: Session = Depends(get_db)):
    """
    Get comprehensive data status for the Data Status page.
    Uses cached stats for speed - no expensive GROUP BY queries.
    """
    import json
    
    # Check memory cache first (5 min TTL)
    cached = get_cached("data_status")
    if cached:
        return cached
    
    # Try to load from database cache
    cache_row = db.query(CachedStats).filter(CachedStats.stat_key == "data_status").first()
    if cache_row and cache_row.stat_json:
        result = json.loads(cache_row.stat_json)
        set_cached("data_status", result)
        return result
    
    # Fallback: Build response from other cached stats (no GROUP BY)
    SOURCE_INFO = {
        "usaspending": {
            "name": "USAspending.gov",
            "description": "Federal grants, loans, and contracts",
            "url": "https://usaspending.gov"
        },
        "sba_ppp": {
            "name": "SBA PPP Loans",
            "description": "Paycheck Protection Program loans (COVID-19)",
            "url": "https://data.sba.gov/dataset/ppp-foia"
        },
        "ohio_checkbook": {
            "name": "Ohio Checkbook",
            "description": "Ohio state spending data",
            "url": "https://checkbook.ohio.gov"
        }
    }
    
    # Try to get source stats from awards_by_source cache
    source_cache = db.query(CachedStats).filter(CachedStats.stat_key == "awards_by_source").first()
    source_data = {}
    if source_cache and source_cache.stat_json:
        source_data = json.loads(source_cache.stat_json)
    
    sources = []
    for key, info in SOURCE_INFO.items():
        if key in source_data:
            sources.append({
                "key": key,
                "name": info["name"],
                "description": info["description"],
                "url": info["url"],
                "status": "active",
                "record_count": source_data[key].get("count", 0),
                "total_amount": float(source_data[key].get("total", 0)),
                "date_range": None,  # Skip - requires expensive query
                "by_year": [],
                "by_type": []
            })
        else:
            sources.append({
                "key": key,
                "name": info["name"],
                "description": info["description"],
                "url": info["url"],
                "status": "pending",
                "record_count": 0,
                "total_amount": 0,
                "date_range": None,
                "by_year": [],
                "by_type": []
            })
    
    # Get totals from cache
    totals_cache = db.query(CachedStats).filter(
        CachedStats.stat_key.in_(["total_awards", "total_amount", "total_recipients"])
    ).all()
    totals_dict = {r.stat_key: r.stat_value for r in totals_cache}
    
    # Fast agency count (small table)
    agency_count = db.query(func.count(Agency.id)).scalar() or 0
    
    totals = {
        "total_awards": int(totals_dict.get("total_awards", 0)),
        "total_amount": float(totals_dict.get("total_amount", 0)),
        "total_recipients": int(totals_dict.get("total_recipients", 0)),
        "total_agencies": agency_count,
        "recipients_with_naics": 0,  # Skip expensive query
        "naics_codes_loaded": 0
    }
    
    result = {
        "sources": sources,
        "totals": totals,
        "recipients": {
            "total": totals["total_recipients"],
            "with_naics": 0,
            "with_business_type": 0,
            "by_status": []
        }
    }
    set_cached("data_status", result)
    return result
