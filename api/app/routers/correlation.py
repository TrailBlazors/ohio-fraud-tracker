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
    FUNDING_BEFORE_FORMATION = "funding_before_formation"  # Award before business formed
    # IRS 990 flags
    NONPROFIT_REVENUE_MISMATCH = "nonprofit_revenue_mismatch"  # Grants > reported revenue
    NONPROFIT_HIGH_COMPENSATION = "nonprofit_high_compensation"  # >25% to compensation
    NONPROFIT_LOW_PROGRAM_RATIO = "nonprofit_low_program_ratio"  # <65% to programs
    NONPROFIT_STALE_FILING = "nonprofit_stale_filing"  # >3 years since filing
    NONPROFIT_NO_FILING = "nonprofit_no_filing"  # Has EIN but no 990 found
    # Campaign finance flags
    POLITICAL_DONOR = "political_donor"  # Donated to campaigns and received awards


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
        
        print("  Checking for nonprofit anomalies...")
        self._check_nonprofit_anomalies()

        print("  Checking for funding before formation...")
        self._check_funding_before_formation()

        return self.flags
    
    def _check_duplicate_awards(self):
        """Find potential duplicate awards (same recipient, similar amount, close dates)"""
        
        # More efficient approach: find recipients with multiple awards first,
        # then check for duplicates within each recipient's awards
        
        # Step 1: Find recipients with potential duplicates (same amount, close dates)
        # This uses a smarter query that doesn't do a full self-join
        query = text("""
            WITH recipient_candidates AS (
                -- Find recipients who have multiple awards with similar amounts
                SELECT DISTINCT a1.recipient_id
                FROM awards a1
                WHERE a1.amount > 10000
                  AND a1.award_date IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM awards a2
                    WHERE a2.recipient_id = a1.recipient_id
                      AND a2.id != a1.id
                      AND a2.award_date IS NOT NULL
                      AND ABS(a1.amount - a2.amount) / NULLIF(a1.amount, 0) < 0.01
                      AND a2.award_date BETWEEN a1.award_date - INTERVAL '30 days' AND a1.award_date + INTERVAL '30 days'
                  )
                LIMIT 1000
            )
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
            WHERE a1.recipient_id IN (SELECT recipient_id FROM recipient_candidates)
                AND a1.award_date IS NOT NULL 
                AND a2.award_date IS NOT NULL
                AND a1.amount > 10000
                AND ABS(a1.amount - a2.amount) / NULLIF(a1.amount, 0) < 0.01
                AND a2.award_date BETWEEN a1.award_date - INTERVAL '30 days' AND a1.award_date + INTERVAL '30 days'
            ORDER BY a1.amount DESC
            LIMIT 500
        """)
        
        try:
            results = self.db.execute(query).fetchall()
        except Exception as e:
            print(f"Duplicate query error: {e}")
            # Fallback to simpler query if the optimized one fails
            return self._check_duplicate_awards_simple()
        
        seen_pairs = set()
        
        for row in results:
            pair_key = (min(row.award1_id, row.award2_id), max(row.award1_id, row.award2_id))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            
            amount_diff_pct = abs(row.amount1 - row.amount2) / row.amount1 * 100
            
            # Calculate date diff - handle both date and datetime types
            if row.date1 and row.date2:
                diff = row.date1 - row.date2
                date_diff = abs(diff.days if hasattr(diff, 'days') else int(diff))
            else:
                date_diff = 0
            
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
    
    def _check_duplicate_awards_simple(self):
        """Simpler fallback for duplicate detection - checks top recipients only"""
        # Get top 100 recipients by award count
        top_recipients = self.db.query(
            Award.recipient_id
        ).group_by(Award.recipient_id).having(
            func.count(Award.id) >= 5
        ).order_by(func.sum(Award.amount).desc()).limit(100).all()
        
        recipient_ids = [r.recipient_id for r in top_recipients]
        
        for recipient_id in recipient_ids:
            # Get awards for this recipient
            awards = self.db.query(Award).filter(
                Award.recipient_id == recipient_id,
                Award.amount > 10000,
                Award.award_date.isnot(None)
            ).order_by(Award.amount.desc()).limit(50).all()
            
            # Check pairs within this recipient
            for i, a1 in enumerate(awards):
                for a2 in awards[i+1:]:
                    if a1.amount == 0:
                        continue
                    amount_diff_pct = abs(a1.amount - a2.amount) / a1.amount
                    if amount_diff_pct >= 0.01:
                        continue
                    
                    date_diff = abs((a1.award_date - a2.award_date).days)
                    if date_diff > 30:
                        continue
                    
                    # Found a duplicate
                    if amount_diff_pct == 0 and date_diff == 0:
                        severity = Severity.CRITICAL if a1.amount > 100000 else Severity.HIGH
                        match_type = "exact"
                    elif amount_diff_pct < 0.001 and date_diff <= 7:
                        severity = Severity.HIGH if a1.amount > 50000 else Severity.MEDIUM
                        match_type = "near_exact"
                    else:
                        severity = Severity.MEDIUM if a1.amount > 50000 else Severity.LOW
                        match_type = "similar"
                    
                    self.flags.append(Flag(
                        flag_type=FlagType.DUPLICATE_AWARD,
                        severity=severity,
                        description=f"Potential duplicate: ${a1.amount:,.0f} and ${a2.amount:,.0f} within {date_diff} days",
                        recipient_id=recipient_id,
                        award_id=a1.id,
                        evidence={
                            "match_type": match_type,
                            "award1": {
                                "id": a1.id,
                                "amount": float(a1.amount),
                                "date": str(a1.award_date),
                                "source": a1.source,
                                "description": (a1.description or "")[:200]
                            },
                            "award2": {
                                "id": a2.id,
                                "amount": float(a2.amount),
                                "date": str(a2.award_date),
                                "source": a2.source,
                                "description": (a2.description or "")[:200]
                            },
                            "amount_diff_pct": round(amount_diff_pct * 100, 2),
                            "date_diff_days": date_diff
                        }
                    ))
                    
                    if len(self.flags) >= 500:
                        return
    
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
    
    def _check_nonprofit_anomalies(self):
        """Check nonprofits for 990 red flags"""
        from datetime import datetime, timedelta
        
        # Only check recipients with 990 data loaded
        nonprofits = self.db.query(
            Recipient.id,
            Recipient.name,
            Recipient.ein,
            Recipient.is_nonprofit,
            Recipient.tax_period,
            Recipient.irs_total_revenue,
            Recipient.irs_total_expenses,
            Recipient.irs_program_ratio,
            Recipient.irs_comp_ratio,
            Recipient.irs_total_compensation,
            Recipient.irs_last_updated,
            func.sum(Award.amount).label("total_awards")
        ).outerjoin(
            Award, Award.recipient_id == Recipient.id
        ).filter(
            Recipient.is_nonprofit == True
        ).group_by(Recipient.id).all()
        
        current_year = datetime.now().year
        
        for np in nonprofits:
            # 1. Revenue mismatch: grants received > reported revenue
            if np.irs_total_revenue and np.total_awards:
                if np.total_awards > np.irs_total_revenue * 1.5:  # >150% of revenue
                    severity = Severity.CRITICAL if np.total_awards > np.irs_total_revenue * 3 else Severity.HIGH
                    self.flags.append(Flag(
                        flag_type=FlagType.NONPROFIT_REVENUE_MISMATCH,
                        severity=severity,
                        description=f"Grants (${np.total_awards:,.0f}) exceed 990 revenue (${np.irs_total_revenue:,.0f})",
                        recipient_id=np.id,
                        evidence={
                            "total_grants_received": float(np.total_awards),
                            "irs_reported_revenue": float(np.irs_total_revenue),
                            "ratio": round(np.total_awards / np.irs_total_revenue, 2),
                            "tax_period": np.tax_period
                        }
                    ))
            
            # 2. High compensation ratio (>25% of expenses)
            if np.irs_comp_ratio and np.irs_comp_ratio > 0.25:
                severity = Severity.HIGH if np.irs_comp_ratio > 0.40 else Severity.MEDIUM
                self.flags.append(Flag(
                    flag_type=FlagType.NONPROFIT_HIGH_COMPENSATION,
                    severity=severity,
                    description=f"High compensation: {np.irs_comp_ratio*100:.1f}% of expenses go to compensation",
                    recipient_id=np.id,
                    evidence={
                        "compensation_ratio": float(np.irs_comp_ratio),
                        "total_compensation": float(np.irs_total_compensation) if np.irs_total_compensation else None,
                        "total_expenses": float(np.irs_total_expenses) if np.irs_total_expenses else None,
                        "tax_period": np.tax_period
                    }
                ))
            
            # 3. Low program ratio (<65% to actual programs)
            if np.irs_program_ratio and np.irs_program_ratio < 0.65:
                severity = Severity.HIGH if np.irs_program_ratio < 0.50 else Severity.MEDIUM
                self.flags.append(Flag(
                    flag_type=FlagType.NONPROFIT_LOW_PROGRAM_RATIO,
                    severity=severity,
                    description=f"Low program spending: only {np.irs_program_ratio*100:.1f}% goes to programs",
                    recipient_id=np.id,
                    evidence={
                        "program_ratio": float(np.irs_program_ratio),
                        "total_expenses": float(np.irs_total_expenses) if np.irs_total_expenses else None,
                        "tax_period": np.tax_period
                    }
                ))
            
            # 4. Stale filing (>3 years old)
            if np.tax_period:
                try:
                    filing_year = int(np.tax_period[:4])
                    years_old = current_year - filing_year
                    if years_old >= 3:
                        severity = Severity.HIGH if years_old >= 5 else Severity.MEDIUM
                        self.flags.append(Flag(
                            flag_type=FlagType.NONPROFIT_STALE_FILING,
                            severity=severity,
                            description=f"Stale 990 filing: last filed for {filing_year} ({years_old} years ago)",
                            recipient_id=np.id,
                            evidence={
                                "tax_period": np.tax_period,
                                "filing_year": filing_year,
                                "years_since_filing": years_old
                            }
                        ))
                except (ValueError, TypeError):
                    pass

    def _check_funding_before_formation(self):
        """Find awards dated before the business was legally formed"""

        # Query recipients with formation_date and awards before that date
        query = text("""
            SELECT
                r.id as recipient_id,
                r.name,
                r.formation_date,
                r.business_status,
                a.id as award_id,
                a.source,
                a.amount,
                a.award_date,
                a.description,
                (r.formation_date - a.award_date) as days_before
            FROM recipients r
            JOIN awards a ON a.recipient_id = r.id
            WHERE r.formation_date IS NOT NULL
              AND a.award_date IS NOT NULL
              AND a.award_date < r.formation_date
              AND a.amount > 1000
            ORDER BY (r.formation_date - a.award_date) DESC, a.amount DESC
            LIMIT 500
        """)

        try:
            results = self.db.execute(query).fetchall()
        except Exception as e:
            print(f"Funding before formation query error: {e}")
            return

        # Group by recipient to avoid duplicate flags
        seen_recipients = set()

        for row in results:
            # Skip if we already flagged this recipient
            if row.recipient_id in seen_recipients:
                continue
            seen_recipients.add(row.recipient_id)

            days_before = row.days_before
            if hasattr(days_before, 'days'):
                days_before = days_before.days

            # Determine severity based on gap size
            if days_before > 365:  # More than 1 year before formation
                severity = Severity.CRITICAL
            elif days_before > 180:  # 6 months to 1 year
                severity = Severity.HIGH
            elif days_before > 30:  # 1-6 months
                severity = Severity.MEDIUM
            else:
                severity = Severity.LOW

            self.flags.append(Flag(
                flag_type=FlagType.FUNDING_BEFORE_FORMATION,
                severity=severity,
                description=f"Award received {days_before} days before business formation",
                recipient_id=row.recipient_id,
                award_id=row.award_id,
                evidence={
                    "formation_date": str(row.formation_date),
                    "award_date": str(row.award_date),
                    "days_before_formation": int(days_before),
                    "amount": float(row.amount),
                    "source": row.source,
                    "business_status": row.business_status,
                    "description": (row.description or "")[:200]
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
            
            # Commit each flag individually to let PostgreSQL generate the ID
            try:
                self.db.commit()
                saved += 1
            except Exception as e:
                self.db.rollback()
                print(f"Error saving flag: {e}")
        
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
    valid_flags = []  # Only flags with actual evidence data
    
    for flag in all_flags:
        if flag.evidence:
            try:
                evidence = json.loads(flag.evidence)
                # Only include flags where we have actual award amounts
                award1_amount = evidence.get("award1", {}).get("amount", 0) if evidence.get("award1") else 0
                award2_amount = evidence.get("award2", {}).get("amount", 0) if evidence.get("award2") else 0
                
                if award1_amount > 0 or award2_amount > 0:
                    valid_flags.append(flag)
                    # Add the smaller of the two amounts (potential double-payment)
                    if award1_amount > 0 and award2_amount > 0:
                        total_at_risk += min(award1_amount, award2_amount)
            except:
                pass  # Skip flags with invalid JSON
    
    # Update total to reflect only valid flags
    total = len(valid_flags)
    
    # Get paginated results from valid flags
    # Sort by severity and created_at
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    valid_flags.sort(key=lambda f: (severity_order.get(f.severity, 4), f.created_at or datetime.min), reverse=False)
    
    paginated_flags = valid_flags[offset:offset + limit]
    
    results = []
    for flag in paginated_flags:
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
    
    # Summary by severity (from valid flags only)
    by_severity = {}
    for flag in valid_flags:
        by_severity[flag.severity] = by_severity.get(flag.severity, 0) + 1
    
    return {
        "total": total,
        "total_at_risk": total_at_risk,
        "by_severity": by_severity,
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


@router.delete("/correlation/flags/clear")
async def clear_all_flags(
    flag_type: Optional[str] = Query(None, description="Clear only this flag type"),
    db: Session = Depends(get_db)
):
    """
    Clear all fraud flags (or just a specific type).
    Use this to reset and re-run correlation analysis.
    """
    query = db.query(FraudFlag)
    
    if flag_type:
        query = query.filter(FraudFlag.flag_type == flag_type)
    
    count = query.count()
    query.delete()
    db.commit()
    
    return {
        "success": True,
        "deleted": count,
        "flag_type": flag_type or "all"
    }


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


@router.get("/correlation/funding-before-formation")
async def get_funding_before_formation(
    source: Optional[str] = Query(None, description="Filter by source (usaspending, sba_ppp, ohio_checkbook)"),
    min_days: int = Query(0, ge=0, description="Minimum days before formation"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Get recipients who received awards before their business was legally formed.
    Returns detailed analysis including timeline and amounts.
    """
    # Build base query
    base_query = text("""
        SELECT
            r.id as recipient_id,
            r.name,
            r.city,
            r.formation_date,
            r.business_status,
            r.business_type,
            MIN(a.award_date) as first_award_date,
            MAX(a.award_date) as last_award_before,
            COUNT(a.id) as awards_before_formation,
            SUM(a.amount) as total_before_formation,
            (r.formation_date - MIN(a.award_date)) as max_days_before
        FROM recipients r
        JOIN awards a ON a.recipient_id = r.id
        WHERE r.formation_date IS NOT NULL
          AND a.award_date IS NOT NULL
          AND a.award_date < r.formation_date
          AND a.amount > 0
          {source_filter}
        GROUP BY r.id
        HAVING (r.formation_date - MIN(a.award_date)) >= :min_days
        ORDER BY (r.formation_date - MIN(a.award_date)) DESC, SUM(a.amount) DESC
        LIMIT :limit OFFSET :offset
    """.format(source_filter="AND a.source = :source" if source else ""))

    # Count query
    count_query = text("""
        SELECT COUNT(*) FROM (
            SELECT r.id
            FROM recipients r
            JOIN awards a ON a.recipient_id = r.id
            WHERE r.formation_date IS NOT NULL
              AND a.award_date IS NOT NULL
              AND a.award_date < r.formation_date
              AND a.amount > 0
              {source_filter}
            GROUP BY r.id
            HAVING (r.formation_date - MIN(a.award_date)) >= :min_days
        ) subq
    """.format(source_filter="AND a.source = :source" if source else ""))

    # Summary stats query
    summary_query = text("""
        SELECT
            COUNT(DISTINCT r.id) as total_recipients,
            SUM(a.amount) as total_amount,
            AVG(r.formation_date - a.award_date) as avg_days_before
        FROM recipients r
        JOIN awards a ON a.recipient_id = r.id
        WHERE r.formation_date IS NOT NULL
          AND a.award_date IS NOT NULL
          AND a.award_date < r.formation_date
          AND a.amount > 0
          {source_filter}
    """.format(source_filter="AND a.source = :source" if source else ""))

    # By source breakdown
    by_source_query = text("""
        SELECT
            a.source,
            COUNT(DISTINCT r.id) as recipient_count,
            SUM(a.amount) as total_amount
        FROM recipients r
        JOIN awards a ON a.recipient_id = r.id
        WHERE r.formation_date IS NOT NULL
          AND a.award_date IS NOT NULL
          AND a.award_date < r.formation_date
          AND a.amount > 0
        GROUP BY a.source
        ORDER BY SUM(a.amount) DESC
    """)

    params = {"min_days": min_days, "limit": limit, "offset": offset}
    if source:
        params["source"] = source

    try:
        # Execute queries
        results = db.execute(base_query, params).fetchall()
        total_count = db.execute(count_query, params).scalar() or 0
        summary = db.execute(summary_query, params).fetchone()
        by_source = db.execute(by_source_query).fetchall()

        # Format results
        items = []
        for row in results:
            days_before = row.max_days_before
            if hasattr(days_before, 'days'):
                days_before = days_before.days

            # Determine severity
            if days_before > 365:
                severity = "critical"
            elif days_before > 180:
                severity = "high"
            elif days_before > 30:
                severity = "medium"
            else:
                severity = "low"

            items.append({
                "recipient_id": row.recipient_id,
                "name": row.name,
                "city": row.city,
                "formation_date": str(row.formation_date) if row.formation_date else None,
                "first_award_date": str(row.first_award_date) if row.first_award_date else None,
                "last_award_before": str(row.last_award_before) if row.last_award_before else None,
                "days_before_formation": int(days_before) if days_before else 0,
                "awards_before_formation": row.awards_before_formation,
                "total_before_formation": float(row.total_before_formation or 0),
                "business_status": row.business_status,
                "business_type": row.business_type,
                "severity": severity
            })

        # Format summary
        avg_days = summary.avg_days_before if summary else 0
        if hasattr(avg_days, 'days'):
            avg_days = avg_days.days

        return {
            "summary": {
                "total_recipients": int(summary.total_recipients) if summary and summary.total_recipients else 0,
                "total_amount_at_risk": float(summary.total_amount) if summary and summary.total_amount else 0,
                "avg_days_before_formation": int(avg_days) if avg_days else 0
            },
            "by_source": [
                {
                    "source": s.source,
                    "recipient_count": s.recipient_count,
                    "total_amount": float(s.total_amount or 0)
                }
                for s in by_source
            ],
            "total_count": total_count,
            "items": items,
            "has_more": offset + limit < total_count
        }

    except Exception as e:
        return {
            "error": str(e),
            "summary": {"total_recipients": 0, "total_amount_at_risk": 0, "avg_days_before_formation": 0},
            "by_source": [],
            "total_count": 0,
            "items": [],
            "has_more": False
        }
