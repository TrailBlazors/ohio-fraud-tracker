"""
Recipients endpoints - businesses and organizations
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, or_, and_, literal

from app.database import get_db
from app.models import Award, Recipient, Agency
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
    
    search_term = f"%{q.lower()}%"
    
    results = db.query(
        Recipient.id,
        Recipient.name,
        Recipient.city
    ).filter(
        func.lower(Recipient.name).like(search_term)
    ).order_by(Recipient.name).limit(limit).all()
    
    return [{"id": r.id, "name": r.name, "city": r.city} for r in results]


@router.get("/recipients/flagged")
async def get_flagged_recipients(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get recipients with potential issues:
    1. Business status is inactive/cancelled/dissolved (from Ohio SOS)
    2. High concentration of awards (20+ awards)
    3. Unusually large single awards ($50M+)
    """
    
    items = []
    existing_ids = set()
    
    try:
        # Method 1: Inactive businesses with awards (requires Ohio SOS data)
        inactive_query = db.query(
            Recipient,
            func.count(Award.id).label("total_awards"),
            func.sum(Award.amount).label("total_amount")
        ).join(Award, Award.recipient_id == Recipient.id)\
         .filter(Recipient.business_status.in_(["inactive", "cancelled", "dissolved"]))\
         .group_by(Recipient.id)\
         .order_by(desc("total_amount"))\
         .limit(100)
        
        for recipient, total_awards, total_amount in inactive_query.all():
            items.append({
                "id": recipient.id,
                "name": recipient.name,
                "city": recipient.city,
                "business_status": recipient.business_status,
                "total_awards": total_awards,
                "total_amount": float(total_amount or 0),
                "flag_reason": f"Business is {recipient.business_status} but received {total_awards} federal awards totaling ${float(total_amount or 0):,.0f}",
                "flag_type": "inactive_business"
            })
            existing_ids.add(recipient.id)
    except Exception as e:
        print(f"Error in inactive query: {e}")
    
    try:
        # Method 2: Recipients with high award counts (20+ awards)
        high_count_query = db.query(
            Recipient,
            func.count(Award.id).label("total_awards"),
            func.sum(Award.amount).label("total_amount")
        ).join(Award, Award.recipient_id == Recipient.id)\
         .group_by(Recipient.id)\
         .having(func.count(Award.id) >= 20)\
         .order_by(desc(func.count(Award.id)))\
         .limit(100)
        
        for recipient, total_awards, total_amount in high_count_query.all():
            if recipient.id not in existing_ids:
                items.append({
                    "id": recipient.id,
                    "name": recipient.name,
                    "city": recipient.city,
                    "business_status": recipient.business_status,
                    "total_awards": total_awards,
                    "total_amount": float(total_amount or 0),
                    "flag_reason": f"High award concentration: {total_awards} awards",
                    "flag_type": "high_concentration"
                })
                existing_ids.add(recipient.id)
    except Exception as e:
        print(f"Error in high count query: {e}")
    
    try:
        # Method 3: Recipients with very large single awards ($50M+)
        large_award_threshold = 50_000_000
        
        large_award_query = db.query(
            Recipient,
            func.count(Award.id).label("total_awards"),
            func.sum(Award.amount).label("total_amount"),
            func.max(Award.amount).label("max_award")
        ).join(Award, Award.recipient_id == Recipient.id)\
         .group_by(Recipient.id)\
         .having(func.max(Award.amount) >= large_award_threshold)\
         .order_by(desc(func.max(Award.amount)))\
         .limit(100)
        
        for recipient, total_awards, total_amount, max_award in large_award_query.all():
            if recipient.id not in existing_ids:
                items.append({
                    "id": recipient.id,
                    "name": recipient.name,
                    "city": recipient.city,
                    "business_status": recipient.business_status,
                    "total_awards": total_awards,
                    "total_amount": float(total_amount or 0),
                    "flag_reason": f"Large single award: ${float(max_award or 0):,.0f}",
                    "flag_type": "large_award"
                })
                existing_ids.add(recipient.id)
    except Exception as e:
        print(f"Error in large award query: {e}")
    
    # Sort all items by total_amount descending
    items.sort(key=lambda x: x["total_amount"], reverse=True)
    
    # Paginate
    total_count = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    paginated_items = items[start:end]
    
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    
    return {
        "items": paginated_items,
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
    sort_by: str = Query("total_amount", description="Sort field"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db)
):
    """
    List recipients with their award totals.
    
    Filters:
    - q: Search in recipient name
    - city: Filter by city (partial match)
    - business_status: Filter by Ohio SOS status
    - has_awards: Only show recipients with awards
    """
    
    # Base query with aggregates
    query = db.query(
        Recipient,
        func.count(Award.id).label("total_awards"),
        func.coalesce(func.sum(Award.amount), 0).label("total_amount")
    ).outerjoin(Award, Award.recipient_id == Recipient.id)\
     .group_by(Recipient.id)
    
    # Text search in name
    if q:
        search_term = f"%{q.lower()}%"
        query = query.filter(func.lower(Recipient.name).like(search_term))
    
    # City filter (partial match)
    if city:
        city_term = f"%{city.lower()}%"
        query = query.filter(func.lower(Recipient.city).like(city_term))
    
    if business_status:
        query = query.filter(Recipient.business_status == business_status)
    
    if has_awards:
        query = query.having(func.count(Award.id) > 0)
    
    # Get total count
    count_query = query.subquery()
    total_count = db.query(func.count()).select_from(count_query).scalar()
    
    # Sorting
    sort_columns = {
        "name": Recipient.name,
        "city": Recipient.city,
        "total_awards": "total_awards",
        "total_amount": "total_amount",
    }
    
    sort_col = sort_columns.get(sort_by, "total_amount")
    
    if sort_order == "asc":
        query = query.order_by(asc(sort_col))
    else:
        query = query.order_by(desc(sort_col))
    
    # Pagination
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    # Format results
    items = [
        RecipientSummary(
            id=recipient.id,
            name=recipient.name,
            city=recipient.city,
            state=recipient.state,
            zip_code=recipient.zip_code,
            business_status=recipient.business_status,
            total_awards=total_awards,
            total_amount=float(total_amount)
        )
        for recipient, total_awards, total_amount in results
    ]
    
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    
    return RecipientListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total_count=total_count or 0,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1
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
