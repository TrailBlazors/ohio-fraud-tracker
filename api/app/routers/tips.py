"""
Tips API - Submit and manage fraud tips
"""

from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models import Tip

router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class TipCreate(BaseModel):
    submission_type: str  # fraud_report, data_correction, document_submission, investigation_lead
    subject: str
    description: str
    state: Optional[str] = "OH"
    fraud_types: Optional[List[str]] = []
    related_name: Optional[str] = None
    related_address: Optional[str] = None
    evidence: Optional[str] = None
    email: Optional[str] = None


class TipResponse(BaseModel):
    id: int
    submission_type: str
    subject: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/tips", response_model=TipResponse)
async def submit_tip(
    tip_data: TipCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Submit a new tip about potential fraud, waste, or abuse.
    Tips can be submitted anonymously.
    """
    # Validate submission type
    valid_types = ["fraud_report", "data_correction", "document_submission", "investigation_lead"]
    if tip_data.submission_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid submission_type. Must be one of: {valid_types}")

    # Validate required fields
    if not tip_data.subject or len(tip_data.subject.strip()) < 5:
        raise HTTPException(status_code=400, detail="Subject must be at least 5 characters")

    if not tip_data.description or len(tip_data.description.strip()) < 20:
        raise HTTPException(status_code=400, detail="Description must be at least 20 characters")

    # Create tip
    tip = Tip(
        submission_type=tip_data.submission_type,
        subject=tip_data.subject.strip()[:200],
        description=tip_data.description.strip()[:10000],
        state=tip_data.state[:2] if tip_data.state else "OH",
        fraud_types=",".join(tip_data.fraud_types) if tip_data.fraud_types else None,
        related_name=tip_data.related_name[:200] if tip_data.related_name else None,
        related_address=tip_data.related_address[:300] if tip_data.related_address else None,
        evidence=tip_data.evidence[:500] if tip_data.evidence else None,
        email=tip_data.email[:255] if tip_data.email else None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500],
        status="new",
    )

    db.add(tip)
    db.commit()
    db.refresh(tip)

    return tip


@router.get("/tips/stats")
async def get_tips_stats(db: Session = Depends(get_db)):
    """Get tip submission statistics (for admin dashboard)."""
    total = db.query(func.count(Tip.id)).scalar() or 0
    by_status = db.query(
        Tip.status,
        func.count(Tip.id)
    ).group_by(Tip.status).all()

    by_type = db.query(
        Tip.submission_type,
        func.count(Tip.id)
    ).group_by(Tip.submission_type).all()

    return {
        "total": total,
        "by_status": {row[0]: row[1] for row in by_status},
        "by_type": {row[0]: row[1] for row in by_type},
    }
