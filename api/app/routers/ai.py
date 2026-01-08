"""
AI-powered analysis endpoints.

Uses Claude to generate human-readable narratives explaining
why recipients may be suspicious based on their flags and data.
"""

import os
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models import Recipient, Award, FraudFlag, AIAnalysis, Agency

router = APIRouter()

# Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-3-haiku-20240307"  # Cheapest, fastest model
MAX_GENERATIONS_PER_DAY = 100
MIN_SEVERITY_FOR_AUTO = 8  # Only auto-eligible for severity >= 8
MIN_FLAGS_FOR_AUTO = 3     # Or 3+ flags


def get_anthropic_client():
    """Get Anthropic client, raising error if not configured."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI analysis not configured. Set ANTHROPIC_API_KEY environment variable."
        )
    try:
        import anthropic
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Anthropic SDK not installed."
        )


def compute_flags_hash(flags: list) -> str:
    """Compute hash of flag IDs for cache invalidation."""
    flag_ids = sorted([str(f.id) for f in flags])
    return hashlib.sha256(",".join(flag_ids).encode()).hexdigest()[:16]


def is_high_risk(recipient_id: int, db: Session) -> dict:
    """
    Check if recipient qualifies for AI analysis.
    Returns dict with eligible status and reason.
    """
    # Get flags for this recipient
    flags = db.query(FraudFlag).filter(
        FraudFlag.recipient_id == recipient_id,
        FraudFlag.is_resolved == False
    ).all()

    if not flags:
        return {"eligible": False, "reason": "No unresolved flags"}

    max_severity = max(f.severity for f in flags)
    flag_count = len(flags)

    # Get total funding
    total_amount = db.query(func.sum(Award.amount)).filter(
        Award.recipient_id == recipient_id
    ).scalar() or 0

    # Check dissolved/cancelled with significant funding
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    is_dissolved = recipient and recipient.business_status in ("dissolved", "cancelled", "inactive")

    # Eligibility criteria
    if max_severity >= MIN_SEVERITY_FOR_AUTO:
        return {"eligible": True, "reason": f"High severity flag ({max_severity}/10)"}
    if flag_count >= MIN_FLAGS_FOR_AUTO:
        return {"eligible": True, "reason": f"Multiple flags ({flag_count})"}
    if is_dissolved and total_amount >= 100000:
        return {"eligible": True, "reason": f"Dissolved business with ${total_amount:,.0f} in funding"}

    return {"eligible": False, "reason": f"Does not meet risk threshold (severity {max_severity}, {flag_count} flags)"}


def gather_recipient_context(recipient_id: int, db: Session) -> dict:
    """Gather all relevant data about a recipient for AI analysis."""
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    # Get flags
    flags = db.query(FraudFlag).filter(
        FraudFlag.recipient_id == recipient_id
    ).order_by(desc(FraudFlag.severity)).all()

    # Get award summary
    award_stats = db.query(
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total"),
        func.min(Award.award_date).label("first_date"),
        func.max(Award.award_date).label("last_date")
    ).filter(Award.recipient_id == recipient_id).first()

    # Get awards by source
    awards_by_source = db.query(
        Award.source,
        func.count(Award.id).label("count"),
        func.sum(Award.amount).label("total")
    ).filter(Award.recipient_id == recipient_id).group_by(Award.source).all()

    # Get top agencies
    top_agencies = db.query(
        Agency.name,
        func.sum(Award.amount).label("total")
    ).join(Award, Award.agency_id == Agency.id)\
     .filter(Award.recipient_id == recipient_id)\
     .group_by(Agency.name)\
     .order_by(desc("total"))\
     .limit(5).all()

    # Check for address matches (other recipients at same address)
    address_matches = []
    if recipient.address:
        matches = db.query(Recipient).filter(
            Recipient.address == recipient.address,
            Recipient.id != recipient_id
        ).limit(10).all()
        address_matches = [{"name": r.name, "id": r.id} for r in matches]

    return {
        "recipient": {
            "id": recipient.id,
            "name": recipient.name,
            "address": recipient.address,
            "city": recipient.city,
            "state": recipient.state,
            "zip_code": recipient.zip_code,
            "business_status": recipient.business_status,
            "naics_code": recipient.naics_code,
            "business_type": recipient.business_type,
        },
        "flags": [
            {
                "type": f.flag_type,
                "severity": f.severity,
                "description": f.description,
                "evidence": f.evidence,
                "is_resolved": f.is_resolved
            }
            for f in flags
        ],
        "awards": {
            "count": award_stats.count or 0,
            "total_amount": float(award_stats.total or 0),
            "first_date": str(award_stats.first_date) if award_stats.first_date else None,
            "last_date": str(award_stats.last_date) if award_stats.last_date else None,
            "by_source": [
                {"source": s.source, "count": s.count, "total": float(s.total or 0)}
                for s in awards_by_source
            ],
            "top_agencies": [
                {"name": a.name, "total": float(a.total or 0)}
                for a in top_agencies
            ]
        },
        "address_matches": address_matches
    }


def generate_narrative(context: dict) -> tuple[str, int]:
    """
    Generate AI narrative from recipient context.
    Returns (narrative, tokens_used).
    """
    client = get_anthropic_client()

    recipient = context["recipient"]
    flags = context["flags"]
    awards = context["awards"]
    address_matches = context["address_matches"]

    # Build the prompt
    prompt = f"""Analyze this government funding recipient and explain why they may warrant further investigation.
Be concise, factual, and highlight the most concerning issues first.

RECIPIENT:
- Name: {recipient['name']}
- Location: {recipient['city']}, {recipient['state']} {recipient['zip_code'] or ''}
- Address: {recipient['address'] or 'Not available'}
- Business Status: {recipient['business_status'] or 'Unknown'}
- Industry (NAICS): {recipient['naics_code'] or 'Not specified'}
- Business Type: {recipient['business_type'] or 'Not specified'}

FUNDING RECEIVED:
- Total Awards: {awards['count']:,}
- Total Amount: ${awards['total_amount']:,.2f}
- Date Range: {awards['first_date'] or 'Unknown'} to {awards['last_date'] or 'Unknown'}
- By Source: {', '.join([f"{s['source']}: ${s['total']:,.0f}" for s in awards['by_source']])}
- Top Funding Agencies: {', '.join([f"{a['name']}: ${a['total']:,.0f}" for a in awards['top_agencies'][:3]])}

RED FLAGS DETECTED ({len(flags)} total):
"""
    for i, flag in enumerate(flags[:10], 1):  # Limit to top 10 flags
        prompt += f"\n{i}. [{flag['type']}] Severity {flag['severity']}/10"
        prompt += f"\n   {flag['description']}"
        if flag['evidence']:
            prompt += f"\n   Evidence: {flag['evidence'][:200]}"

    if address_matches:
        prompt += f"\n\nADDRESS SHARING:\nThis address is shared with {len(address_matches)} other funding recipients:"
        for match in address_matches[:5]:
            prompt += f"\n- {match['name']}"

    prompt += """

Provide a 2-3 paragraph analysis that:
1. Summarizes the key concerns in plain English
2. Explains why the combination of factors is suspicious
3. Suggests what an investigator should look for

Be direct and specific. Do not hedge or use phrases like "may or may not be concerning."
If the data suggests potential fraud, say so clearly."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    narrative = response.content[0].text
    tokens_used = response.usage.input_tokens + response.usage.output_tokens

    return narrative, tokens_used


@router.get("/recipients/{recipient_id}/ai-analysis")
async def get_ai_analysis(
    recipient_id: int,
    force_regenerate: bool = Query(False, description="Force regenerate even if cached"),
    db: Session = Depends(get_db)
):
    """
    Get AI-generated analysis for a recipient.

    Returns cached analysis if available, or generates new one for high-risk recipients.
    """
    # Check if recipient exists
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    # Check eligibility
    risk_check = is_high_risk(recipient_id, db)

    # Check for cached analysis
    cached = db.query(AIAnalysis).filter(AIAnalysis.recipient_id == recipient_id).first()

    if cached and not force_regenerate:
        return {
            "recipient_id": recipient_id,
            "recipient_name": recipient.name,
            "narrative": cached.narrative,
            "generated_at": cached.generated_at.isoformat(),
            "model": cached.model_used,
            "cached": True,
            "eligible": risk_check["eligible"],
            "eligibility_reason": risk_check["reason"]
        }

    # If not eligible and no cache, return eligibility info only
    if not risk_check["eligible"]:
        return {
            "recipient_id": recipient_id,
            "recipient_name": recipient.name,
            "narrative": None,
            "generated_at": None,
            "cached": False,
            "eligible": False,
            "eligibility_reason": risk_check["reason"],
            "message": "This recipient does not meet the risk threshold for AI analysis."
        }

    # Rate limiting - check generations today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    generations_today = db.query(func.count(AIAnalysis.id)).filter(
        AIAnalysis.generated_at >= today_start
    ).scalar() or 0

    if generations_today >= MAX_GENERATIONS_PER_DAY and not cached:
        raise HTTPException(
            status_code=429,
            detail=f"Daily AI generation limit reached ({MAX_GENERATIONS_PER_DAY}). Try again tomorrow."
        )

    # Gather context and generate
    context = gather_recipient_context(recipient_id, db)
    flags = db.query(FraudFlag).filter(FraudFlag.recipient_id == recipient_id).all()

    try:
        narrative, tokens_used = generate_narrative(context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")

    # Cache the result
    if cached:
        cached.narrative = narrative
        cached.flags_hash = compute_flags_hash(flags)
        cached.awards_count = context["awards"]["count"]
        cached.total_amount = context["awards"]["total_amount"]
        cached.model_used = MODEL
        cached.tokens_used = tokens_used
        cached.generated_at = datetime.utcnow()
    else:
        cached = AIAnalysis(
            recipient_id=recipient_id,
            narrative=narrative,
            flags_hash=compute_flags_hash(flags),
            awards_count=context["awards"]["count"],
            total_amount=context["awards"]["total_amount"],
            model_used=MODEL,
            tokens_used=tokens_used
        )
        db.add(cached)

    db.commit()

    return {
        "recipient_id": recipient_id,
        "recipient_name": recipient.name,
        "narrative": narrative,
        "generated_at": cached.generated_at.isoformat(),
        "model": MODEL,
        "tokens_used": tokens_used,
        "cached": False,
        "eligible": True,
        "eligibility_reason": risk_check["reason"]
    }


@router.get("/ai/status")
async def ai_status(db: Session = Depends(get_db)):
    """Check AI analysis system status and usage."""
    configured = bool(ANTHROPIC_API_KEY)

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    generations_today = db.query(func.count(AIAnalysis.id)).filter(
        AIAnalysis.generated_at >= today_start
    ).scalar() or 0

    total_cached = db.query(func.count(AIAnalysis.id)).scalar() or 0
    total_tokens = db.query(func.sum(AIAnalysis.tokens_used)).scalar() or 0

    # Count eligible recipients
    high_severity_count = db.query(func.count(func.distinct(FraudFlag.recipient_id))).filter(
        FraudFlag.severity >= MIN_SEVERITY_FOR_AUTO,
        FraudFlag.is_resolved == False
    ).scalar() or 0

    return {
        "configured": configured,
        "model": MODEL,
        "daily_limit": MAX_GENERATIONS_PER_DAY,
        "generations_today": generations_today,
        "remaining_today": max(0, MAX_GENERATIONS_PER_DAY - generations_today),
        "total_cached_analyses": total_cached,
        "total_tokens_used": total_tokens,
        "eligible_recipients": high_severity_count,
        "min_severity_threshold": MIN_SEVERITY_FOR_AUTO,
        "min_flags_threshold": MIN_FLAGS_FOR_AUTO
    }
