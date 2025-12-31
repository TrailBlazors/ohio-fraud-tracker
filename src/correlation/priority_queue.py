"""
Prioritized Verification Queue

Determines which recipients to verify next based on:
1. High-dollar recipients (most money = most risk)
2. Multiple funding sources (cross-source = more scrutiny)
3. Recently added (new data needs verification)
4. Stale verification (not checked in 6+ months)
5. Never verified (no SOS data yet)

Usage:
    from src.correlation.priority_queue import get_verification_queue
    
    with get_db_context() as db:
        queue = get_verification_queue(db, limit=100)
        for recipient_id, priority, reason in queue:
            # verify recipient...
"""

import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_, case, desc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Priority(int, Enum):
    """Verification priority levels (lower = higher priority)"""
    CRITICAL = 1    # High dollar, never verified
    HIGH = 2        # Multi-source or >$500k
    MEDIUM = 3      # Recently added, moderate amounts
    LOW = 4         # Routine re-verification
    BACKGROUND = 5  # Stale but previously clean


def get_verification_queue(
    db: Session,
    limit: int = 100,
    min_amount: float = 10000,
    stale_days: int = 180
) -> List[Tuple[int, Priority, str]]:
    """
    Get prioritized list of recipients needing verification.
    
    Returns:
        List of (recipient_id, priority, reason) tuples
    """
    from api.app.models import Recipient, Award
    
    stale_date = datetime.utcnow() - timedelta(days=stale_days)
    recent_date = datetime.utcnow() - timedelta(days=30)
    
    queue = []
    seen_ids = set()
    
    # Priority 1: High-dollar recipients never verified
    high_dollar_unverified = db.query(
        Recipient.id,
        func.sum(Award.amount).label("total")
    ).join(
        Award, Award.recipient_id == Recipient.id
    ).filter(
        Recipient.sos_last_updated.is_(None)
    ).group_by(
        Recipient.id
    ).having(
        func.sum(Award.amount) >= 1000000  # $1M+
    ).order_by(
        desc("total")
    ).limit(limit // 4).all()
    
    for r in high_dollar_unverified:
        if r.id not in seen_ids:
            queue.append((r.id, Priority.CRITICAL, f"High-dollar (${r.total:,.0f}), never verified"))
            seen_ids.add(r.id)
    
    # Priority 2: Multi-source recipients
    multi_source = db.query(
        Recipient.id,
        func.count(func.distinct(Award.source)).label("source_count"),
        func.sum(Award.amount).label("total")
    ).join(
        Award, Award.recipient_id == Recipient.id
    ).filter(
        or_(
            Recipient.sos_last_updated.is_(None),
            Recipient.sos_last_updated < stale_date
        )
    ).group_by(
        Recipient.id
    ).having(
        func.count(func.distinct(Award.source)) >= 2
    ).order_by(
        desc("total")
    ).limit(limit // 4).all()
    
    for r in multi_source:
        if r.id not in seen_ids:
            queue.append((r.id, Priority.HIGH, f"Multi-source ({r.source_count} sources), ${r.total:,.0f}"))
            seen_ids.add(r.id)
    
    # Priority 3: Recently added, moderate amounts
    recently_added = db.query(
        Recipient.id,
        func.sum(Award.amount).label("total")
    ).join(
        Award, Award.recipient_id == Recipient.id
    ).filter(
        Recipient.created_at >= recent_date,
        Recipient.sos_last_updated.is_(None)
    ).group_by(
        Recipient.id
    ).having(
        func.sum(Award.amount) >= min_amount
    ).order_by(
        desc("total")
    ).limit(limit // 4).all()
    
    for r in recently_added:
        if r.id not in seen_ids:
            queue.append((r.id, Priority.MEDIUM, f"Recently added, ${r.total:,.0f}"))
            seen_ids.add(r.id)
    
    # Priority 4: Never verified (fill remaining slots)
    remaining = limit - len(queue)
    if remaining > 0:
        never_verified = db.query(
            Recipient.id,
            func.sum(Award.amount).label("total")
        ).join(
            Award, Award.recipient_id == Recipient.id
        ).filter(
            Recipient.sos_last_updated.is_(None),
            Recipient.id.notin_(seen_ids) if seen_ids else True
        ).group_by(
            Recipient.id
        ).having(
            func.sum(Award.amount) >= min_amount
        ).order_by(
            desc("total")
        ).limit(remaining).all()
        
        for r in never_verified:
            if r.id not in seen_ids:
                queue.append((r.id, Priority.LOW, f"Never verified, ${r.total:,.0f}"))
                seen_ids.add(r.id)
    
    # Priority 5: Stale verification (if still have room)
    remaining = limit - len(queue)
    if remaining > 0:
        stale = db.query(
            Recipient.id,
            Recipient.sos_last_updated
        ).filter(
            Recipient.sos_last_updated < stale_date,
            Recipient.id.notin_(seen_ids) if seen_ids else True
        ).order_by(
            Recipient.sos_last_updated
        ).limit(remaining).all()
        
        for r in stale:
            if r.id not in seen_ids:
                days_old = (datetime.utcnow() - r.sos_last_updated).days
                queue.append((r.id, Priority.BACKGROUND, f"Stale ({days_old} days old)"))
                seen_ids.add(r.id)
    
    # Sort by priority
    queue.sort(key=lambda x: x[1].value)
    
    return queue


def get_queue_stats(db: Session) -> dict:
    """Get statistics about the verification queue"""
    from api.app.models import Recipient, Award
    
    stale_date = datetime.utcnow() - timedelta(days=180)
    
    total_recipients = db.query(func.count(Recipient.id)).scalar() or 0
    
    never_verified = db.query(func.count(Recipient.id)).filter(
        Recipient.sos_last_updated.is_(None)
    ).scalar() or 0
    
    stale = db.query(func.count(Recipient.id)).filter(
        Recipient.sos_last_updated < stale_date
    ).scalar() or 0
    
    verified_current = total_recipients - never_verified - stale
    
    # High-dollar unverified
    high_dollar = db.query(func.count(Recipient.id)).join(
        Award, Award.recipient_id == Recipient.id
    ).filter(
        Recipient.sos_last_updated.is_(None)
    ).group_by(
        Recipient.id
    ).having(
        func.sum(Award.amount) >= 1000000
    ).count()
    
    return {
        "total_recipients": total_recipients,
        "never_verified": never_verified,
        "stale_verification": stale,
        "verified_current": verified_current,
        "high_dollar_unverified": high_dollar,
        "verification_rate": f"{(verified_current / total_recipients * 100):.1f}%" if total_recipients > 0 else "0%"
    }
