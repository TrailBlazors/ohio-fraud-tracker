"""
Statistics and dashboard endpoints
"""

import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models import Award, Recipient, Agency, FraudFlag
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
    Get all agencies with award counts
    """
    query = db.query(
        Agency.id,
        Agency.code,
        Agency.name,
        func.count(Award.id).label("total_awards"),
        func.sum(Award.amount).label("total_amount")
    ).outerjoin(Award, Award.agency_id == Agency.id)\
     .group_by(Agency.id)\
     .order_by(desc("total_amount")).all()
    
    return [
        AgencySummary(
            id=row.id,
            code=row.code,
            name=row.name,
            total_awards=row.total_awards or 0,
            total_amount=float(row.total_amount or 0)
        )
        for row in query
    ]


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
    Shows all sources, record counts, date ranges, and import history.
    """
    # Check cache first
    cached = get_cached("data_status")
    if cached:
        return cached
    
    from app.models import DataImport, NaicsCode
    
    # Source metadata (descriptions and URLs)
    SOURCE_INFO = {
        "usaspending": {
            "name": "USAspending.gov",
            "description": "Federal grants, loans, and contracts",
            "url": "https://usaspending.gov",
            "types": ["grants", "loans", "contracts"]
        },
        "sba_ppp": {
            "name": "SBA PPP Loans",
            "description": "Paycheck Protection Program loans (COVID-19)",
            "url": "https://data.sba.gov/dataset/ppp-foia",
            "types": ["loans"]
        },
        "sba_eidl": {
            "name": "SBA EIDL Loans",
            "description": "Economic Injury Disaster Loans",
            "url": "https://data.sba.gov",
            "types": ["loans"]
        },
        "ohio_checkbook": {
            "name": "Ohio Checkbook",
            "description": "Ohio state spending data",
            "url": "https://checkbook.ohio.gov",
            "types": ["state_spending"]
        },
        "ohio_sos": {
            "name": "Ohio Secretary of State",
            "description": "Business registration and status",
            "url": "https://www.ohiosos.gov/businesses/",
            "types": ["business_registry"]
        }
    }
    
    # Get stats for each source
    sources = []
    source_list = db.query(Award.source).distinct().all()
    active_sources = {s[0] for s in source_list}
    
    for source_key, info in SOURCE_INFO.items():
        if source_key in active_sources:
            # Get detailed stats for this source
            stats = db.query(
                func.count(Award.id).label("count"),
                func.sum(Award.amount).label("total"),
                func.min(Award.award_date).label("min_date"),
                func.max(Award.award_date).label("max_date"),
                func.min(Award.created_at).label("first_import"),
                func.max(Award.created_at).label("last_import")
            ).filter(Award.source == source_key).first()
            
            # Get year breakdown
            year_breakdown = db.query(
                func.strftime("%Y", Award.award_date).label("year"),
                func.count(Award.id).label("count"),
                func.sum(Award.amount).label("total")
            ).filter(
                Award.source == source_key,
                Award.award_date.isnot(None)
            ).group_by("year").order_by("year").all()
            
            # Get award type breakdown for this source
            type_breakdown = db.query(
                Award.award_type,
                func.count(Award.id).label("count"),
                func.sum(Award.amount).label("total")
            ).filter(Award.source == source_key).group_by(Award.award_type).all()
            
            sources.append({
                "key": source_key,
                "name": info["name"],
                "description": info["description"],
                "url": info["url"],
                "status": "active",
                "record_count": stats.count or 0,
                "total_amount": float(stats.total or 0),
                "date_range": {
                    "min": stats.min_date.isoformat() if stats.min_date else None,
                    "max": stats.max_date.isoformat() if stats.max_date else None
                },
                "import_info": {
                    "first_import": stats.first_import.isoformat() if stats.first_import else None,
                    "last_import": stats.last_import.isoformat() if stats.last_import else None
                },
                "by_year": [
                    {"year": row.year, "count": row.count, "total": float(row.total or 0)}
                    for row in year_breakdown
                ],
                "by_type": [
                    {"type": row.award_type, "count": row.count, "total": float(row.total or 0)}
                    for row in type_breakdown
                ]
            })
        else:
            # Source not yet imported
            sources.append({
                "key": source_key,
                "name": info["name"],
                "description": info["description"],
                "url": info["url"],
                "status": "pending",
                "record_count": 0,
                "total_amount": 0,
                "date_range": None,
                "import_info": None,
                "by_year": [],
                "by_type": []
            })
    
    # Get recipient stats
    recipient_stats = db.query(
        func.count(Recipient.id).label("total"),
        func.count(Recipient.naics_code).label("with_naics"),
        func.count(Recipient.business_type).label("with_business_type")
    ).first()
    
    # Count recipients by status
    status_breakdown = db.query(
        Recipient.business_status,
        func.count(Recipient.id).label("count")
    ).group_by(Recipient.business_status).all()
    
    # Get NAICS code count
    naics_count = 0
    try:
        naics_count = db.query(func.count(NaicsCode.code)).scalar() or 0
    except:
        pass
    
    # Database totals
    totals = {
        "total_awards": db.query(func.count(Award.id)).scalar() or 0,
        "total_amount": float(db.query(func.sum(Award.amount)).scalar() or 0),
        "total_recipients": recipient_stats.total or 0,
        "recipients_with_naics": recipient_stats.with_naics or 0,
        "total_agencies": db.query(func.count(Agency.id)).scalar() or 0,
        "naics_codes_loaded": naics_count
    }
    
    result = {
        "sources": sources,
        "totals": totals,
        "recipients": {
            "total": recipient_stats.total or 0,
            "with_naics": recipient_stats.with_naics or 0,
            "with_business_type": recipient_stats.with_business_type or 0,
            "by_status": [
                {"status": row.business_status, "count": row.count}
                for row in status_breakdown
            ]
        }
    }
    set_cached("data_status", result)
    return result
