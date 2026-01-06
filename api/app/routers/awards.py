"""
Awards endpoints - grants, loans, contracts
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, or_, text

from app.database import get_db
from app.models import Award, Recipient, Agency, SubAgency, CachedStats
from app.schemas import (
    AwardListResponse,
    AwardListItem,
    AwardDetail,
    AwardSearchParams
)

router = APIRouter()

# Cache for FTS availability check
_fts_available: Optional[bool] = None
_fts_type: Optional[str] = None  # "postgresql" or "sqlite"


def is_fts_available(db: Session) -> bool:
    """Check if full-text search is configured."""
    global _fts_available, _fts_type
    if _fts_available is not None:
        return _fts_available

    from app.database import IS_POSTGRES

    if IS_POSTGRES:
        try:
            # Check if tsvector column exists and has data
            count = db.execute(text("""
                SELECT COUNT(*) FROM awards WHERE description_tsv IS NOT NULL
            """)).scalar()
            _fts_available = count > 0
            _fts_type = "postgresql"
        except Exception:
            _fts_available = False
    else:
        try:
            count = db.execute(text("SELECT COUNT(*) FROM awards_fts")).scalar()
            _fts_available = count > 0
            _fts_type = "sqlite"
        except Exception:
            _fts_available = False

    return _fts_available


def search_with_fts(db: Session, search_term: str, limit: int = 1000) -> list[int]:
    """
    Use full-text search to find matching award IDs.
    - PostgreSQL: Uses tsvector/tsquery with GIN index
    - SQLite: Uses FTS5 MATCH
    Falls back to empty list if FTS is not available.
    """
    if not is_fts_available(db):
        return []

    from app.database import IS_POSTGRES

    try:
        if IS_POSTGRES:
            # PostgreSQL: Use plainto_tsquery for simple search
            results = db.execute(
                text("""
                    SELECT id FROM awards
                    WHERE description_tsv @@ plainto_tsquery('english', :term)
                    LIMIT :limit
                """),
                {"term": search_term, "limit": limit}
            ).fetchall()
            return [r[0] for r in results]
        else:
            # SQLite FTS5 search - use MATCH for full-text search
            safe_term = search_term.replace('"', '""')
            results = db.execute(
                text('SELECT rowid FROM awards_fts WHERE description MATCH :term LIMIT :limit'),
                {"term": f'"{safe_term}"*', "limit": limit}
            ).fetchall()
            return [r[0] for r in results]
    except Exception:
        return []


def build_award_query(db: Session, params: AwardSearchParams, fast_search: bool = False):
    """Build filtered query based on search params"""

    query = db.query(Award, Recipient, Agency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)

    # Text search - try FTS first, fall back to LIKE
    if params.q:
        search_term = f"%{params.q}%"
        if fast_search:
            # Fast: only search recipient name
            query = query.filter(Recipient.name.ilike(search_term))
        else:
            # Try FTS for description search (much faster)
            fts_ids = search_with_fts(db, params.q)
            if fts_ids:
                # FTS found matches - combine with recipient name search
                query = query.filter(
                    or_(
                        Recipient.name.ilike(search_term),
                        Award.id.in_(fts_ids),
                        Recipient.city.ilike(search_term)
                    )
                )
            else:
                # FTS not available or no matches - fall back to LIKE
                query = query.filter(
                    or_(
                        Recipient.name.ilike(search_term),
                        Award.description.ilike(search_term),
                        Recipient.city.ilike(search_term)
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
        query = query.filter(Recipient.city.ilike(params.city))
    
    if params.cfda_number:
        query = query.filter(Award.cfda_number == params.cfda_number)
    
    # NAICS code filter
    if hasattr(params, 'naics_code') and params.naics_code:
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
    fast: bool = Query(False, description="Fast mode - minimal JOINs for faster response"),
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
    - fast: Fast mode - skip JOINs for faster response (recipient info fetched separately)
    """

    # Check if query has any filters
    has_filters = any([
        q, recipient_id, agency_code, award_type,
        min_amount, max_amount, start_date, end_date,
        city, cfda_number, source
    ])

    # Fast mode - minimal query without JOINs for maximum speed
    if fast:
        query = db.query(Award)

        # Apply simple filters (no JOINs needed)
        if recipient_id:
            query = query.filter(Award.recipient_id == recipient_id)
        if award_type:
            query = query.filter(Award.award_type == award_type)
        if source:
            query = query.filter(Award.source == source)
        if min_amount is not None:
            query = query.filter(Award.amount >= min_amount)
        if max_amount is not None:
            query = query.filter(Award.amount <= max_amount)
        if start_date:
            query = query.filter(Award.award_date >= start_date)
        if end_date:
            query = query.filter(Award.award_date <= end_date)
        if cfda_number:
            query = query.filter(Award.cfda_number == cfda_number)

        # For text search in fast mode, we need a subquery for recipient name
        if q:
            search_term = f"%{q}%"
            # Search only in award description for fast mode
            query = query.filter(Award.description.ilike(search_term))

        # Sort by award columns only in fast mode
        fast_sort_columns = {
            "amount": Award.amount,
            "date": Award.award_date,
            "type": Award.award_type,
        }
        sort_col = fast_sort_columns.get(sort_by, Award.amount)
        query = query.order_by(asc(sort_col) if sort_order == "asc" else desc(sort_col))

        # Pagination
        offset = (page - 1) * page_size
        results = query.offset(offset).limit(page_size).all()

        # Batch fetch recipient names for display
        recipient_ids = [a.recipient_id for a in results]
        recipients_map = {}
        if recipient_ids:
            recipients = db.query(Recipient.id, Recipient.name, Recipient.city).filter(
                Recipient.id.in_(recipient_ids)
            ).all()
            recipients_map = {r.id: (r.name, r.city) for r in recipients}

        # Batch fetch agency codes
        agency_ids = [a.agency_id for a in results if a.agency_id]
        agencies_map = {}
        if agency_ids:
            agencies = db.query(Agency.id, Agency.code, Agency.name).filter(
                Agency.id.in_(agency_ids)
            ).all()
            agencies_map = {a.id: (a.code, a.name) for a in agencies}

        items = []
        for award in results:
            r_name, r_city = recipients_map.get(award.recipient_id, ("Unknown", None))
            a_code, a_name = agencies_map.get(award.agency_id, (None, None)) if award.agency_id else (None, None)
            items.append(AwardListItem(
                id=award.id,
                source=award.source,
                award_type=award.award_type,
                amount=award.amount,
                description=award.description,
                recipient_name=r_name,
                recipient_city=r_city,
                agency_code=a_code,
                agency_name=a_name,
                award_date=award.award_date,
                cfda_number=award.cfda_number
            ))

        # Estimate total for pagination
        total_count = len(items) + ((page - 1) * page_size)
        has_next = len(items) == page_size
        has_prev = page > 1
        total_pages = page + (1 if has_next else 0)

        return AwardListResponse(
            items=items,
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev
        )

    # Standard mode with full JOINs
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

    # Build query
    query = build_award_query(db, params)
    
    # Get total count - ALWAYS skip count for filtered queries (too slow on remote DB)
    if skip_count or has_filters:
        # For filtered queries, estimate based on page
        # We'll show "X+ results" in UI
        total_count = -1  # Signal to UI that count is unknown
    elif not has_filters:
        # Use cached total for unfiltered query
        cached = db.query(CachedStats).filter(CachedStats.stat_key == "total_awards").first()
        if cached:
            total_count = int(cached.stat_value)
        else:
            total_count = -1
    else:
        total_count = -1
    
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
    
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
    
    # Check if there's more data by seeing if we got a full page
    has_next = len(items) == page_size
    has_prev = page > 1
    
    return AwardListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total_count=total_count if total_count > 0 else len(items) + ((page - 1) * page_size),
        total_pages=total_pages if total_pages > 0 else page + (1 if has_next else 0),
        has_next=has_next,
        has_prev=has_prev
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


@router.get("/search/fast")
async def fast_search(
    q: str = Query(..., min_length=2, description="Search term"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Fast search endpoint - searches recipient names only, skips COUNT.
    Optimized for the search page initial results.
    """
    search_term = f"%{q}%"
    
    # Fast query: only recipient name, no COUNT, limited results
    # Use ilike for case-insensitive without LOWER() function
    query = db.query(Award, Recipient, Agency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)\
        .filter(Recipient.name.ilike(search_term))\
        .order_by(desc(Award.amount))\
        .limit(limit)
    
    results = query.all()
    
    items = [
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
        for award, recipient, agency in results
    ]
    
    return {
        "items": items,
        "total_count": len(items),
        "has_more": len(items) == limit
    }


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
    skip_count: bool = Query(False, description="Skip total count for faster response"),
    db: Session = Depends(get_db)
):
    """
    List loans only (PPP, EIDL, federal loans)
    """
    # Filter to loan types/sources
    loan_types = ["direct_loan", "guaranteed_loan", "insurance", "loan"]
    loan_sources = ["sba_ppp", "sba_eidl"]
    
    # Build optimized query - filter loans FIRST, then search
    query = db.query(Award, Recipient, Agency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)\
        .filter(
            or_(
                Award.award_type.in_(loan_types),
                Award.source.in_(loan_sources)
            )
        )
    
    # Text search - only on recipient name for speed
    if q:
        search_term = f"%{q}%"
        query = query.filter(Recipient.name.ilike(search_term))
    
    # City filter
    if city:
        query = query.filter(Recipient.city.ilike(f"%{city}%"))
    
    # Amount filters
    if min_amount is not None:
        query = query.filter(Award.amount >= min_amount)
    if max_amount is not None:
        query = query.filter(Award.amount <= max_amount)
    
    # Get total count - skip for speed (count is slow on remote DB)
    # Just check if we have a full page to determine has_next
    total_count = -1
    
    # Sort and paginate
    query = apply_sorting(query, sort_by, sort_order)
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
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
    
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
    
    # Check if there's more data
    has_next = len(items) == page_size
    has_prev = page > 1
    
    return AwardListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total_count=len(items) + ((page - 1) * page_size) if total_count < 0 else total_count,
        total_pages=page + (1 if has_next else 0) if total_pages == 0 else total_pages,
        has_next=has_next,
        has_prev=has_prev
    )
