"""
LEIE Exclusions endpoints - OIG excluded providers cross-referenced against Ohio recipients.
"""

import ast
import json
import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case

from app.database import get_db
from app.models import Award, ExcludedEntity, FraudFlag, Recipient

router = APIRouter()

_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 3600        # 1 hour for search results
MATCHES_TTL = 43200     # 12 hours — only changes after an import run


def _get_cached(key: str, ttl: float = CACHE_TTL):
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < ttl:
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
    cached = _get_cached("exclusions_stats", MATCHES_TTL)
    if cached:
        return cached

    # Single pass over excluded_entities for all counts
    row = db.query(
        func.count(ExcludedEntity.id),
        func.sum(case((ExcludedEntity.state == "OH", 1), else_=0)),
        func.sum(case((ExcludedEntity.general_type == "INDIV", 1), else_=0)),
        func.sum(case((ExcludedEntity.general_type == "ENTITY", 1), else_=0)),
        func.sum(case((ExcludedEntity.reinstatement_date == None, 1), else_=0)),  # noqa: E711
    ).one()

    flagged_recipients = (
        db.query(func.count(FraudFlag.id))
        .filter(FraudFlag.flag_type == "excluded_provider")
        .scalar() or 0
    )

    result = {
        "total": int(row[0] or 0),
        "ohio_count": int(row[1] or 0),
        "individuals": int(row[2] or 0),
        "entities": int(row[3] or 0),
        "active_count": int(row[4] or 0),
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
    cache_key = f"matches:{page}:{page_size}"
    cached = _get_cached(cache_key, MATCHES_TTL)
    if cached:
        return cached

    offset = (page - 1) * page_size

    total = (
        db.query(func.count(FraudFlag.id))
        .filter(FraudFlag.flag_type == "excluded_provider")
        .scalar() or 0
    )

    # Step 1: fetch this page of flagged recipients
    flag_rows = (
        db.query(FraudFlag, Recipient)
        .join(Recipient, FraudFlag.recipient_id == Recipient.id)
        .filter(FraudFlag.flag_type == "excluded_provider")
        .order_by(desc(FraudFlag.created_at))
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # Step 2: award totals only for the ~25 recipients on this page
    recipient_ids = [r.id for _, r in flag_rows]
    award_totals: dict[int, tuple[float, int]] = {}
    if recipient_ids:
        totals = (
            db.query(
                Award.recipient_id,
                func.sum(Award.amount).label("total_amount"),
                func.count(Award.id).label("award_count"),
            )
            .filter(Award.recipient_id.in_(recipient_ids))
            .group_by(Award.recipient_id)
            .all()
        )
        award_totals = {row.recipient_id: (float(row.total_amount or 0), int(row.award_count or 0)) for row in totals}

    items = []
    for flag, recipient in flag_rows:
        evidence = _parse_evidence(flag.evidence)
        ta, ac = award_totals.get(recipient.id, (0.0, 0))
        items.append({
            "recipient_id": recipient.id,
            "recipient_name": recipient.name,
            "city": recipient.city,
            "state": recipient.state,
            "total_amount": ta,
            "award_count": ac,
            "flag_description": flag.description,
            "flag_created_at": flag.created_at.isoformat() if flag.created_at else None,
            "excluded_name": evidence.get("excluded_name"),
            "exclusion_date": evidence.get("exclusion_date"),
            "exclusion_type": evidence.get("exclusion_type"),
            "specialty": evidence.get("specialty"),
            "npi": evidence.get("npi"),
        })

    result = {"items": items, "total": total, "page": page, "page_size": page_size}
    _set_cached(cache_key, result)
    return result


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
