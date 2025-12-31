"""
Awards endpoints - grants, loans, contracts
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, or_

from app.database import get_db
from app.models import Award, Recipient, Agency, SubAgency, CachedStats
from app.schemas import (
    AwardListResponse, 
    AwardListItem, 
    AwardDetail,
    AwardSearchParams
)

router = APIRouter()


def build_award_query(db: Session, params: AwardSearchParams):
    """Build filtered query based on search params"""
    
    query = db.query(Award, Recipient, Agency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)
    
    # Text search
    if params.q:
        search_term = f"%{params.q.lower()}%"
        query = query.filter(
            or_(
                func.lower(Recipient.name).like(search_term),
                func.lower(Award.description).like(search_term),
                func.lower(Recipient.city).like(search_term)
            )
        )
    
    # Filters
    if params.recipient_id:
        query = query.filter(Award.recipient_id == params.recipient_id)
    
    if params.agency_code:
        query = query.filter(Agency.code == params.agency_code.upper())
    
    if params.award_type:
        query = query.filter(Award.award_type == params.award_type)
    
    if params.source:
        query = query.filter(Award.source == params.source)
    
    if params.min_amount is not None:
        query = query.filter(Award.amount >= params.min_amount)
    
    if params.max_amount is not None:
        query = query.filter(Award.amount <= params.max_amount)
    
    if params.start_date:
        query = query.filter(Award.award_date >= params.start_date)
    
    if params.end_date:
        query = query.filter(Award.award_date <= params.end_date)
    
    if params.city:
        query = query.filter(func.lower(Recipient.city) == params.city.lower())
    
    if params.cfda_number:
        query = query.filter(Award.cfda_number == params.cfda_number)
    
    # NAICS code filter (business type search)
    if hasattr(params, 'naics_code') and params.naics_code:
        # Support partial match (e.g., "484" matches all trucking)
        naics_term = f"{params.naics_code}%"
        query = query.filter(Recipient.naics_code.like(naics_term))
    
    return query


def apply_sorting(query, sort_by: str, sort_order: str):
    """Apply sorting to query"""
    
    # Map sort field names to columns
    sort_columns = {
        "amount": Award.amount,
        "date": Award.award_date,
        "recipient": Recipient.name,
        "agency": Agency.code,
        "type": Award.award_type,
    }
    
    column = sort_columns.get(sort_by, Award.amount)
    
    if sort_order == "asc":
        return query.order_by(asc(column))
    else:
        return query.order_by(desc(column))


@router.get("/awards", response_model=AwardListResponse)
async def list_awards(
    q: Optional[str] = Query(None, description="Search term"),
    recipient_id: Optional[int] = None,
    agency_code: Optional[str] = None,
    award_type: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    city: Optional[str] = None,
    cfda_number: Optional[str] = None,
    source: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str = Query("amount", description="Sort field"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    skip_count: bool = Query(False, description="Skip total count for faster response"),
    db: Session = Depends(get_db)
):
    """
    List awards with filtering, pagination, and sorting.
    
    Filters:
    - q: Search in recipient name, description, city
    - agency_code: Filter by agency (HHS, DOT, etc.)
    - award_type: Filter by type (grant, loan, contract)
    - min_amount/max_amount: Amount range
    - start_date/end_date: Date range
    - city: Recipient city
    - source: Data source (usaspending, sba_ppp, etc.)
    - skip_count: Skip total count for faster initial load
    """
    
    params = AwardSearchParams(
        q=q,
        recipient_id=recipient_id,
        agency_code=agency_code,
        award_type=award_type,
        min_amount=min_amount,
        max_amount=max_amount,
        start_date=start_date,
        end_date=end_date,
        city=city,
        cfda_number=cfda_number,
        source=source,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    # Check if query has any filters
    has_filters = any([
        q, recipient_id, agency_code, award_type, 
        min_amount, max_amount, start_date, end_date, 
        city, cfda_number, source
    ])
    
    # Build query
    query = build_award_query(db, params)
    
    # Get total count - use cached value for simple queries
    if skip_count:
        # Estimate: assume there's more data
        total_count = page * page_size + page_size
    elif not has_filters:
        # Use cached total for unfiltered query
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "total_awards").first()
        if cached:
            total_count = int(cached.stat_value)
        else:
            total_count = query.count()
    elif source and not any([q, recipient_id, agency_code, award_type, min_amount, max_amount, start_date, end_date, city, cfda_number]):
        # Only source filter - use cached source count
        import json
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "awards_by_source").first()
        if cached and cached.stat_json:
            source_data = json.loads(cached.stat_json)
            if source in source_data:
                total_count = source_data[source]["count"]
            else:
                total_count = query.count()
        else:
            total_count = query.count()
    else:
        # Filtered query - need actual count
        total_count = query.count()
    
    # Apply sorting and pagination
    query = apply_sorting(query, sort_by, sort_order)
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    # Format results
    items = [
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
        for award, recipient, agency in results
    ]
    
    total_pages = (total_count + page_size - 1) // page_size
    
    return AwardListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1
    )


@router.get("/awards/{award_id}", response_model=AwardDetail)
async def get_award(award_id: int, db: Session = Depends(get_db)):
    """
    Get detailed information for a single award
    """
    
    result = db.query(Award, Recipient, Agency, SubAgency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)\
        .outerjoin(SubAgency, Award.sub_agency_id == SubAgency.id)\
        .filter(Award.id == award_id)\
        .first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Award not found")
    
    award, recipient, agency, sub_agency = result
    
    return AwardDetail(
        id=award.id,
        source=award.source,
        source_award_id=award.source_award_id,
        award_type=award.award_type,
        amount=award.amount,
        description=award.description,
        recipient_id=recipient.id,
        recipient_name=recipient.name,
        recipient_city=recipient.city,
        recipient_state=recipient.state,
        agency_id=agency.id if agency else None,
        agency_code=agency.code if agency else None,
        agency_name=agency.name if agency else None,
        sub_agency_name=sub_agency.name if sub_agency else None,
        award_date=award.award_date,
        start_date=award.start_date,
        end_date=award.end_date,
        cfda_number=award.cfda_number,
        cfda_title=award.cfda_title,
        pop_city=award.pop_city,
        pop_state=award.pop_state,
        pop_zip=award.pop_zip,
        last_modified=award.last_modified,
        created_at=award.created_at
    )


@router.get("/grants", response_model=AwardListResponse)
async def list_grants(
    q: Optional[str] = Query(None),
    agency_code: Optional[str] = None,
    city: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source: Optional[str] = Query(None, description="Filter by source"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str = Query("amount"),
    sort_order: str = Query("desc"),
    skip_count: bool = Query(False),
    db: Session = Depends(get_db)
):
    """
    List grants/awards (convenience endpoint)
    """
    return await list_awards(
        q=q,
        agency_code=agency_code,
        award_type=None,
        city=city,
        min_amount=min_amount,
        max_amount=max_amount,
        start_date=start_date,
        end_date=end_date,
        source=source,  # Allow filtering by source
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        skip_count=skip_count,
        db=db,
        recipient_id=None,
        cfda_number=None
    )


@router.get("/loans", response_model=AwardListResponse)
async def list_loans(
    q: Optional[str] = Query(None),
    city: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str = Query("amount"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db)
):
    """
    List loans only (PPP, EIDL, federal loans)
    """
    # Include both federal loans and SBA loans
    params = AwardSearchParams(
        q=q,
        city=city,
        min_amount=min_amount,
        max_amount=max_amount,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    query = build_award_query(db, params)
    
    # Filter to loan types
    loan_types = ["direct_loan", "guaranteed_loan", "insurance"]
    loan_sources = ["sba_ppp", "sba_eidl"]
    
    query = query.filter(
        or_(
            Award.award_type.in_(loan_types),
            Award.source.in_(loan_sources)
        )
    )
    
    total_count = query.count()
    query = apply_sorting(query, sort_by, sort_order)
    offset = (params.page - 1) * params.page_size
    results = query.offset(offset).limit(params.page_size).all()
    
    items = [
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
        for award, recipient, agency in results
    ]
    
    total_pages = (total_count + params.page_size - 1) // params.page_size
    
    return AwardListResponse(
        items=items,
        page=params.page,
        page_size=params.page_size,
        total_count=total_count,
        total_pages=total_pages,
        has_next=params.page < total_pages,
        has_prev=params.page > 1
    )
