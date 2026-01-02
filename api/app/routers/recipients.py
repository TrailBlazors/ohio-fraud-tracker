"""
Recipients endpoints - businesses and organizations
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, or_, and_, literal

from app.database import get_db
from app.models import Award, Recipient, Agency, FraudFlag, CachedStats
from app.schemas import (
    RecipientListResponse,
    RecipientSummary,
)

router = APIRouter()


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


@router.get("/recipients/flagged")
async def get_flagged_recipients(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get recipients with fraud flags from correlation analysis.
    Uses pre-computed flags from fraud_flags table for fast loading.
    """
    
    # Query from fraud_flags table (fast)
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
    total_count = query.count()
    
    # Paginate
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    items = []
    for row in results:
        items.append({
            "id": row.recipient_id,
            "name": row.name,
            "city": row.city,
            "business_status": row.business_status,
            "total_awards": 0,  # Skip expensive calculation
            "total_amount": 0,
            "flag_reason": row.description,
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

@router.get("/recipients/{recipient_id}")
async def get_recipient(recipient_id: int, db: Session = Depends(get_db)):
    """Get detailed information for a single recipient"""
    
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
    
    return {
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
        "updated_at": recipient.updated_at
    }


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
    
    # Query awards with agency
    query = db.query(Award, Agency)\
        .outerjoin(Agency, Award.agency_id == Agency.id)\
        .filter(Award.recipient_id == recipient_id)\
        .order_by(desc(Award.amount))
    
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
