"""
Statistics and dashboard endpoints
"""

import json
import time
from typing import Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text

from app.database import get_db
from app.models import Award, Recipient, Agency, FraudFlag, CachedStats
from app.schemas import DashboardStats, AwardListItem, AgencySummary

router = APIRouter()

# Simple in-memory cache with TTL
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 86400  # 24 hours - data doesn't change frequently


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


# =============================================================================
# CACHE WARMING ENDPOINT
# =============================================================================

@router.get("/stats/cache/warm")
async def warm_cache(db: Session = Depends(get_db)):
    """
    Pre-compute and cache expensive stats.
    Call this after deployment or via cron to keep the cache warm.
    """
    results = {}
    
    # 1. Top recipients (most expensive query)
    try:
        top_results = db.execute(text("""
            SELECT 
                r.id, r.name, r.city, r.state, r.business_status,
                COUNT(a.id) as award_count,
                SUM(a.amount) as total_amount
            FROM recipients r
            INNER JOIN awards a ON a.recipient_id = r.id
            GROUP BY r.id
            ORDER BY total_amount DESC
            LIMIT 20
        """)).fetchall()
        
        items = []
        for i, row in enumerate(top_results, 1):
            items.append({
                "rank": i,
                "id": row.id,
                "name": row.name,
                "city": row.city,
                "state": row.state,
                "business_status": row.business_status,
                "award_count": row.award_count,
                "total_amount": float(row.total_amount) if row.total_amount else 0
            })
        
        top_data = {"items": items, "count": len(items)}
        
        # Update cache
        cache_key = "top_recipients_20"
        cached = db.query(CachedStats).filter(CachedStats.stat_key == cache_key).first()
        if cached:
            cached.stat_json = json.dumps(top_data)
            cached.updated_at = datetime.utcnow()
        else:
            db.add(CachedStats(stat_key=cache_key, stat_value=20, stat_json=json.dumps(top_data)))
        
        results["top_recipients"] = "cached"
    except Exception as e:
        results["top_recipients"] = f"error: {str(e)}"
    
    # 2. Quick stats
    try:
        totals = db.query(
            func.count(Award.id).label("total_awards"),
            func.sum(Award.amount).label("total_amount")
        ).first()
        
        total_recipients = db.query(func.count(Recipient.id)).scalar() or 0
        total_flagged = db.query(func.count(FraudFlag.id)).filter(FraudFlag.is_resolved == False).scalar() or 0
        total_flags_ever = db.query(func.count(FraudFlag.id)).scalar() or 0
        
        # Save individual stats
        stats_to_cache = [
            ("total_awards", totals.total_awards or 0),
            ("total_amount", float(totals.total_amount or 0)),
            ("total_recipients", total_recipients),
            ("total_flagged", total_flagged),
            ("total_flags_ever", total_flags_ever),
        ]
        
        for key, value in stats_to_cache:
            cached = db.query(CachedStats).filter(CachedStats.stat_key == key).first()
            if cached:
                cached.stat_value = value
                cached.updated_at = datetime.utcnow()
            else:
                db.add(CachedStats(stat_key=key, stat_value=value))
        
        results["quick_stats"] = "cached"
    except Exception as e:
        results["quick_stats"] = f"error: {str(e)}"
    
    # 3. Awards by source
    try:
        source_query = db.query(
            Award.source,
            func.count(Award.id).label("count"),
            func.sum(Award.amount).label("total")
        ).group_by(Award.source).all()
        
        source_data = {
            row.source: {"count": row.count, "total": float(row.total or 0)}
            for row in source_query
        }
        
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "awards_by_source").first()
        if cached:
            cached.stat_json = json.dumps(source_data)
            cached.updated_at = datetime.utcnow()
        else:
            db.add(CachedStats(stat_key="awards_by_source", stat_value=len(source_data), stat_json=json.dumps(source_data)))
        
        results["awards_by_source"] = "cached"
    except Exception as e:
        results["awards_by_source"] = f"error: {str(e)}"
    
    # 4. Top agencies
    try:
        agency_query = db.query(
            Agency.id, Agency.code, Agency.name,
            func.count(Award.id).label("total_awards"),
            func.sum(Award.amount).label("total_amount")
        ).join(Award, Award.agency_id == Agency.id)\
         .group_by(Agency.id)\
         .order_by(desc("total_amount"))\
         .limit(10).all()
        
        agency_data = [
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "total_awards": row.total_awards,
                "total_amount": float(row.total_amount or 0)
            }
            for row in agency_query
        ]
        
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "top_agencies").first()
        if cached:
            cached.stat_json = json.dumps(agency_data)
            cached.updated_at = datetime.utcnow()
        else:
            db.add(CachedStats(stat_key="top_agencies", stat_value=len(agency_data), stat_json=json.dumps(agency_data)))
        
        results["top_agencies"] = "cached"
    except Exception as e:
        results["top_agencies"] = f"error: {str(e)}"
    
    # 5. Funding by county (expensive geo query)
    try:
        city_results = db.execute(text("""
            SELECT 
                UPPER(r.city) as city,
                COUNT(DISTINCT r.id) as recipient_count,
                COUNT(a.id) as award_count,
                COALESCE(SUM(a.amount), 0) as total_amount
            FROM recipients r
            LEFT JOIN awards a ON a.recipient_id = r.id
            WHERE r.city IS NOT NULL AND r.city != '' AND r.state = 'OH'
            GROUP BY UPPER(r.city)
            ORDER BY total_amount DESC
        """)).fetchall()
        
        city_to_county = {
            "COLUMBUS": "FRANKLIN", "CLEVELAND": "CUYAHOGA", "CINCINNATI": "HAMILTON",
            "TOLEDO": "LUCAS", "AKRON": "SUMMIT", "DAYTON": "MONTGOMERY",
            "PARMA": "CUYAHOGA", "CANTON": "STARK", "YOUNGSTOWN": "MAHONING",
            "LORAIN": "LORAIN", "HAMILTON": "BUTLER", "SPRINGFIELD": "CLARK",
            "KETTERING": "MONTGOMERY", "ELYRIA": "LORAIN", "LAKEWOOD": "CUYAHOGA",
            "DUBLIN": "FRANKLIN", "FAIRFIELD": "BUTLER", "FINDLAY": "HANCOCK",
            "WARREN": "TRUMBULL", "LIMA": "ALLEN", "WESTERVILLE": "FRANKLIN",
            "NEWARK": "LICKING", "MANSFIELD": "RICHLAND", "MENTOR": "LAKE",
            "BEAVERCREEK": "GREENE", "CLEVELAND HEIGHTS": "CUYAHOGA", "STRONGSVILLE": "CUYAHOGA",
            "CUYAHOGA FALLS": "SUMMIT", "MIDDLETOWN": "BUTLER", "EUCLID": "CUYAHOGA",
            "GROVE CITY": "FRANKLIN", "REYNOLDSBURG": "FRANKLIN", "STOW": "SUMMIT",
            "DELAWARE": "DELAWARE", "BRUNSWICK": "MEDINA", "UPPER ARLINGTON": "FRANKLIN",
            "GAHANNA": "FRANKLIN", "WESTLAKE": "CUYAHOGA", "NORTH OLMSTED": "CUYAHOGA",
            "FAIRBORN": "GREENE", "MASSILLON": "STARK", "MASON": "WARREN",
            "HUBER HEIGHTS": "MONTGOMERY", "MARION": "MARION",
        }
        
        county_totals = {}
        for row in city_results:
            city = row[0]
            county = city_to_county.get(city)
            if county:
                if county not in county_totals:
                    county_totals[county] = {
                        "county": county, "recipient_count": 0,
                        "award_count": 0, "total_amount": 0, "cities": []
                    }
                county_totals[county]["recipient_count"] += row[1]
                county_totals[county]["award_count"] += row[2]
                county_totals[county]["total_amount"] += float(row[3])
                if float(row[3]) > 0:
                    county_totals[county]["cities"].append({
                        "city": city.title(), "amount": float(row[3])
                    })
        
        counties = sorted(county_totals.values(), key=lambda x: x["total_amount"], reverse=True)
        for county in counties:
            county["cities"] = sorted(county["cities"], key=lambda x: x["amount"], reverse=True)[:5]
        
        county_data = {"counties": counties, "total_counties": len(counties)}
        
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "funding_by_county").first()
        if cached:
            cached.stat_json = json.dumps(county_data)
            cached.updated_at = datetime.utcnow()
        else:
            db.add(CachedStats(stat_key="funding_by_county", stat_value=len(counties), stat_json=json.dumps(county_data)))
        
        results["funding_by_county"] = "cached"
    except Exception as e:
        results["funding_by_county"] = f"error: {str(e)}"
    
    try:
        db.commit()
        # Clear memory cache so next request gets fresh data
        _cache.clear()
    except Exception as e:
        db.rollback()
        results["commit"] = f"error: {str(e)}"
    
    return {
        "status": "ok",
        "cached": results,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/stats/db/optimize")
async def optimize_database(db: Session = Depends(get_db)):
    """
    Add performance indexes and run ANALYZE.
    Call this once after deployment or after major data imports.
    """
    results = {}
    
    indexes = [
        ("ix_awards_recipient_amount", "CREATE INDEX IF NOT EXISTS ix_awards_recipient_amount ON awards(recipient_id, amount)"),
        ("ix_fraud_flags_unresolved", "CREATE INDEX IF NOT EXISTS ix_fraud_flags_unresolved ON fraud_flags(is_resolved, recipient_id)"),
        ("ix_fraud_flags_severity", "CREATE INDEX IF NOT EXISTS ix_fraud_flags_severity ON fraud_flags(severity, created_at DESC)"),
        ("ix_awards_recipient_full", "CREATE INDEX IF NOT EXISTS ix_awards_recipient_full ON awards(recipient_id, id, amount)"),
        ("ix_awards_agency_amount", "CREATE INDEX IF NOT EXISTS ix_awards_agency_amount ON awards(agency_id, amount)"),
        ("ix_awards_source_amount", "CREATE INDEX IF NOT EXISTS ix_awards_source_amount ON awards(source, amount)"),
        ("ix_recipients_city_state", "CREATE INDEX IF NOT EXISTS ix_recipients_city_state ON recipients(city, state)"),
        ("ix_awards_recipient_date_amount", "CREATE INDEX IF NOT EXISTS ix_awards_recipient_date_amount ON awards(recipient_id, award_date, amount)"),
        ("ix_fraud_flags_type", "CREATE INDEX IF NOT EXISTS ix_fraud_flags_type ON fraud_flags(flag_type, is_resolved)"),
    ]
    
    for name, sql in indexes:
        try:
            db.execute(text(sql))
            db.commit()
            results[name] = "created"
        except Exception as e:
            results[name] = f"error: {str(e)}"
    
    # Run ANALYZE
    try:
        db.execute(text("ANALYZE"))
        db.commit()
        results["analyze"] = "complete"
    except Exception as e:
        results["analyze"] = f"error: {str(e)}"
    
    return {
        "status": "ok",
        "indexes": results,
        "timestamp": datetime.utcnow().isoformat()
    }


# =============================================================================
# QUICK STATS (FAST)
# =============================================================================

@router.get("/stats/quick")
async def get_quick_stats(db: Session = Depends(get_db)):
    """
    Fast stats for initial page load - reads from cache table.
    """
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
    
    # Only get awards that have dates
    recent_query = db.query(Award, Recipient, Agency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)\
        .filter(Award.award_date.isnot(None))\
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
    """Get homepage dashboard statistics"""
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
        correlation_status = "not_run"
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
    """Get all agencies - fast version for dropdowns."""
    cached = get_cached("agencies_list")
    if cached:
        return cached
    
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
    """Get award totals by year"""
    query = db.query(
        func.strftime("%Y", Award.award_date).label("year"),
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).filter(Award.award_date.isnot(None))\
     .group_by("year")\
     .order_by(desc("year")).all()
    
    return [
        {"year": row.year, "count": row.count, "total": float(row.total or 0)}
        for row in query
    ]


@router.get("/stats/by-city")
async def get_stats_by_city(limit: int = 20, db: Session = Depends(get_db)):
    """Get award totals by city"""
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
        {"city": row.city, "count": row.count, "total": float(row.total or 0)}
        for row in query
    ]


@router.get("/stats/data-coverage")
async def get_data_coverage(db: Session = Depends(get_db)):
    """Get data coverage info: year ranges and counts by source"""
    cached = get_cached("data_coverage")
    if cached:
        return cached
    
    sources = {}
    source_list = db.query(Award.source).distinct().all()
    
    for (source,) in source_list:
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
    """Get comprehensive data status for the Data Status page."""
    cached = get_cached("data_status")
    if cached:
        return cached
    
    # Try to load from database cache
    cache_row = db.query(CachedStats).filter(CachedStats.stat_key == "data_status").first()
    if cache_row and cache_row.stat_json:
        result = json.loads(cache_row.stat_json)
        set_cached("data_status", result)
        return result
    
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
                "date_range": None,
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
    
    totals_cache = db.query(CachedStats).filter(
        CachedStats.stat_key.in_([
            "total_awards", "total_amount", "total_recipients",
            "recipients_with_naics", "recipients_with_business_type"
        ])
    ).all()
    totals_dict = {r.stat_key: r.stat_value for r in totals_cache}
    
    status_cache = db.query(CachedStats).filter(CachedStats.stat_key == "recipients_by_status").first()
    recipients_by_status = []
    if status_cache and status_cache.stat_json:
        recipients_by_status = json.loads(status_cache.stat_json)
    
    agency_count = db.query(func.count(Agency.id)).scalar() or 0
    
    total_recipients = int(totals_dict.get("total_recipients", 0))
    recipients_with_naics = int(totals_dict.get("recipients_with_naics", 0))
    recipients_with_business_type = int(totals_dict.get("recipients_with_business_type", 0))
    
    totals = {
        "total_awards": int(totals_dict.get("total_awards", 0)),
        "total_amount": float(totals_dict.get("total_amount", 0)),
        "total_recipients": total_recipients,
        "total_agencies": agency_count,
        "recipients_with_naics": recipients_with_naics,
        "naics_codes_loaded": 0
    }
    
    result = {
        "sources": sources,
        "totals": totals,
        "recipients": {
            "total": total_recipients,
            "with_naics": recipients_with_naics,
            "with_business_type": recipients_with_business_type,
            "by_status": recipients_by_status
        }
    }
    set_cached("data_status", result)
    return result


@router.get("/stats/geo/funding-by-county")
async def get_funding_by_county(db: Session = Depends(get_db)):
    """Get total funding aggregated by Ohio county. Uses database cache."""
    
    # Check memory cache first (5 min TTL)
    cached = get_cached("funding_by_county")
    if cached:
        return cached
    
    # Check database cache (24 hour TTL)
    cache_row = db.query(CachedStats).filter(CachedStats.stat_key == "funding_by_county").first()
    if cache_row and cache_row.stat_json:
        if cache_row.updated_at and cache_row.updated_at > datetime.utcnow() - timedelta(hours=24):
            result = json.loads(cache_row.stat_json)
            set_cached("funding_by_county", result)
            return result
    
    # Cache miss - compute (slow)
    city_results = db.execute(text("""
        SELECT 
            UPPER(r.city) as city,
            COUNT(DISTINCT r.id) as recipient_count,
            COUNT(a.id) as award_count,
            COALESCE(SUM(a.amount), 0) as total_amount
        FROM recipients r
        LEFT JOIN awards a ON a.recipient_id = r.id
        WHERE r.city IS NOT NULL AND r.city != '' AND r.state = 'OH'
        GROUP BY UPPER(r.city)
        ORDER BY total_amount DESC
    """)).fetchall()
    
    city_to_county = {
        "COLUMBUS": "FRANKLIN", "CLEVELAND": "CUYAHOGA", "CINCINNATI": "HAMILTON",
        "TOLEDO": "LUCAS", "AKRON": "SUMMIT", "DAYTON": "MONTGOMERY",
        "PARMA": "CUYAHOGA", "CANTON": "STARK", "YOUNGSTOWN": "MAHONING",
        "LORAIN": "LORAIN", "HAMILTON": "BUTLER", "SPRINGFIELD": "CLARK",
        "KETTERING": "MONTGOMERY", "ELYRIA": "LORAIN", "LAKEWOOD": "CUYAHOGA",
        "DUBLIN": "FRANKLIN", "FAIRFIELD": "BUTLER", "FINDLAY": "HANCOCK",
        "WARREN": "TRUMBULL", "LIMA": "ALLEN", "WESTERVILLE": "FRANKLIN",
        "NEWARK": "LICKING", "MANSFIELD": "RICHLAND", "MENTOR": "LAKE",
        "BEAVERCREEK": "GREENE", "CLEVELAND HEIGHTS": "CUYAHOGA", "STRONGSVILLE": "CUYAHOGA",
        "CUYAHOGA FALLS": "SUMMIT", "MIDDLETOWN": "BUTLER", "EUCLID": "CUYAHOGA",
        "GROVE CITY": "FRANKLIN", "REYNOLDSBURG": "FRANKLIN", "STOW": "SUMMIT",
        "DELAWARE": "DELAWARE", "BRUNSWICK": "MEDINA", "UPPER ARLINGTON": "FRANKLIN",
        "GAHANNA": "FRANKLIN", "WESTLAKE": "CUYAHOGA", "NORTH OLMSTED": "CUYAHOGA",
        "FAIRBORN": "GREENE", "MASSILLON": "STARK", "MASON": "WARREN",
        "HUBER HEIGHTS": "MONTGOMERY", "MARION": "MARION",
    }
    
    county_totals = {}
    for row in city_results:
        city = row[0]
        county = city_to_county.get(city)
        if county:
            if county not in county_totals:
                county_totals[county] = {
                    "county": county, "recipient_count": 0,
                    "award_count": 0, "total_amount": 0, "cities": []
                }
            county_totals[county]["recipient_count"] += row[1]
            county_totals[county]["award_count"] += row[2]
            county_totals[county]["total_amount"] += float(row[3])
            if float(row[3]) > 0:
                county_totals[county]["cities"].append({
                    "city": city.title(), "amount": float(row[3])
                })
    
    counties = sorted(county_totals.values(), key=lambda x: x["total_amount"], reverse=True)
    for county in counties:
        county["cities"] = sorted(county["cities"], key=lambda x: x["amount"], reverse=True)[:5]
    
    result = {"counties": counties, "total_counties": len(counties)}
    
    # Save to memory cache
    set_cached("funding_by_county", result)
    
    # Save to database cache
    if cache_row:
        cache_row.stat_json = json.dumps(result)
        cache_row.updated_at = datetime.utcnow()
    else:
        db.add(CachedStats(stat_key="funding_by_county", stat_value=len(counties), stat_json=json.dumps(result)))
    
    try:
        db.commit()
    except:
        db.rollback()
    
    return result
