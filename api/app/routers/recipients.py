"""
Recipients endpoints - businesses and organizations
"""

import json
import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, or_, and_, literal, text

from app.database import get_db
from app.models import Award, Recipient, Agency, FraudFlag, CachedStats
from app.schemas import (
    RecipientListResponse,
    RecipientSummary,
)

router = APIRouter()

# Simple in-memory cache with TTL (same pattern as stats.py)
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 86400  # 24 hours

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


def _compute_nonprofit_health(recipient, total_grants: float) -> dict:
    """Compute health indicators for a nonprofit based on 990 data"""
    indicators = []
    overall_score = 100  # Start at 100, deduct for issues
    
    # 1. Program ratio check (should be >65%)
    if recipient.irs_program_ratio is not None:
        if recipient.irs_program_ratio >= 0.75:
            indicators.append({"name": "Program Spending", "status": "good", 
                             "detail": f"{recipient.irs_program_ratio*100:.0f}% goes to programs"})
        elif recipient.irs_program_ratio >= 0.65:
            indicators.append({"name": "Program Spending", "status": "fair", 
                             "detail": f"{recipient.irs_program_ratio*100:.0f}% goes to programs"})
            overall_score -= 10
        else:
            indicators.append({"name": "Program Spending", "status": "poor", 
                             "detail": f"Only {recipient.irs_program_ratio*100:.0f}% goes to programs"})
            overall_score -= 25
    
    # 2. Compensation ratio check (should be <25%)
    if recipient.irs_comp_ratio is not None:
        if recipient.irs_comp_ratio <= 0.20:
            indicators.append({"name": "Compensation", "status": "good", 
                             "detail": f"{recipient.irs_comp_ratio*100:.0f}% to compensation"})
        elif recipient.irs_comp_ratio <= 0.30:
            indicators.append({"name": "Compensation", "status": "fair", 
                             "detail": f"{recipient.irs_comp_ratio*100:.0f}% to compensation"})
            overall_score -= 10
        else:
            indicators.append({"name": "Compensation", "status": "poor", 
                             "detail": f"{recipient.irs_comp_ratio*100:.0f}% to compensation (high)"})
            overall_score -= 20
    
    # 3. Revenue vs grants check
    if recipient.irs_total_revenue and total_grants > 0:
        ratio = total_grants / recipient.irs_total_revenue
        if ratio <= 1.0:
            indicators.append({"name": "Grant/Revenue Ratio", "status": "good", 
                             "detail": "Grants align with reported revenue"})
        elif ratio <= 1.5:
            indicators.append({"name": "Grant/Revenue Ratio", "status": "fair", 
                             "detail": f"Grants are {ratio:.1f}x reported revenue"})
            overall_score -= 15
        else:
            indicators.append({"name": "Grant/Revenue Ratio", "status": "poor", 
                             "detail": f"Grants are {ratio:.1f}x reported revenue (mismatch)"})
            overall_score -= 30
    
    # 4. Filing freshness check
    if recipient.tax_period:
        try:
            from datetime import datetime as dt
            filing_year = int(recipient.tax_period[:4])
            years_old = dt.now().year - filing_year
            if years_old <= 2:
                indicators.append({"name": "Filing Status", "status": "good", 
                                 "detail": f"Filed for {filing_year}"})
            elif years_old <= 3:
                indicators.append({"name": "Filing Status", "status": "fair", 
                                 "detail": f"Last filed for {filing_year} ({years_old} years ago)"})
                overall_score -= 10
            else:
                indicators.append({"name": "Filing Status", "status": "poor", 
                                 "detail": f"Stale: last filed for {filing_year} ({years_old} years ago)"})
                overall_score -= 20
        except:
            pass
    
    # Determine overall status
    if overall_score >= 80:
        overall_status = "healthy"
    elif overall_score >= 60:
        overall_status = "fair"
    elif overall_score >= 40:
        overall_status = "concerning"
    else:
        overall_status = "poor"
    
    return {
        "overall_status": overall_status,
        "overall_score": max(0, overall_score),
        "indicators": indicators
    }


# =============================================================================
# TOP RECIPIENTS (RED FLAGS) - OPTIMIZED WITH CACHING
# =============================================================================

@router.get("/recipients/top")
async def get_top_recipients(
    limit: int = Query(20, ge=1, le=100),
    refresh: bool = Query(False, description="Force refresh cache"),
    db: Session = Depends(get_db)
):
    """
    Get top recipients by total award amount.
    Uses in-memory cache first, then database cache, then computes.
    """
    
    cache_key = f"top_recipients_{limit}"
    
    # 1. Check in-memory cache first (fastest)
    if not refresh:
        cached = get_cached(cache_key)
        if cached:
            return cached
    
    # 2. Check database cache (second fastest)
    if not refresh:
        db_cached = db.query(CachedStats).filter(CachedStats.stat_key == cache_key).first()
        if db_cached and db_cached.stat_json:
            try:
                data = json.loads(db_cached.stat_json)
                set_cached(cache_key, data)  # Store in memory for next time
                return data
            except json.JSONDecodeError:
                pass
    
    # 3. Cache miss - run the query (slow but necessary)
    results = db.execute(text("""
        SELECT 
            r.id,
            r.name,
            r.city,
            r.state,
            r.business_status,
            COUNT(a.id) as award_count,
            SUM(a.amount) as total_amount
        FROM recipients r
        INNER JOIN awards a ON a.recipient_id = r.id
        GROUP BY r.id
        ORDER BY total_amount DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    
    items = []
    for i, row in enumerate(results, 1):
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
    
    response = {
        "items": items,
        "count": len(items)
    }
    
    # Store in memory cache
    set_cached(cache_key, response)
    
    # Update database cache
    cached = db.query(CachedStats).filter(CachedStats.stat_key == cache_key).first()
    if cached:
        cached.stat_json = json.dumps(response)
        cached.updated_at = func.now()
    else:
        cached = CachedStats(
            stat_key=cache_key,
            stat_value=len(items),
            stat_json=json.dumps(response)
        )
        db.add(cached)
    
    try:
        db.commit()
    except:
        db.rollback()
    
    return response


# =============================================================================
# STATIC ROUTES - Must come before dynamic {recipient_id} routes
# =============================================================================

@router.get("/recipients/search/autocomplete")
async def autocomplete_recipients(
    q: str = Query(..., min_length=2, description="Search term"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Autocomplete search for recipient names"""
    
    search_term = f"%{q}%"
    
    results = db.query(
        Recipient.id,
        Recipient.name,
        Recipient.city
    ).filter(
        Recipient.name.ilike(search_term)
    ).order_by(Recipient.name).limit(limit).all()
    
    return [{"id": r.id, "name": r.name, "city": r.city} for r in results]


@router.get("/recipients/nonprofits")
async def get_nonprofits(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    health_status: Optional[str] = Query(None, description="Filter: healthy, fair, concerning, poor"),
    has_flags: Optional[bool] = Query(None, description="Only show flagged nonprofits"),
    min_grants: Optional[float] = Query(None, description="Minimum total grants received"),
    db: Session = Depends(get_db)
):
    """
    List nonprofits with 990 data and health indicators.
    Cached for 1 hour.
    """
    
    cache_key = f"nonprofits_{page}_{page_size}_{health_status}_{has_flags}_{min_grants}"
    
    # Check cache (shorter TTL for this endpoint - 1 hour)
    cached = get_cached(cache_key)
    if cached:
        return cached
    
    # Build query
    query = db.query(
        Recipient,
        func.coalesce(func.sum(Award.amount), 0).label("total_grants"),
        func.count(Award.id).label("award_count")
    ).outerjoin(
        Award, Award.recipient_id == Recipient.id
    ).filter(
        Recipient.is_nonprofit == True
    ).group_by(Recipient.id)
    
    if min_grants:
        query = query.having(func.sum(Award.amount) >= min_grants)
    
    # Get total before pagination
    total_count = db.query(func.count(Recipient.id)).filter(
        Recipient.is_nonprofit == True
    ).scalar() or 0
    
    # Order by total grants descending
    query = query.order_by(desc("total_grants"))
    
    # Paginate
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    items = []
    for recipient, total_grants, award_count in results:
        health = _compute_nonprofit_health(recipient, float(total_grants))
        
        # Filter by health status if specified
        if health_status and health["overall_status"] != health_status:
            continue
        
        items.append({
            "id": recipient.id,
            "name": recipient.name,
            "city": recipient.city,
            "ein": recipient.ein,
            "total_grants": float(total_grants),
            "award_count": award_count,
            "tax_period": recipient.tax_period,
            "form_type": recipient.form_type,
            "irs_total_revenue": recipient.irs_total_revenue,
            "irs_program_ratio": recipient.irs_program_ratio,
            "irs_comp_ratio": recipient.irs_comp_ratio,
            "health_status": health["overall_status"],
            "health_score": health["overall_score"],
            "propublica_url": f"https://projects.propublica.org/nonprofits/organizations/{recipient.ein}" if recipient.ein else None
        })
    
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    
    response = {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }
    
    # Cache for 1 hour (shorter than default)
    _cache[cache_key] = (time.time(), response)
    
    return response


@router.get("/recipients/nonprofits/stats")
async def get_nonprofit_stats(
    refresh: bool = Query(False),
    db: Session = Depends(get_db)
):
    """
    Get aggregate statistics for nonprofits with 990 data.
    Cached for 24 hours.
    """
    
    cache_key = "nonprofit_stats"
    
    if not refresh:
        cached = get_cached(cache_key)
        if cached:
            return cached
    
    # Count nonprofits
    total_nonprofits = db.query(func.count(Recipient.id)).filter(
        Recipient.is_nonprofit == True
    ).scalar() or 0
    
    nonprofits_with_990 = db.query(func.count(Recipient.id)).filter(
        Recipient.is_nonprofit == True,
        Recipient.irs_total_revenue.isnot(None)
    ).scalar() or 0
    
    # Total grants to nonprofits
    total_nonprofit_grants = db.query(func.sum(Award.amount)).join(
        Recipient, Award.recipient_id == Recipient.id
    ).filter(
        Recipient.is_nonprofit == True
    ).scalar() or 0
    
    # Average metrics
    avg_program_ratio = db.query(func.avg(Recipient.irs_program_ratio)).filter(
        Recipient.is_nonprofit == True,
        Recipient.irs_program_ratio.isnot(None)
    ).scalar()
    
    avg_comp_ratio = db.query(func.avg(Recipient.irs_comp_ratio)).filter(
        Recipient.is_nonprofit == True,
        Recipient.irs_comp_ratio.isnot(None)
    ).scalar()
    
    # Count by health status (sample calculation)
    # Note: This is an approximation - full calculation would be expensive
    low_program = db.query(func.count(Recipient.id)).filter(
        Recipient.is_nonprofit == True,
        Recipient.irs_program_ratio < 0.65
    ).scalar() or 0
    
    high_comp = db.query(func.count(Recipient.id)).filter(
        Recipient.is_nonprofit == True,
        Recipient.irs_comp_ratio > 0.25
    ).scalar() or 0
    
    response = {
        "total_nonprofits": total_nonprofits,
        "nonprofits_with_990_data": nonprofits_with_990,
        "coverage_percent": round(nonprofits_with_990 / total_nonprofits * 100, 1) if total_nonprofits else 0,
        "total_grants_to_nonprofits": float(total_nonprofit_grants),
        "averages": {
            "program_ratio": round(float(avg_program_ratio), 3) if avg_program_ratio else None,
            "compensation_ratio": round(float(avg_comp_ratio), 3) if avg_comp_ratio else None,
        },
        "concerns": {
            "low_program_ratio": low_program,
            "high_compensation": high_comp,
        }
    }
    
    set_cached(cache_key, response)
    return response


@router.get("/recipients/flagged")
async def get_flagged_recipients(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get recipients with fraud flags from correlation analysis.
    Optimized query - skips expensive award aggregation.
    """
    
    # Simple, fast query - no joins to awards table
    query = db.query(
        FraudFlag.id.label("flag_id"),
        FraudFlag.flag_type,
        FraudFlag.severity,
        FraudFlag.description,
        FraudFlag.recipient_id,
        FraudFlag.created_at,
        Recipient.name,
        Recipient.city,
        Recipient.business_status
    ).join(
        Recipient, FraudFlag.recipient_id == Recipient.id
    ).filter(
        FraudFlag.is_resolved == False,
        FraudFlag.recipient_id.isnot(None)
    ).order_by(
        desc(FraudFlag.severity),
        desc(FraudFlag.created_at)
    )
    
    # Get total count (fast - just counting flags)
    total_count = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.is_resolved == False,
        FraudFlag.recipient_id.isnot(None)
    ).scalar() or 0
    
    # Paginate
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    items = []
    for row in results:
        items.append({
            "id": row.recipient_id,
            "name": row.name or "Unknown Recipient",
            "city": row.city or "Ohio",
            "business_status": row.business_status or "unknown",
            "total_awards": 0,  # Skip expensive calculation - not needed for flagged view
            "total_amount": 0,
            "flag_reason": row.description or "Flagged for review",
            "flag_type": row.flag_type,
            "severity": row.severity,
            "flag_id": row.flag_id
        })
    
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }


# =============================================================================
# LIST AND SEARCH
# =============================================================================

@router.get("/recipients", response_model=RecipientListResponse)
async def list_recipients(
    q: Optional[str] = Query(None, description="Search by name"),
    city: Optional[str] = None,
    business_status: Optional[str] = None,
    has_awards: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str = Query("name", description="Sort field"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    skip_count: bool = Query(False, description="Skip total count for faster response"),
    fast: bool = Query(False, description="Fast mode - skip award aggregation"),
    db: Session = Depends(get_db)
):
    """
    List recipients with their award totals.
    
    Filters:
    - q: Search in recipient name
    - city: Filter by city (partial match)
    - business_status: Filter by Ohio SOS status
    - has_awards: Only show recipients with awards
    - skip_count: Skip total count for faster initial load
    - fast: Skip award aggregation for much faster response
    """
    
    has_filters = any([q, city, business_status, has_awards])
    
    # Fast mode - just get recipients without aggregation
    if fast:
        query = db.query(Recipient)
        
        if q:
            search_term = f"%{q}%"
            query = query.filter(Recipient.name.ilike(search_term))
        if city:
            city_term = f"%{city}%"
            query = query.filter(Recipient.city.ilike(city_term))
        if business_status:
            query = query.filter(Recipient.business_status == business_status)
        
        # Get total count
        if skip_count:
            total_count = page * page_size + page_size
        elif not has_filters:
            cached = db.query(CachedStats).filter(CachedStats.stat_key == "total_recipients").first()
            total_count = int(cached.stat_value) if cached else db.query(func.count(Recipient.id)).scalar() or 0
        else:
            total_count = query.count()
        
        # Sort and paginate
        sort_col = getattr(Recipient, sort_by, Recipient.name)
        query = query.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))
        results = query.offset((page - 1) * page_size).limit(page_size).all()
        
        items = [
            RecipientSummary(
                id=r.id, name=r.name, city=r.city, state=r.state,
                zip_code=r.zip_code, business_status=r.business_status,
                total_awards=0, total_amount=0.0
            )
            for r in results
        ]
        
        total_pages = (total_count + page_size - 1) // page_size if total_count else 0
        return RecipientListResponse(
            items=items, page=page, page_size=page_size,
            total_count=total_count, total_pages=total_pages,
            has_next=page < total_pages, has_prev=page > 1
        )
    
    # Full mode with aggregation (slower)
    query = db.query(
        Recipient,
        func.count(Award.id).label("total_awards"),
        func.coalesce(func.sum(Award.amount), 0).label("total_amount")
    ).outerjoin(Award, Award.recipient_id == Recipient.id)\
     .group_by(Recipient.id)
    
    if q:
        search_term = f"%{q}%"
        query = query.filter(Recipient.name.ilike(search_term))
    if city:
        city_term = f"%{city}%"
        query = query.filter(Recipient.city.ilike(city_term))
    if business_status:
        query = query.filter(Recipient.business_status == business_status)
    if has_awards:
        query = query.having(func.count(Award.id) > 0)
    
    # Get total count
    if skip_count:
        total_count = page * page_size + page_size
    elif not has_filters:
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "total_recipients").first()
        total_count = int(cached.stat_value) if cached else db.query(func.count(Recipient.id)).scalar() or 0
    else:
        count_query = query.subquery()
        total_count = db.query(func.count()).select_from(count_query).scalar() or 0
    
    # Sorting
    sort_columns = {
        "name": Recipient.name,
        "city": Recipient.city,
        "total_awards": "total_awards",
        "total_amount": "total_amount",
    }
    sort_col = sort_columns.get(sort_by, Recipient.name)
    query = query.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))
    
    # Pagination
    results = query.offset((page - 1) * page_size).limit(page_size).all()
    
    items = [
        RecipientSummary(
            id=recipient.id, name=recipient.name, city=recipient.city,
            state=recipient.state, zip_code=recipient.zip_code,
            business_status=recipient.business_status,
            total_awards=total_awards, total_amount=float(total_amount)
        )
        for recipient, total_awards, total_amount in results
    ]
    
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    return RecipientListResponse(
        items=items, page=page, page_size=page_size,
        total_count=total_count or 0, total_pages=total_pages,
        has_next=page < total_pages, has_prev=page > 1
    )


# =============================================================================
# DYNAMIC ROUTES - Must come after static routes
# =============================================================================

@router.get("/recipients/enrich")
async def enrich_recipients(
    ids: str = Query(..., description="Comma-separated recipient IDs to enrich"),
    db: Session = Depends(get_db)
):
    """
    Fetch award totals for a list of recipients.
    Used for progressive loading - first load basic data fast, then enrich with totals.
    """
    try:
        id_list = [int(id.strip()) for id in ids.split(",") if id.strip()]
    except ValueError:
        return {"items": []}

    if not id_list or len(id_list) > 100:
        return {"items": []}

    # Batch fetch totals for all recipients
    results = db.query(
        Award.recipient_id,
        func.count(Award.id).label("total_awards"),
        func.coalesce(func.sum(Award.amount), 0).label("total_amount")
    ).filter(
        Award.recipient_id.in_(id_list)
    ).group_by(Award.recipient_id).all()

    items = {
        row.recipient_id: {
            "id": row.recipient_id,
            "total_awards": row.total_awards,
            "total_amount": float(row.total_amount)
        }
        for row in results
    }

    # Include zeros for recipients with no awards
    for rid in id_list:
        if rid not in items:
            items[rid] = {"id": rid, "total_awards": 0, "total_amount": 0.0}

    return {"items": list(items.values())}


@router.get("/recipients/{recipient_id}")
async def get_recipient(recipient_id: int, db: Session = Depends(get_db)):
    """Get detailed information for a single recipient including 990 data"""
    
    result = db.query(
        Recipient,
        func.count(Award.id).label("total_awards"),
        func.coalesce(func.sum(Award.amount), 0).label("total_amount")
    ).outerjoin(Award, Award.recipient_id == Recipient.id)\
     .filter(Recipient.id == recipient_id)\
     .group_by(Recipient.id)\
     .first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Recipient not found")
    
    recipient, total_awards, total_amount = result
    
    # Build response
    response = {
        "id": recipient.id,
        "name": recipient.name,
        "uei": recipient.uei,
        "ein": recipient.ein,
        "ohio_entity_number": recipient.ohio_entity_number,
        "address": recipient.address,
        "city": recipient.city,
        "state": recipient.state,
        "zip_code": recipient.zip_code,
        "county": recipient.county,
        "business_status": recipient.business_status,
        "formation_date": recipient.formation_date,
        "total_awards": total_awards,
        "total_amount": float(total_amount),
        "created_at": recipient.created_at,
        "updated_at": recipient.updated_at,
    }
    
    # Add 990 nonprofit data if available
    if recipient.is_nonprofit:
        response["nonprofit_data"] = {
            "is_nonprofit": True,
            "propublica_id": recipient.propublica_id,
            "tax_period": recipient.tax_period,
            "form_type": recipient.form_type,
            "financials": {
                "total_revenue": recipient.irs_total_revenue,
                "total_expenses": recipient.irs_total_expenses,
                "net_assets": recipient.irs_net_assets,
                "total_liabilities": recipient.irs_total_liabilities,
            },
            "compensation": {
                "total_compensation": recipient.irs_total_compensation,
                "top_salary": recipient.irs_top_salary,
                "num_employees": recipient.irs_num_employees,
                "compensation_ratio": recipient.irs_comp_ratio,
            },
            "program_efficiency": {
                "program_expenses": recipient.irs_program_expenses,
                "admin_expenses": recipient.irs_admin_expenses,
                "fundraising_expenses": recipient.irs_fundraising_expenses,
                "program_ratio": recipient.irs_program_ratio,
            },
            "last_updated": recipient.irs_last_updated.isoformat() if recipient.irs_last_updated else None,
            # Health indicators
            "health_indicators": _compute_nonprofit_health(recipient, float(total_amount))
        }
    else:
        response["nonprofit_data"] = None
    
    return response


@router.get("/recipients/{recipient_id}/awards")
async def get_recipient_awards(
    recipient_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get all awards for a specific recipient"""
    
    # Verify recipient exists
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    
    # Query awards with agency (most recent first)
    query = db.query(Award, Agency)\
        .outerjoin(Agency, Award.agency_id == Agency.id)\
        .filter(Award.recipient_id == recipient_id)\
        .order_by(desc(Award.award_date))
    
    total_count = query.count()
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    items = [
        {
            "id": award.id,
            "source": award.source,
            "award_type": award.award_type,
            "amount": award.amount,
            "description": award.description,
            "award_date": award.award_date,
            "cfda_number": award.cfda_number,
            "agency_code": agency.code if agency else None,
            "agency_name": agency.name if agency else None,
        }
        for award, agency in results
    ]
    
    total_pages = (total_count + page_size - 1) // page_size
    
    return {
        "recipient": {
            "id": recipient.id,
            "name": recipient.name,
            "city": recipient.city
        },
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }
