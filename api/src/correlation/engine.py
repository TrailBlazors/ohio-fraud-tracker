"""
Correlation Engine for Fraud Detection

Scans awards and recipients for potential fraud indicators.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import Award, Recipient, FraudFlag


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
        """Find potential duplicate awards (same recipient, amount, date)"""
        
        # Find duplicates
        duplicates = self.db.query(
            Award.recipient_id,
            Award.amount,
            Award.award_date,
            func.count(Award.id).label("count")
        ).filter(
            Award.award_date.isnot(None)
        ).group_by(
            Award.recipient_id,
            Award.amount,
            Award.award_date
        ).having(
            func.count(Award.id) > 1
        ).all()
        
        for dup in duplicates:
            # Get the actual award IDs
            awards = self.db.query(Award.id, Award.source).filter(
                Award.recipient_id == dup.recipient_id,
                Award.amount == dup.amount,
                Award.award_date == dup.award_date
            ).all()
            
            # Skip if all from same source (might be legitimate updates)
            sources = set(a.source for a in awards)
            if len(sources) == 1:
                continue
            
            self.flags.append(Flag(
                flag_type=FlagType.DUPLICATE_AWARD,
                severity=Severity.HIGH if dup.amount > 100000 else Severity.MEDIUM,
                description=f"Potential duplicate: {dup.count} awards of ${dup.amount:,.0f} on {dup.award_date}",
                recipient_id=dup.recipient_id,
                evidence={
                    "amount": dup.amount,
                    "date": str(dup.award_date),
                    "count": dup.count,
                    "award_ids": [a.id for a in awards],
                    "sources": list(sources)
                }
            ))
    
    def _check_outlier_amounts(self):
        """Find awards that are significantly above average for their type"""
        
        # Get average by award type
        averages = self.db.query(
            Award.award_type,
            func.avg(Award.amount).label("avg"),
            func.stddev(Award.amount).label("stddev")
        ).group_by(Award.award_type).all()
        
        for avg_row in averages:
            if not avg_row.avg or not avg_row.stddev:
                continue
            
            # Find awards > 5 standard deviations above mean
            threshold = avg_row.avg + (5 * avg_row.stddev)
            
            outliers = self.db.query(Award).filter(
                Award.award_type == avg_row.award_type,
                Award.amount > threshold,
                Award.amount > 1000000  # Only flag if > $1M
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
        
        # Find addresses with 3+ recipients
        address_counts = self.db.query(
            Recipient.address,
            Recipient.city,
            func.count(Recipient.id).label("recipient_count")
        ).filter(
            Recipient.address.isnot(None),
            Recipient.address != "",
            func.length(Recipient.address) > 5  # Filter out short/invalid addresses
        ).group_by(
            Recipient.address,
            Recipient.city
        ).having(
            func.count(Recipient.id) >= 3
        ).all()
        
        for addr in address_counts:
            # Get total funding at this address
            total = self.db.query(func.sum(Award.amount)).join(
                Recipient, Award.recipient_id == Recipient.id
            ).filter(
                Recipient.address == addr.address,
                Recipient.city == addr.city
            ).scalar() or 0
            
            if total < 100000:  # Skip if small amounts
                continue
            
            # Get recipient IDs at this address
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
        
        # Find inactive businesses with awards
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
            func.sum(Award.amount) > 10000  # Only flag if > $10k
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
        
        # Find recipients with many awards
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
            func.count(Award.id) >= 50  # 50+ awards
        ).order_by(
            func.count(Award.id).desc()
        ).limit(50).all()
        
        for r in high_volume:
            self.flags.append(Flag(
                flag_type=FlagType.HIGH_VOLUME_RECIPIENT,
                severity=Severity.LOW,  # Often legitimate (universities, hospitals)
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
            # Check for existing similar flag
            existing = self.db.query(FraudFlag).filter(
                FraudFlag.flag_type == flag.flag_type.value,
                FraudFlag.recipient_id == flag.recipient_id,
                FraudFlag.is_resolved == False
            ).first()
            
            if existing:
                continue  # Skip duplicate
            
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
