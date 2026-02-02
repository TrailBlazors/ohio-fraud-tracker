"""
Ohio Campaign Finance API Endpoints

Data coverage: 1990-2022 (updated annually from Ohio Secretary of State)
Source: https://www.ohiosos.gov/campaign-finance/
"""

from typing import Optional, List
from datetime import date
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_, and_

from app.database import get_db
from app.models import CampaignContribution, Politician, Recipient, Award, FraudFlag

router = APIRouter()

# Data coverage constants - displayed to users
DATA_START_YEAR = 1990
DATA_END_YEAR = 2022
DATA_LAST_UPDATED = "2024-01-15"  # Update when data is refreshed


@router.get("/campaign-finance/info")
async def get_campaign_finance_info():
    """
    Get metadata about campaign finance data coverage.
    Frontend should display this prominently.
    """
    return {
        "source": "Ohio Secretary of State",
        "source_url": "https://www.ohiosos.gov/campaign-finance/",
        "coverage": {
            "start_year": DATA_START_YEAR,
            "end_year": DATA_END_YEAR,
            "description": f"Campaign contributions from {DATA_START_YEAR} to {DATA_END_YEAR}"
        },
        "last_updated": DATA_LAST_UPDATED,
        "disclaimer": "Data is from public filings with the Ohio Secretary of State. "
                     "Updated annually. Some records may be incomplete.",
        "committee_types": {
            "CAN": "Candidate Committee",
            "PAC": "Political Action Committee",
            "PAR": "Political Party Committee"
        }
    }


@router.get("/campaign-finance/stats")
async def get_campaign_finance_stats(db: Session = Depends(get_db)):
    """
    Get summary statistics for campaign finance data.
    Used on dashboard and campaign finance landing page.
    """
    # Total contributions
    total = db.query(func.count(CampaignContribution.id)).scalar() or 0
    total_amount = db.query(func.sum(CampaignContribution.amount)).scalar() or 0

    # By committee type
    by_type = db.query(
        CampaignContribution.committee_type,
        func.count(CampaignContribution.id).label("count"),
        func.sum(CampaignContribution.amount).label("total")
    ).group_by(CampaignContribution.committee_type).all()

    type_breakdown = {
        row.committee_type or "Unknown": {
            "count": row.count,
            "total": float(row.total or 0)
        }
        for row in by_type
    }

    # Year range in actual data
    year_range = db.query(
        func.min(CampaignContribution.report_year),
        func.max(CampaignContribution.report_year)
    ).first()

    # Matched to recipients
    matched_count = db.query(func.count(CampaignContribution.id)).filter(
        CampaignContribution.matched_recipient_id.isnot(None)
    ).scalar() or 0

    # Political donor flags
    donor_flags = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.flag_type == "political_donor"
    ).scalar() or 0

    # Politician count
    politician_count = db.query(func.count(Politician.id)).scalar() or 0

    return {
        "total_contributions": total,
        "total_amount": float(total_amount),
        "by_committee_type": type_breakdown,
        "data_coverage": {
            "start_year": year_range[0] if year_range else DATA_START_YEAR,
            "end_year": year_range[1] if year_range else DATA_END_YEAR,
        },
        "matched_to_recipients": matched_count,
        "recipients_flagged_as_donors": donor_flags,
        "politicians_tracked": politician_count,
    }


@router.get("/campaign-finance/contributions")
async def search_contributions(
    contributor: Optional[str] = Query(None, description="Contributor name search"),
    committee: Optional[str] = Query(None, description="Committee name search"),
    committee_type: Optional[str] = Query(None, description="CAN, PAC, or PAR"),
    city: Optional[str] = Query(None, description="Contributor city"),
    min_amount: Optional[float] = Query(None, ge=0),
    max_amount: Optional[float] = Query(None),
    year_from: Optional[int] = Query(None, ge=DATA_START_YEAR),
    year_to: Optional[int] = Query(None, le=DATA_END_YEAR),
    recipient_id: Optional[int] = Query(None, description="Filter by matched recipient"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Search campaign contributions with filters.

    Data covers {DATA_START_YEAR}-{DATA_END_YEAR}.
    """
    query = db.query(CampaignContribution)

    # Apply filters
    if contributor:
        search_term = f"%{contributor.lower()}%"
        query = query.filter(
            or_(
                func.lower(CampaignContribution.contributor_name).like(search_term),
                func.lower(CampaignContribution.contributor_name_normalized).like(search_term),
                func.lower(CampaignContribution.contributor_last).like(search_term),
            )
        )

    if committee:
        search_term = f"%{committee.lower()}%"
        query = query.filter(
            func.lower(CampaignContribution.committee_name).like(search_term)
        )

    if committee_type:
        query = query.filter(CampaignContribution.committee_type == committee_type.upper())

    if city:
        query = query.filter(func.lower(CampaignContribution.city) == city.lower())

    if min_amount is not None:
        query = query.filter(CampaignContribution.amount >= min_amount)

    if max_amount is not None:
        query = query.filter(CampaignContribution.amount <= max_amount)

    if year_from is not None:
        query = query.filter(CampaignContribution.report_year >= year_from)

    if year_to is not None:
        query = query.filter(CampaignContribution.report_year <= year_to)

    if recipient_id is not None:
        query = query.filter(CampaignContribution.matched_recipient_id == recipient_id)

    # Get total count (skip for performance on large datasets)
    total_count = query.count()

    # Sort and paginate
    query = query.order_by(desc(CampaignContribution.amount))
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    items = [
        {
            "id": c.id,
            "contributor_name": c.contributor_name or f"{c.contributor_first or ''} {c.contributor_last or ''}".strip(),
            "address": c.address,
            "city": c.city,
            "state": c.state,
            "zip_code": c.zip_code,
            "amount": c.amount,
            "contribution_date": c.contribution_date.isoformat() if c.contribution_date else None,
            "report_year": c.report_year,
            "committee_name": c.committee_name,
            "committee_type": c.committee_type,
            "matched_recipient_id": c.matched_recipient_id,
        }
        for c in results
    ]

    total_pages = (total_count + page_size - 1) // page_size if total_count else 0

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
        "data_coverage": f"{DATA_START_YEAR}-{DATA_END_YEAR}",
    }


@router.get("/campaign-finance/top-donors")
async def get_top_donors(
    committee_type: Optional[str] = Query(None, description="CAN, PAC, or PAR"),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Get top campaign contributors by total amount donated.
    """
    query = db.query(
        CampaignContribution.contributor_name_normalized,
        CampaignContribution.city,
        CampaignContribution.state,
        CampaignContribution.matched_recipient_id,
        func.sum(CampaignContribution.amount).label("total_donated"),
        func.count(CampaignContribution.id).label("num_contributions"),
        func.min(CampaignContribution.report_year).label("first_year"),
        func.max(CampaignContribution.report_year).label("last_year"),
    ).filter(
        CampaignContribution.contributor_name_normalized.isnot(None),
        CampaignContribution.contributor_name_normalized != "",
    )

    if committee_type:
        query = query.filter(CampaignContribution.committee_type == committee_type.upper())

    if year_from:
        query = query.filter(CampaignContribution.report_year >= year_from)

    if year_to:
        query = query.filter(CampaignContribution.report_year <= year_to)

    query = query.group_by(
        CampaignContribution.contributor_name_normalized,
        CampaignContribution.city,
        CampaignContribution.state,
        CampaignContribution.matched_recipient_id,
    ).order_by(desc("total_donated")).limit(limit)

    results = query.all()

    # Get recipient names for matched donors
    recipient_ids = [r.matched_recipient_id for r in results if r.matched_recipient_id]
    recipient_lookup = {}
    if recipient_ids:
        recipients = db.query(Recipient.id, Recipient.name).filter(
            Recipient.id.in_(recipient_ids)
        ).all()
        recipient_lookup = {r.id: r.name for r in recipients}

    items = [
        {
            "contributor_name": r.contributor_name_normalized,
            "city": r.city,
            "state": r.state,
            "total_donated": float(r.total_donated),
            "num_contributions": r.num_contributions,
            "years_active": f"{r.first_year}-{r.last_year}",
            "matched_recipient_id": r.matched_recipient_id,
            "matched_recipient_name": recipient_lookup.get(r.matched_recipient_id),
            "is_award_recipient": r.matched_recipient_id is not None,
        }
        for r in results
    ]

    return {
        "items": items,
        "data_coverage": f"{DATA_START_YEAR}-{DATA_END_YEAR}",
        "filters": {
            "committee_type": committee_type,
            "year_from": year_from,
            "year_to": year_to,
        }
    }


@router.get("/campaign-finance/politicians")
async def list_politicians(
    search: Optional[str] = Query(None, description="Search by name"),
    office: Optional[str] = Query(None, description="Filter by office"),
    min_contributions: Optional[float] = Query(None, description="Minimum total contributions"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    List politicians/candidates extracted from campaign committees.
    """
    query = db.query(Politician)

    if search:
        search_term = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(Politician.name).like(search_term),
                func.lower(Politician.committee_name).like(search_term),
            )
        )

    if office:
        query = query.filter(func.lower(Politician.office).like(f"%{office.lower()}%"))

    if min_contributions:
        query = query.filter(Politician.total_contributions >= min_contributions)

    total_count = query.count()

    query = query.order_by(desc(Politician.total_contributions))
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    items = [
        {
            "id": p.id,
            "name": p.name,
            "committee_name": p.committee_name,
            "party": p.party,
            "office": p.office,
            "district": p.district,
            "total_contributions": p.total_contributions,
            "contribution_count": p.contribution_count,
            "years_active": p.years_active,
        }
        for p in results
    ]

    total_pages = (total_count + page_size - 1) // page_size if total_count else 0

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


@router.get("/campaign-finance/politicians/{politician_id}")
async def get_politician(
    politician_id: int,
    db: Session = Depends(get_db)
):
    """Get details for a specific politician."""
    politician = db.query(Politician).filter(Politician.id == politician_id).first()

    if not politician:
        raise HTTPException(status_code=404, detail="Politician not found")

    # Get top contributors to this politician
    top_contributors = db.query(
        CampaignContribution.contributor_name_normalized,
        CampaignContribution.city,
        CampaignContribution.matched_recipient_id,
        func.sum(CampaignContribution.amount).label("total"),
        func.count(CampaignContribution.id).label("count"),
    ).filter(
        CampaignContribution.master_key == politician.master_key
    ).group_by(
        CampaignContribution.contributor_name_normalized,
        CampaignContribution.city,
        CampaignContribution.matched_recipient_id,
    ).order_by(desc("total")).limit(20).all()

    contributors = [
        {
            "contributor_name": c.contributor_name_normalized,
            "city": c.city,
            "total_donated": float(c.total),
            "num_contributions": c.count,
            "is_award_recipient": c.matched_recipient_id is not None,
            "recipient_id": c.matched_recipient_id,
        }
        for c in top_contributors
    ]

    return {
        "id": politician.id,
        "name": politician.name,
        "committee_name": politician.committee_name,
        "party": politician.party,
        "office": politician.office,
        "district": politician.district,
        "total_contributions": politician.total_contributions,
        "contribution_count": politician.contribution_count,
        "years_active": politician.years_active,
        "top_contributors": contributors,
    }


@router.get("/campaign-finance/recipient/{recipient_id}/donations")
async def get_recipient_donations(
    recipient_id: int,
    db: Session = Depends(get_db)
):
    """
    Get all campaign donations made by a specific recipient.
    Shows potential pay-to-play connections.
    """
    # Get recipient info
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    # Get their donations
    donations = db.query(CampaignContribution).filter(
        CampaignContribution.matched_recipient_id == recipient_id
    ).order_by(desc(CampaignContribution.contribution_date)).all()

    # Calculate totals
    total_donated = sum(d.amount for d in donations)

    # Get their awards for comparison
    total_awards = db.query(func.sum(Award.amount)).filter(
        Award.recipient_id == recipient_id
    ).scalar() or 0

    # Get timeline data
    donation_items = [
        {
            "id": d.id,
            "amount": d.amount,
            "contribution_date": d.contribution_date.isoformat() if d.contribution_date else None,
            "report_year": d.report_year,
            "committee_name": d.committee_name,
            "committee_type": d.committee_type,
        }
        for d in donations
    ]

    # Group by committee for summary
    by_committee = {}
    for d in donations:
        key = d.committee_name
        if key not in by_committee:
            by_committee[key] = {"count": 0, "total": 0, "committee_type": d.committee_type}
        by_committee[key]["count"] += 1
        by_committee[key]["total"] += d.amount

    committees = [
        {"name": k, **v}
        for k, v in sorted(by_committee.items(), key=lambda x: x[1]["total"], reverse=True)
    ]

    return {
        "recipient": {
            "id": recipient.id,
            "name": recipient.name,
            "city": recipient.city,
        },
        "summary": {
            "total_donated": total_donated,
            "num_donations": len(donations),
            "total_awards_received": float(total_awards),
            "donation_to_award_ratio": total_donated / total_awards if total_awards > 0 else None,
        },
        "committees_donated_to": committees,
        "donations": donation_items,
        "data_coverage": f"{DATA_START_YEAR}-{DATA_END_YEAR}",
    }


@router.get("/campaign-finance/political-donors")
async def get_political_donors(
    min_donated: Optional[float] = Query(None, description="Minimum amount donated"),
    min_awards: Optional[float] = Query(None, description="Minimum awards received"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    List recipients who are also political donors.
    Core endpoint for pay-to-play analysis.
    """
    # Get recipients with political_donor flags
    query = db.query(FraudFlag).filter(
        FraudFlag.flag_type == "political_donor"
    ).join(Recipient, FraudFlag.recipient_id == Recipient.id)

    total_count = query.count()

    query = query.order_by(desc(FraudFlag.created_at))
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    # Get full recipient info
    recipient_ids = [f.recipient_id for f in results]
    recipients = {}
    if recipient_ids:
        for r in db.query(Recipient).filter(Recipient.id.in_(recipient_ids)).all():
            recipients[r.id] = r

    # Get award totals
    award_totals = {}
    if recipient_ids:
        awards = db.query(
            Award.recipient_id,
            func.sum(Award.amount).label("total"),
            func.count(Award.id).label("count"),
        ).filter(
            Award.recipient_id.in_(recipient_ids)
        ).group_by(Award.recipient_id).all()
        award_totals = {a.recipient_id: {"total": a.total, "count": a.count} for a in awards}

    # Get donation totals
    donation_totals = {}
    if recipient_ids:
        donations = db.query(
            CampaignContribution.matched_recipient_id,
            func.sum(CampaignContribution.amount).label("total"),
            func.count(CampaignContribution.id).label("count"),
        ).filter(
            CampaignContribution.matched_recipient_id.in_(recipient_ids)
        ).group_by(CampaignContribution.matched_recipient_id).all()
        donation_totals = {d.matched_recipient_id: {"total": d.total, "count": d.count} for d in donations}

    items = []
    for flag in results:
        r = recipients.get(flag.recipient_id)
        if not r:
            continue

        awards = award_totals.get(r.id, {"total": 0, "count": 0})
        donations = donation_totals.get(r.id, {"total": 0, "count": 0})

        # Apply filters
        if min_donated and donations["total"] < min_donated:
            continue
        if min_awards and awards["total"] < min_awards:
            continue

        items.append({
            "recipient_id": r.id,
            "recipient_name": r.name,
            "city": r.city,
            "business_type": r.business_type,
            "total_donated": float(donations["total"]),
            "num_donations": donations["count"],
            "total_awards": float(awards["total"]),
            "num_awards": awards["count"],
            "flag_severity": flag.severity,
            "flag_description": flag.description,
        })

    total_pages = (total_count + page_size - 1) // page_size if total_count else 0

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
        "data_coverage": f"{DATA_START_YEAR}-{DATA_END_YEAR}",
    }
