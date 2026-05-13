"""
LEIE Exclusions endpoints - OIG excluded providers cross-referenced against Ohio recipients.
"""

import ast
import json
import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.models import Award, ExcludedEntity, FraudFlag, Recipient

router = APIRouter()

_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 3600  # 1 hour


def _get_cached(key: str):
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return val
    return None


def _set_cached(key: str, value: Any):
    _cache[key] = (time.time(), value)


def _parse_evidence(evidence_str: str | None) -> dict:
    if not evidence_str:
        return {}
    try:
        return json.loads(evidence_str)
    except Exception:
        try:
            return ast.literal_eval(evidence_str)
        except Exception:
            return {}


@router.get("/exclusions/stats")
async def get_exclusions_stats(db: Session = Depends(get_db)):
    cached = _get_cached("exclusions_stats")
    if cached:
        return cached

    total = db.query(func.count(ExcludedEntity.id)).scalar() or 0
    ohio_count = (
        db.query(func.count(ExcludedEntity.id))
        .filter(ExcludedEntity.state == "OH")
        .scalar() or 0
    )
    individuals = (
        db.query(func.count(ExcludedEntity.id))
        .filter(ExcludedEntity.general_type == "INDIV")
        .scalar() or 0
    )
    entities = (
        db.query(func.count(ExcludedEntity.id))
        .filter(ExcludedEntity.general_type == "ENTITY")
        .scalar() or 0
    )
    active_count = (
        db.query(func.count(ExcludedEntity.id))
        .filter(ExcludedEntity.reinstatement_date == None)  # noqa: E711
        .scalar() or 0
    )
    flagged_recipients = (
        db.query(func.count(FraudFlag.id))
        .filter(FraudFlag.flag_type == "excluded_provider")
        .scalar() or 0
    )

    result = {
        "total": total,
        "ohio_count": ohio_count,
        "individuals": individuals,
        "entities": entities,
        "active_count": active_count,
        "flagged_recipients": flagged_recipients,
    }
    _set_cached("exclusions_stats", result)
    return result


@router.get("/exclusions/matches")
async def get_exclusion_matches(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * page_size

    flags_with_recipients = (
        db.query(FraudFlag, Recipient)
        .join(Recipient, FraudFlag.recipient_id == Recipient.id)
        .filter(FraudFlag.flag_type == "excluded_provider")
        .order_by(desc(FraudFlag.created_at))
        .offset(offset)
        .limit(page_size)
        .all()
    )

    total = (
        db.query(func.count(FraudFlag.id))
        .filter(FraudFlag.flag_type == "excluded_provider")
        .scalar() or 0
    )

    # Batch-fetch award totals for all recipients in this page
    recipient_ids = [r.id for _, r in flags_with_recipients]
    award_totals: dict[int, dict] = {}
    if recipient_ids:
        rows = (
            db.query(Award.recipient_id, func.sum(Award.amount), func.count(Award.id))
            .filter(Award.recipient_id.in_(recipient_ids))
            .group_by(Award.recipient_id)
            .all()
        )
        for rid, total_amt, cnt in rows:
            award_totals[rid] = {"total_amount": float(total_amt or 0), "award_count": cnt}

    items = []
    for flag, recipient in flags_with_recipients:
        evidence = _parse_evidence(flag.evidence)
        items.append({
            "recipient_id": recipient.id,
            "recipient_name": recipient.name,
            "city": recipient.city,
            "state": recipient.state,
            "total_amount": award_totals.get(recipient.id, {}).get("total_amount", 0.0),
            "award_count": award_totals.get(recipient.id, {}).get("award_count", 0),
            "flag_description": flag.description,
            "flag_created_at": flag.created_at.isoformat() if flag.created_at else None,
            "excluded_name": evidence.get("excluded_name"),
            "exclusion_date": evidence.get("exclusion_date"),
            "exclusion_type": evidence.get("exclusion_type"),
            "specialty": evidence.get("specialty"),
            "npi": evidence.get("npi"),
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/exclusions")
async def search_exclusions(
    q: Optional[str] = Query(None),
    state: Optional[str] = Query("OH"),
    general_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    fast: bool = Query(False),
    db: Session = Depends(get_db),
):
    query = db.query(ExcludedEntity)

    if q:
        query = query.filter(ExcludedEntity.name_normalized.ilike(f"%{q.lower()}%"))
    if state and state.lower() != "all":
        query = query.filter(ExcludedEntity.state == state.upper())
    if general_type in ("INDIV", "ENTITY"):
        query = query.filter(ExcludedEntity.general_type == general_type)
    if active_only:
        query = query.filter(ExcludedEntity.reinstatement_date == None)  # noqa: E711

    total = None if fast else query.count()

    offset = (page - 1) * page_size
    rows = (
        query.order_by(desc(ExcludedEntity.exclusion_date))
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": e.id,
            "last_name": e.last_name,
            "first_name": e.first_name,
            "middle_name": e.middle_name,
            "business_name": e.business_name,
            "general_type": e.general_type,
            "specialty": e.specialty,
            "npi": e.npi,
            "city": e.city,
            "state": e.state,
            "zip_code": e.zip_code,
            "exclusion_type": e.exclusion_type,
            "exclusion_date": e.exclusion_date.isoformat() if e.exclusion_date else None,
            "reinstatement_date": e.reinstatement_date.isoformat() if e.reinstatement_date else None,
        }
        for e in rows
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}
