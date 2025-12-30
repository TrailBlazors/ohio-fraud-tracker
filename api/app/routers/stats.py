"""
Statistics and dashboard endpoints
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models import Award, Recipient, Agency, FraudFlag
from app.schemas import DashboardStats, AwardListItem, AgencySummary

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(db: Session = Depends(get_db)):
    """
    Get homepage dashboard statistics
    """
    # Total counts
    total_awards = db.query(func.count(Award.id)).scalar() or 0
    total_amount = db.query(func.sum(Award.amount)).scalar() or 0
    total_recipients = db.query(func.count(Recipient.id)).scalar() or 0
    total_flagged = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.is_resolved == False
    ).scalar() or 0
    
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
    
    return DashboardStats(
        total_awards=total_awards,
        total_amount=float(total_amount),
        total_recipients=total_recipients,
        total_flagged=total_flagged,
        awards_by_type=awards_by_type,
        awards_by_source=awards_by_source,
        top_agencies=top_agencies,
        recent_awards=recent_awards
    )


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
