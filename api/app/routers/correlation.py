"""
Correlation and fraud detection endpoints
"""

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import json

from app.database import get_db
from app.models import Award, Recipient, FraudFlag

router = APIRouter()


# ============== Correlation Engine (inlined) ==============

class FlagType(Enum):
    """Types of fraud flags"""
    DUPLICATE_AWARD = "duplicate_award"
    OUTLIER_AMOUNT = "outlier_amount"
    MULTIPLE_RECIPIENTS_SAME_ADDRESS = "multiple_recipients_same_address"
    INACTIVE_BUSINESS = "inactive_business"
    HIGH_VOLUME_RECIPIENT = "high_volume_recipient"
    MULTI_SOURCE_FUNDING = "multi_source_funding"


class Severity(Enum):
    """Severity levels for flags"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Flag:
    """A detected fraud flag"""
    flag_type: FlagType
    severity: Severity
    description: str
    recipient_id: Optional[int] = None
    award_id: Optional[int] = None
    evidence: Optional[Dict[str, Any]] = None


class CorrelationEngine:
    """Engine for running fraud correlation analysis"""
    
    def __init__(self, db: Session):
        self.db = db
        self.flags: List[Flag] = []
    
    def run_full_scan(self) -> List[Flag]:
        """Run all correlation checks"""
        self.flags = []
        
        print("  Checking for duplicate awards...")
        self._check_duplicate_awards()
        
        print("  Checking for outlier amounts...")
        self._check_outlier_amounts()
        
        print("  Checking for multiple recipients at same address...")
        self._check_duplicate_addresses()
        
        print("  Checking for inactive businesses...")
        self._check_inactive_businesses()
        
        print("  Checking for high volume recipients...")
        self._check_high_volume_recipients()
        
        return self.flags
    
    def _check_duplicate_awards(self):
        """Find potential duplicate awards (same recipient, similar amount, close dates)"""
        
        # Find near-duplicates: same recipient, amount within 1%, dates within 30 days
        query = text("""
            SELECT 
                a1.id as award1_id,
                a2.id as award2_id,
                a1.recipient_id,
                a1.amount as amount1,
                a2.amount as amount2,
                a1.award_date as date1,
                a2.award_date as date2,
                a1.source as source1,
                a2.source as source2,
                a1.description as desc1,
                a2.description as desc2
            FROM awards a1
            JOIN awards a2 ON a1.recipient_id = a2.recipient_id
                AND a1.id < a2.id
            WHERE a1.award_date IS NOT NULL 
                AND a2.award_date IS NOT NULL
                AND a1.amount > 1000
                AND ABS(a1.amount - a2.amount) / a1.amount < 0.01
                AND ABS(julianday(a1.award_date) - julianday(a2.award_date)) <= 30
            ORDER BY a1.amount DESC
            LIMIT 500
        """)
        
        results = self.db.execute(query).fetchall()
        
        seen_pairs = set()
        
        for row in results:
            pair_key = (min(row.award1_id, row.award2_id), max(row.award1_id, row.award2_id))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            
            amount_diff_pct = abs(row.amount1 - row.amount2) / row.amount1 * 100
            date_diff = abs((row.date1 - row.date2).days) if row.date1 and row.date2 else 0
            
            if amount_diff_pct == 0 and date_diff == 0:
                severity = Severity.CRITICAL if row.amount1 > 100000 else Severity.HIGH
                match_type = "exact"
            elif amount_diff_pct < 0.1 and date_diff <= 7:
                severity = Severity.HIGH if row.amount1 > 50000 else Severity.MEDIUM
                match_type = "near_exact"
            else:
                severity = Severity.MEDIUM if row.amount1 > 50000 else Severity.LOW
                match_type = "similar"
            
            self.flags.append(Flag(
                flag_type=FlagType.DUPLICATE_AWARD,
                severity=severity,
                description=f"Potential duplicate: ${row.amount1:,.0f} and ${row.amount2:,.0f} within {date_diff} days",
                recipient_id=row.recipient_id,
                award_id=row.award1_id,
                evidence={
                    "match_type": match_type,
                    "award1": {
                        "id": row.award1_id,
                        "amount": float(row.amount1),
                        "date": str(row.date1),
                        "source": row.source1,
                        "description": (row.desc1 or "")[:200]
                    },
                    "award2": {
                        "id": row.award2_id,
                        "amount": float(row.amount2),
                        "date": str(row.date2),
                        "source": row.source2,
                        "description": (row.desc2 or "")[:200]
                    },
                    "amount_diff_pct": round(amount_diff_pct, 2),
                    "date_diff_days": date_diff
                }
            ))
    
    def _check_outlier_amounts(self):
        """Find awards that are significantly above average for their type"""
        
        averages = self.db.query(
            Award.award_type,
            func.avg(Award.amount).label("avg"),
            func.stddev(Award.amount).label("stddev")
        ).group_by(Award.award_type).all()
        
        for avg_row in averages:
            if not avg_row.avg or not avg_row.stddev:
                continue
            
            threshold = avg_row.avg + (5 * avg_row.stddev)
            
            outliers = self.db.query(Award).filter(
                Award.award_type == avg_row.award_type,
                Award.amount > threshold,
                Award.amount > 1000000
            ).limit(100).all()
            
            for award in outliers:
                self.flags.append(Flag(
                    flag_type=FlagType.OUTLIER_AMOUNT,
                    severity=Severity.MEDIUM,
                    description=f"Outlier amount: ${award.amount:,.0f} (avg for {award.award_type}: ${avg_row.avg:,.0f})",
                    recipient_id=award.recipient_id,
                    award_id=award.id,
                    evidence={
                        "amount": award.amount,
                        "average": avg_row.avg,
                        "stddev": avg_row.stddev,
                        "award_type": award.award_type
                    }
                ))
    
    def _check_duplicate_addresses(self):
        """Find addresses with multiple recipients receiving awards"""
        
        address_counts = self.db.query(
            Recipient.address,
            Recipient.city,
            func.count(Recipient.id).label("recipient_count")
        ).filter(
            Recipient.address.isnot(None),
            Recipient.address != "",
            func.length(Recipient.address) > 5
        ).group_by(
            Recipient.address,
            Recipient.city
        ).having(
            func.count(Recipient.id) >= 3
        ).all()
        
        for addr in address_counts:
            total = self.db.query(func.sum(Award.amount)).join(
                Recipient, Award.recipient_id == Recipient.id
            ).filter(
                Recipient.address == addr.address,
                Recipient.city == addr.city
            ).scalar() or 0
            
            if total < 100000:
                continue
            
            recipients = self.db.query(Recipient.id, Recipient.name).filter(
                Recipient.address == addr.address,
                Recipient.city == addr.city
            ).all()
            
            self.flags.append(Flag(
                flag_type=FlagType.MULTIPLE_RECIPIENTS_SAME_ADDRESS,
                severity=Severity.HIGH if addr.recipient_count >= 5 else Severity.MEDIUM,
                description=f"{addr.recipient_count} recipients at {addr.address}, {addr.city} - ${total:,.0f} total",
                evidence={
                    "address": addr.address,
                    "city": addr.city,
                    "recipient_count": addr.recipient_count,
                    "total_funding": total,
                    "recipient_ids": [r.id for r in recipients[:10]]
                }
            ))
    
    def _check_inactive_businesses(self):
        """Find inactive/dissolved businesses that received recent funding"""
        
        inactive = self.db.query(
            Recipient.id,
            Recipient.name,
            Recipient.business_status,
            func.sum(Award.amount).label("total"),
            func.max(Award.award_date).label("last_award")
        ).join(
            Award, Award.recipient_id == Recipient.id
        ).filter(
            Recipient.business_status.in_(["inactive", "dissolved", "cancelled"])
        ).group_by(
            Recipient.id
        ).having(
            func.sum(Award.amount) > 10000
        ).all()
        
        for r in inactive:
            self.flags.append(Flag(
                flag_type=FlagType.INACTIVE_BUSINESS,
                severity=Severity.HIGH,
                description=f"{r.business_status.upper()} business '{r.name}' received ${r.total:,.0f}",
                recipient_id=r.id,
                evidence={
                    "business_status": r.business_status,
                    "total_funding": r.total,
                    "last_award_date": str(r.last_award) if r.last_award else None
                }
            ))
    
    def _check_high_volume_recipients(self):
        """Find recipients with unusually high number of awards"""
        
        high_volume = self.db.query(
            Recipient.id,
            Recipient.name,
            func.count(Award.id).label("award_count"),
            func.sum(Award.amount).label("total")
        ).join(
            Award, Award.recipient_id == Recipient.id
        ).group_by(
            Recipient.id
        ).having(
            func.count(Award.id) >= 50
        ).order_by(
            func.count(Award.id).desc()
        ).limit(50).all()
        
        for r in high_volume:
            self.flags.append(Flag(
                flag_type=FlagType.HIGH_VOLUME_RECIPIENT,
                severity=Severity.LOW,
                description=f"High volume: '{r.name}' has {r.award_count} awards totaling ${r.total:,.0f}",
                recipient_id=r.id,
                evidence={
                    "award_count": r.award_count,
                    "total_funding": r.total
                }
            ))
    
    def save_flags_to_db(self, flags: List[Flag]) -> int:
        """Save flags to database, avoiding duplicates"""
        saved = 0
        
        for flag in flags:
            existing = self.db.query(FraudFlag).filter(
                FraudFlag.flag_type == flag.flag_type.value,
                FraudFlag.recipient_id == flag.recipient_id,
                FraudFlag.is_resolved == False
            ).first()
            
            if existing:
                continue
            
            db_flag = FraudFlag(
                flag_type=flag.flag_type.value,
                severity=flag.severity.value,
                description=flag.description,
                recipient_id=flag.recipient_id,
                award_id=flag.award_id,
                evidence=json.dumps(flag.evidence) if flag.evidence else None,
                is_resolved=False,
                created_at=datetime.utcnow()
            )
            self.db.add(db_flag)
            saved += 1
        
        self.db.commit()
        return saved


# ============== API Endpoints ==============


@router.get("/correlation/duplicates")
async def get_duplicate_awards(
    severity: Optional[str] = Query(None, description="Filter by severity"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Get detected duplicate award pairs.
    Returns flags of type 'duplicate_award' with full evidence.
    """
    query = db.query(FraudFlag).filter(
        FraudFlag.flag_type == "duplicate_award",
        FraudFlag.is_resolved == False
    )
    
    if severity:
        query = query.filter(FraudFlag.severity == severity)
    
    total = query.count()
    
    # Calculate total amount at risk
    all_flags = query.all()
    total_at_risk = 0
    for flag in all_flags:
        if flag.evidence:
            evidence = json.loads(flag.evidence)
            # Add the smaller of the two amounts (potential double-payment)
            if "award1" in evidence and "award2" in evidence:
                total_at_risk += min(evidence["award1"].get("amount", 0), evidence["award2"].get("amount", 0))
    
    # Get paginated results
    flags = query.order_by(
        desc(FraudFlag.severity == "critical"),
        desc(FraudFlag.severity == "high"),
        desc(FraudFlag.created_at)
    ).offset(offset).limit(limit).all()
    
    results = []
    for flag in flags:
        # Get recipient info
        recipient = db.query(Recipient.name, Recipient.city).filter(
            Recipient.id == flag.recipient_id
        ).first()
        
        evidence = json.loads(flag.evidence) if flag.evidence else {}
        
        results.append({
            "id": flag.id,
            "severity": flag.severity,
            "description": flag.description,
            "recipient_id": flag.recipient_id,
            "recipient_name": recipient.name if recipient else None,
            "recipient_city": recipient.city if recipient else None,
            "match_type": evidence.get("match_type"),
            "award1": evidence.get("award1"),
            "award2": evidence.get("award2"),
            "amount_diff_pct": evidence.get("amount_diff_pct"),
            "date_diff_days": evidence.get("date_diff_days"),
            "is_resolved": flag.is_resolved,
            "notes": flag.notes,
            "created_at": flag.created_at.isoformat() if flag.created_at else None
        })
    
    # Summary by severity
    severity_counts = db.query(
        FraudFlag.severity,
        func.count(FraudFlag.id).label("count")
    ).filter(
        FraudFlag.flag_type == "duplicate_award",
        FraudFlag.is_resolved == False
    ).group_by(FraudFlag.severity).all()
    
    return {
        "total": total,
        "total_at_risk": total_at_risk,
        "by_severity": {s.severity: s.count for s in severity_counts},
        "duplicates": results
    }


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
    try:
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
