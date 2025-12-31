"""
Correlation and fraud detection endpoints
"""

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Optional, List
from datetime import datetime
import json

from app.database import get_db
from app.models import Award, Recipient, FraudFlag

router = APIRouter()


@router.get("/correlation/flags")
async def get_fraud_flags(
    severity: Optional[str] = Query(None, description="Filter by severity: low, medium, high, critical"),
    flag_type: Optional[str] = Query(None, description="Filter by flag type"),
    is_resolved: Optional[bool] = Query(None, description="Filter by resolution status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get fraud flags with filtering"""
    query = db.query(FraudFlag)
    
    if severity:
        query = query.filter(FraudFlag.severity == severity)
    if flag_type:
        query = query.filter(FraudFlag.flag_type == flag_type)
    if is_resolved is not None:
        query = query.filter(FraudFlag.is_resolved == is_resolved)
    
    total = query.count()
    
    flags = query.order_by(
        desc(FraudFlag.created_at)
    ).offset(offset).limit(limit).all()
    
    results = []
    for flag in flags:
        recipient_name = None
        if flag.recipient_id:
            recipient = db.query(Recipient.name).filter(
                Recipient.id == flag.recipient_id
            ).first()
            recipient_name = recipient.name if recipient else None
        
        results.append({
            "id": flag.id,
            "flag_type": flag.flag_type,
            "severity": flag.severity,
            "description": flag.description,
            "recipient_id": flag.recipient_id,
            "recipient_name": recipient_name,
            "award_id": flag.award_id,
            "evidence": json.loads(flag.evidence) if flag.evidence else {},
            "is_resolved": flag.is_resolved,
            "notes": flag.notes,
            "created_at": flag.created_at.isoformat() if flag.created_at else None
        })
    
    return {
        "total": total,
        "flags": results
    }


@router.get("/correlation/flags/summary")
async def get_flags_summary(db: Session = Depends(get_db)):
    """Get summary statistics for fraud flags"""
    
    # Count by severity
    severity_counts = db.query(
        FraudFlag.severity,
        func.count(FraudFlag.id).label("count")
    ).filter(
        FraudFlag.is_resolved == False
    ).group_by(FraudFlag.severity).all()
    
    # Count by type
    type_counts = db.query(
        FraudFlag.flag_type,
        func.count(FraudFlag.id).label("count")
    ).filter(
        FraudFlag.is_resolved == False
    ).group_by(FraudFlag.flag_type).all()
    
    # Resolution stats
    total_flags = db.query(func.count(FraudFlag.id)).scalar() or 0
    resolved = db.query(func.count(FraudFlag.id)).filter(
        FraudFlag.is_resolved == True
    ).scalar() or 0
    
    return {
        "total_flags": total_flags,
        "unresolved": total_flags - resolved,
        "resolved": resolved,
        "by_severity": {s.severity: s.count for s in severity_counts},
        "by_type": {t.flag_type: t.count for t in type_counts}
    }


@router.patch("/correlation/flags/{flag_id}")
async def update_flag(
    flag_id: int,
    is_resolved: Optional[bool] = None,
    notes: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Update a fraud flag (mark resolved, add notes)"""
    flag = db.query(FraudFlag).filter(FraudFlag.id == flag_id).first()
    
    if not flag:
        return {"error": "Flag not found"}
    
    if is_resolved is not None:
        flag.is_resolved = is_resolved
        if is_resolved:
            flag.reviewed_at = datetime.utcnow()
    
    if notes is not None:
        flag.notes = notes
    
    db.commit()
    
    return {"success": True, "flag_id": flag_id}


@router.post("/correlation/run")
async def run_correlation_analysis(
    background_tasks: BackgroundTasks,
    save: bool = Query(True, description="Save flags to database"),
    db: Session = Depends(get_db)
):
    """
    Run correlation analysis to detect fraud indicators.
    
    Scans for:
    - Duplicate awards (same recipient, amount, date)
    - Outlier amounts (5x above average)
    - Multiple recipients at same address
    """
    import sys
    from pathlib import Path
    
    # Add paths for imports
    api_path = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(api_path))
    sys.path.insert(0, str(api_path.parent))
    
    try:
        from src.correlation.engine import CorrelationEngine
        
        engine = CorrelationEngine(db)
        flags = engine.run_full_scan()
        
        saved_count = 0
        if save and flags:
            saved_count = engine.save_flags_to_db(flags)
        
        # Summarize results
        by_type = {}
        by_severity = {}
        for flag in flags:
            by_type[flag.flag_type.value] = by_type.get(flag.flag_type.value, 0) + 1
            by_severity[flag.severity.value] = by_severity.get(flag.severity.value, 0) + 1
        
        return {
            "success": True,
            "flags_found": len(flags),
            "flags_saved": saved_count,
            "by_severity": by_severity,
            "by_type": by_type
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/correlation/multi-source")
async def get_multi_source_recipients(
    min_sources: int = Query(2, ge=2),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Find recipients receiving funding from multiple sources"""
    
    multi_source = db.query(
        Recipient.id,
        Recipient.name,
        Recipient.city,
        Recipient.business_status,
        func.count(func.distinct(Award.source)).label("source_count"),
        func.sum(Award.amount).label("total_amount"),
        func.count(Award.id).label("award_count")
    ).join(
        Award, Award.recipient_id == Recipient.id
    ).group_by(
        Recipient.id
    ).having(
        func.count(func.distinct(Award.source)) >= min_sources
    ).order_by(
        func.sum(Award.amount).desc()
    ).limit(limit).all()
    
    results = []
    for r in multi_source:
        # Get breakdown by source
        source_breakdown = db.query(
            Award.source,
            func.sum(Award.amount).label("amount"),
            func.count(Award.id).label("count")
        ).filter(
            Award.recipient_id == r.id
        ).group_by(Award.source).all()
        
        results.append({
            "recipient_id": r.id,
            "name": r.name,
            "city": r.city,
            "business_status": r.business_status,
            "source_count": r.source_count,
            "total_amount": float(r.total_amount),
            "award_count": r.award_count,
            "by_source": [
                {"source": s.source, "amount": float(s.amount), "count": s.count}
                for s in source_breakdown
            ]
        })
    
    return {"recipients": results, "total": len(results)}


@router.get("/correlation/duplicate-addresses")
async def get_duplicate_addresses(
    min_recipients: int = Query(3, ge=2),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Find addresses with multiple recipients"""
    
    address_counts = db.query(
        Recipient.address,
        Recipient.city,
        func.count(Recipient.id).label("count")
    ).filter(
        Recipient.address.isnot(None),
        Recipient.address != ""
    ).group_by(
        Recipient.address,
        Recipient.city
    ).having(
        func.count(Recipient.id) >= min_recipients
    ).order_by(
        desc("count")
    ).limit(limit).all()
    
    results = []
    for addr in address_counts:
        # Get recipients at this address
        recipients = db.query(
            Recipient.id,
            Recipient.name,
            func.sum(Award.amount).label("total")
        ).outerjoin(
            Award, Award.recipient_id == Recipient.id
        ).filter(
            Recipient.address == addr.address,
            Recipient.city == addr.city
        ).group_by(Recipient.id).all()
        
        total_amount = sum(r.total or 0 for r in recipients)
        
        results.append({
            "address": addr.address,
            "city": addr.city,
            "recipient_count": addr.count,
            "total_amount": float(total_amount),
            "recipients": [
                {"id": r.id, "name": r.name, "amount": float(r.total or 0)}
                for r in recipients[:10]  # First 10
            ]
        })
    
    return {"addresses": results, "total": len(results)}


@router.get("/correlation/recipient/{recipient_id}/verify")
async def verify_recipient(
    recipient_id: int,
    db: Session = Depends(get_db)
):
    """
    Get verification status for a recipient.
    Shows data from Ohio SOS if available.
    """
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    
    if not recipient:
        return {"error": "Recipient not found"}
    
    # Get awards
    awards = db.query(
        Award.source,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total"),
        func.min(Award.award_date).label("first_award"),
        func.max(Award.award_date).label("last_award")
    ).filter(
        Award.recipient_id == recipient_id
    ).group_by(Award.source).all()
    
    # Get flags for this recipient
    flags = db.query(FraudFlag).filter(
        FraudFlag.recipient_id == recipient_id,
        FraudFlag.is_resolved == False
    ).all()
    
    return {
        "recipient": {
            "id": recipient.id,
            "name": recipient.name,
            "city": recipient.city,
            "address": recipient.address,
            "ohio_entity_number": recipient.ohio_entity_number,
            "business_status": recipient.business_status,
            "formation_date": recipient.formation_date.isoformat() if recipient.formation_date else None,
            "sos_last_updated": recipient.sos_last_updated.isoformat() if recipient.sos_last_updated else None,
            "naics_code": recipient.naics_code,
            "business_type": recipient.business_type
        },
        "awards_by_source": [
            {
                "source": a.source,
                "count": a.count,
                "total": float(a.total),
                "first_award": a.first_award.isoformat() if a.first_award else None,
                "last_award": a.last_award.isoformat() if a.last_award else None
            }
            for a in awards
        ],
        "open_flags": [
            {
                "id": f.id,
                "type": f.flag_type,
                "severity": f.severity,
                "description": f.description
            }
            for f in flags
        ],
        "verification_status": "verified" if recipient.sos_last_updated else "pending"
    }
