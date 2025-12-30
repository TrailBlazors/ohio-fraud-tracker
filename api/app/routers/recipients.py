"""
Recipients endpoints - businesses and organizations
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, or_

from app.database import get_db
from app.models import Award, Recipient
from app.schemas import (
    RecipientListResponse,
    RecipientSummary,
    RecipientDetail,
    AwardListItem,
    RecipientSearchParams
)

router = APIRouter()


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
    - city: Filter by city
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
    
    # Text search
    if q:
        search_term = f"%{q.lower()}%"
        query = query.filter(func.lower(Recipient.name).like(search_term))
    
    # Filters
    if city:
        query = query.filter(func.lower(Recipient.city) == city.lower())
    
    if business_status:
        query = query.filter(Recipient.business_status == business_status)
    
    if has_awards:
        query = query.having(func.count(Award.id) > 0)
    
    # Get total count (need subquery for HAVING)
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


@router.get("/recipients/{recipient_id}", response_model=RecipientDetail)
async def get_recipient(recipient_id: int, db: Session = Depends(get_db)):
    """
    Get detailed information for a single recipient
    """
    
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    
    return RecipientDetail(
        id=recipient.id,
        name=recipient.name,
        uei=recipient.uei,
        ein=recipient.ein,
        ohio_entity_number=recipient.ohio_entity_number,
        address=recipient.address,
        city=recipient.city,
        state=recipient.state,
        zip_code=recipient.zip_code,
        county=recipient.county,
        business_status=recipient.business_status,
        formation_date=recipient.formation_date,
        created_at=recipient.created_at,
        updated_at=recipient.updated_at
    )


@router.get("/recipients/{recipient_id}/awards")
async def get_recipient_awards(
    recipient_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get all awards for a specific recipient
    """
    
    # Verify recipient exists
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    
    # Query awards
    query = db.query(Award)\
        .filter(Award.recipient_id == recipient_id)\
        .order_by(desc(Award.amount))
    
    total_count = query.count()
    offset = (page - 1) * page_size
    awards = query.offset(offset).limit(page_size).all()
    
    items = [
        {
            "id": award.id,
            "source": award.source,
            "award_type": award.award_type,
            "amount": award.amount,
            "description": award.description,
            "award_date": award.award_date,
            "cfda_number": award.cfda_number
        }
        for award in awards
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


@router.get("/recipients/search/autocomplete")
async def autocomplete_recipients(
    q: str = Query(..., min_length=2, description="Search term"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """
    Autocomplete search for recipient names
    """
    
    search_term = f"%{q.lower()}%"
    
    results = db.query(
        Recipient.id,
        Recipient.name,
        Recipient.city
    ).filter(
        func.lower(Recipient.name).like(search_term)
    ).order_by(Recipient.name)\
     .limit(limit).all()
    
    return [
        {
            "id": r.id,
            "name": r.name,
            "city": r.city
        }
        for r in results
    ]


@router.get("/recipients/flagged")
async def get_flagged_recipients(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get recipients with potential issues (inactive business + active awards)
    """
    
    # Find recipients with non-active status but have awards
    query = db.query(
        Recipient,
        func.count(Award.id).label("total_awards"),
        func.sum(Award.amount).label("total_amount")
    ).join(Award, Award.recipient_id == Recipient.id)\
     .filter(Recipient.business_status.in_(["inactive", "cancelled", "dissolved"]))\
     .group_by(Recipient.id)\
     .order_by(desc("total_amount"))
    
    total_count = query.count()
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    items = [
        {
            "id": recipient.id,
            "name": recipient.name,
            "city": recipient.city,
            "business_status": recipient.business_status,
            "total_awards": total_awards,
            "total_amount": float(total_amount),
            "flag_reason": f"Business status is {recipient.business_status} but received {total_awards} awards"
        }
        for recipient, total_awards, total_amount in results
    ]
    
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
