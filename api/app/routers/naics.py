"""
NAICS and Business Type Search Endpoints
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_

from app.database import get_db
from app.models import NaicsCode, Recipient, Award, Agency

router = APIRouter()


@router.get("/naics/search")
async def search_naics(
    q: str = Query(..., min_length=2, description="Search term (code or industry name)"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Search NAICS codes by code number or industry title.
    
    Examples:
    - "484" -> trucking codes
    - "trucking" -> all trucking-related codes
    - "day care" -> child care services
    - "restaurant" -> food services
    """
    search_term = f"%{q.lower()}%"
    
    results = db.query(NaicsCode).filter(
        or_(
            NaicsCode.code.like(f"{q}%"),
            func.lower(NaicsCode.title).like(search_term),
            func.lower(NaicsCode.sector_title).like(search_term)
        )
    ).order_by(NaicsCode.code).limit(limit).all()
    
    return [
        {
            "code": r.code,
            "title": r.title,
            "sector": r.sector,
            "sector_title": r.sector_title
        }
        for r in results
    ]


@router.get("/naics/{code}")
async def get_naics(code: str, db: Session = Depends(get_db)):
    """Get details for a specific NAICS code"""
    
    naics = db.query(NaicsCode).filter(NaicsCode.code == code).first()
    
    if not naics:
        return {"code": code, "title": "Unknown", "sector": None, "sector_title": None}
    
    return {
        "code": naics.code,
        "title": naics.title,
        "sector": naics.sector,
        "sector_title": naics.sector_title
    }


@router.get("/naics/popular")
async def get_popular_naics(
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """
    Get most common NAICS codes based on recipient count.
    Useful for showing industry breakdown.
    """
    
    # Count recipients by NAICS code
    results = db.query(
        Recipient.naics_code,
        func.count(Recipient.id).label("recipient_count"),
        func.sum(
            db.query(func.sum(Award.amount))
            .filter(Award.recipient_id == Recipient.id)
            .correlate(Recipient)
            .scalar_subquery()
        ).label("total_amount")
    ).filter(
        Recipient.naics_code.isnot(None),
        Recipient.naics_code != ""
    ).group_by(Recipient.naics_code)\
     .order_by(desc("recipient_count"))\
     .limit(limit).all()
    
    # Enrich with NAICS titles
    codes = [r.naics_code for r in results]
    naics_lookup = {
        n.code: n.title 
        for n in db.query(NaicsCode).filter(NaicsCode.code.in_(codes)).all()
    }
    
    return [
        {
            "code": r.naics_code,
            "title": naics_lookup.get(r.naics_code, "Unknown"),
            "recipient_count": r.recipient_count,
            "total_amount": float(r.total_amount or 0)
        }
        for r in results
    ]


@router.get("/business-types/search")
async def search_by_business_type(
    industry: str = Query(..., description="Industry keyword (e.g., 'trucking', 'daycare', 'restaurant')"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Search awards by business type/industry.
    
    This searches by:
    1. NAICS code (if industry matches a code)
    2. NAICS title (industry name)
    3. Business type field (LLC, Corporation, etc.)
    
    Examples:
    - industry=trucking -> finds trucking companies
    - industry=daycare -> finds child care centers
    - industry=restaurant -> finds restaurants
    - industry=construction -> finds construction companies
    """
    
    # Common industry keyword to NAICS prefix mapping
    INDUSTRY_NAICS_MAP = {
        "trucking": ["484"],
        "truck": ["484"],
        "transportation": ["48", "49"],
        "daycare": ["624410"],
        "day care": ["624410"],
        "childcare": ["624410"],
        "child care": ["624410"],
        "restaurant": ["722511", "722513", "722514", "722515"],
        "food service": ["722"],
        "construction": ["23", "236", "237", "238"],
        "contractor": ["238"],
        "plumbing": ["238220"],
        "electrical": ["238210"],
        "roofing": ["238160"],
        "hospital": ["622"],
        "medical": ["621", "622"],
        "healthcare": ["62"],
        "health care": ["62"],
        "nursing": ["623110"],
        "assisted living": ["623312"],
        "salon": ["812111", "812112", "812113"],
        "barber": ["812111"],
        "beauty": ["812112"],
        "nail": ["812113"],
        "auto repair": ["811"],
        "car wash": ["811192"],
        "gas station": ["447"],
        "grocery": ["445110"],
        "retail": ["44", "45"],
        "manufacturing": ["31", "32", "33"],
        "agriculture": ["11"],
        "farming": ["111", "112"],
        "hotel": ["721110"],
        "motel": ["721110"],
        "accounting": ["541211", "541213"],
        "legal": ["541110"],
        "lawyer": ["541110"],
        "engineering": ["541330"],
        "architect": ["541310"],
        "consulting": ["541611", "541618"],
        "software": ["541511", "541512"],
        "it": ["541511", "541512", "541519"],
    }
    
    # Find matching NAICS codes
    industry_lower = industry.lower().strip()
    naics_prefixes = INDUSTRY_NAICS_MAP.get(industry_lower, [])
    
    # Also search NAICS titles
    if not naics_prefixes:
        search_term = f"%{industry_lower}%"
        matching_naics = db.query(NaicsCode.code).filter(
            or_(
                func.lower(NaicsCode.title).like(search_term),
                func.lower(NaicsCode.sector_title).like(search_term)
            )
        ).all()
        naics_prefixes = [n.code for n in matching_naics]
    
    # Build query for awards
    query = db.query(Award, Recipient, Agency)\
        .join(Recipient, Award.recipient_id == Recipient.id)\
        .outerjoin(Agency, Award.agency_id == Agency.id)
    
    if naics_prefixes:
        # Filter by NAICS codes
        naics_filters = [Recipient.naics_code.like(f"{prefix}%") for prefix in naics_prefixes]
        query = query.filter(or_(*naics_filters))
    else:
        # Fallback: search business_type field
        search_term = f"%{industry_lower}%"
        query = query.filter(
            or_(
                func.lower(Recipient.business_type).like(search_term),
                func.lower(Recipient.name).like(search_term)
            )
        )
    
    # Get total count
    total_count = query.count()
    
    # Apply sorting and pagination
    query = query.order_by(desc(Award.amount))
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    # Format results
    items = [
        {
            "award_id": award.id,
            "source": award.source,
            "award_type": award.award_type,
            "amount": award.amount,
            "description": award.description,
            "award_date": award.award_date.isoformat() if award.award_date else None,
            "recipient_id": recipient.id,
            "recipient_name": recipient.name,
            "recipient_city": recipient.city,
            "naics_code": recipient.naics_code,
            "business_type": recipient.business_type,
            "agency_code": agency.code if agency else None,
        }
        for award, recipient, agency in results
    ]
    
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    
    # Get industry info
    industry_info = None
    if naics_prefixes:
        sample_naics = db.query(NaicsCode).filter(
            NaicsCode.code.in_(naics_prefixes[:5])
        ).all()
        industry_info = [{"code": n.code, "title": n.title} for n in sample_naics]
    
    return {
        "industry": industry,
        "naics_codes_matched": naics_prefixes[:10],
        "industry_info": industry_info,
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }


@router.get("/industries")
async def list_industries(db: Session = Depends(get_db)):
    """
    Get list of searchable industry categories with common keywords.
    """
    return {
        "industries": [
            {"keyword": "trucking", "description": "Trucking and freight transportation"},
            {"keyword": "daycare", "description": "Child day care services"},
            {"keyword": "restaurant", "description": "Restaurants and food services"},
            {"keyword": "construction", "description": "Construction and contractors"},
            {"keyword": "healthcare", "description": "Healthcare and medical services"},
            {"keyword": "manufacturing", "description": "Manufacturing"},
            {"keyword": "retail", "description": "Retail trade"},
            {"keyword": "salon", "description": "Hair salons and barber shops"},
            {"keyword": "auto repair", "description": "Automotive repair and maintenance"},
            {"keyword": "hotel", "description": "Hotels and lodging"},
            {"keyword": "consulting", "description": "Business consulting services"},
            {"keyword": "software", "description": "Software and IT services"},
            {"keyword": "legal", "description": "Legal services"},
            {"keyword": "accounting", "description": "Accounting and tax services"},
            {"keyword": "agriculture", "description": "Agriculture and farming"},
        ],
        "tip": "Use /api/business-types/search?industry=KEYWORD to search"
    }
