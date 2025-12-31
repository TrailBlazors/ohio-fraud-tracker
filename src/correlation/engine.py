"""
Correlation Engine

Cross-references data across multiple sources to:
1. Match recipients/businesses across sources
2. Detect anomalies and potential fraud indicators

Note: Ohio SOS verification via OpenCorporates is disabled pending API access.
      When enabled, add opencorporates_client parameter to CorrelationEngine.
"""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json

from sqlalchemy.orm import Session
from sqlalchemy import func

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FlagType(str, Enum):
    """Types of fraud indicators"""
    # Business existence issues (requires SOS verification - future)
    BUSINESS_NOT_FOUND = "business_not_found"
    BUSINESS_DISSOLVED = "business_dissolved_before_award"
    BUSINESS_NOT_FORMED = "business_not_formed_before_award"
    BUSINESS_INACTIVE = "business_inactive_at_award"
    
    # Address anomalies
    DUPLICATE_ADDRESS = "duplicate_address_multiple_recipients"
    PO_BOX_LARGE_AWARD = "po_box_large_award"
    
    # Award anomalies
    DUPLICATE_AWARD = "duplicate_award"
    UNUSUALLY_LARGE = "unusually_large_award"
    MULTIPLE_SOURCES = "same_recipient_multiple_sources"
    
    # Data quality
    MISSING_DATA = "missing_required_data"
    NAME_VARIATION = "name_variation_detected"


class Severity(str, Enum):
    """Severity levels for flags"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FraudIndicator:
    """A potential fraud indicator"""
    flag_type: FlagType
    severity: Severity
    recipient_id: Optional[int]
    award_id: Optional[int]
    description: str
    evidence: Dict[str, Any]
    
    def to_dict(self) -> Dict:
        return {
            "flag_type": self.flag_type.value,
            "severity": self.severity.value,
            "recipient_id": self.recipient_id,
            "award_id": self.award_id,
            "description": self.description,
            "evidence": self.evidence
        }


class CorrelationEngine:
    """
    Cross-references data sources to detect anomalies and potential fraud.
    
    Current checks (no external API required):
    - Duplicate addresses (multiple recipients at same address)
    - Duplicate awards (same recipient/amount/date)
    - Unusually large awards (statistical outliers)
    - Multi-source recipients (receiving from federal + state)
    
    Future checks (requires OpenCorporates API):
    - Business existence verification
    - Business status at award date
    """
    
    def __init__(self, db: Session):
        self.db = db
        
        # Import models
        from api.app.models import Award, Recipient, Agency, FraudFlag
        self.Award = Award
        self.Recipient = Recipient
        self.Agency = Agency
        self.FraudFlag = FraudFlag
    
    # =========================================================================
    # ADDRESS ANALYSIS
    # =========================================================================
    
    def find_duplicate_addresses(self, min_recipients: int = 3) -> List[FraudIndicator]:
        """Find addresses used by multiple recipients."""
        flags = []
        
        address_counts = self.db.query(
            self.Recipient.address,
            self.Recipient.city,
            func.count(self.Recipient.id).label("count")
        ).filter(
            self.Recipient.address.isnot(None),
            self.Recipient.address != ""
        ).group_by(
            self.Recipient.address,
            self.Recipient.city
        ).having(
            func.count(self.Recipient.id) >= min_recipients
        ).all()
        
        skip_patterns = ["po box", "p.o. box"]
        
        for addr_info in address_counts:
            address = addr_info.address or ""
            if any(p in address.lower() for p in skip_patterns):
                continue
            
            recipients = self.db.query(self.Recipient).filter(
                self.Recipient.address == addr_info.address,
                self.Recipient.city == addr_info.city
            ).all()
            
            total_amount = sum(
                self.db.query(func.sum(self.Award.amount)).filter(
                    self.Award.recipient_id == r.id
                ).scalar() or 0
                for r in recipients
            )
            
            flags.append(FraudIndicator(
                flag_type=FlagType.DUPLICATE_ADDRESS,
                severity=Severity.MEDIUM if addr_info.count < 5 else Severity.HIGH,
                recipient_id=None,
                award_id=None,
                description=f"{addr_info.count} recipients at: {address}, {addr_info.city}",
                evidence={
                    "address": address,
                    "city": addr_info.city,
                    "recipient_count": addr_info.count,
                    "total_amount": float(total_amount),
                    "recipient_names": [r.name for r in recipients[:10]]
                }
            ))
        
        return flags
    
    # =========================================================================
    # AWARD ANALYSIS
    # =========================================================================
    
    def find_duplicate_awards(self) -> List[FraudIndicator]:
        """Find potential duplicate awards."""
        flags = []
        
        duplicates = self.db.query(
            self.Award.recipient_id,
            self.Award.amount,
            self.Award.award_date,
            func.count(self.Award.id).label("count")
        ).group_by(
            self.Award.recipient_id,
            self.Award.amount,
            self.Award.award_date
        ).having(
            func.count(self.Award.id) > 1
        ).all()
        
        for dup in duplicates:
            recipient = self.db.query(self.Recipient).filter(
                self.Recipient.id == dup.recipient_id
            ).first()
            
            awards = self.db.query(self.Award).filter(
                self.Award.recipient_id == dup.recipient_id,
                self.Award.amount == dup.amount,
                self.Award.award_date == dup.award_date
            ).all()
            
            # Check if from different sources (less likely to be true duplicate)
            sources = list(set(a.source for a in awards))
            severity = Severity.MEDIUM if len(sources) > 1 else Severity.HIGH
            
            flags.append(FraudIndicator(
                flag_type=FlagType.DUPLICATE_AWARD,
                severity=severity,
                recipient_id=dup.recipient_id,
                award_id=awards[0].id if awards else None,
                description=f"Duplicate: {dup.count} awards of ${dup.amount:,.2f} to {recipient.name if recipient else 'Unknown'}",
                evidence={
                    "recipient_name": recipient.name if recipient else None,
                    "amount": dup.amount,
                    "date": str(dup.award_date) if dup.award_date else None,
                    "count": dup.count,
                    "award_ids": [a.id for a in awards],
                    "sources": sources
                }
            ))
        
        return flags
    
    def find_unusually_large_awards(self, min_amount: float = 1000000) -> List[FraudIndicator]:
        """Find awards that are statistical outliers."""
        flags = []
        
        stats = self.db.query(
            self.Award.source,
            func.avg(self.Award.amount).label("avg"),
            func.count(self.Award.id).label("count")
        ).group_by(self.Award.source).all()
        
        for source_stat in stats:
            if source_stat.count < 100:
                continue
            
            avg = source_stat.avg or 0
            threshold = max(avg * 3, min_amount)
            
            outliers = self.db.query(self.Award, self.Recipient).join(
                self.Recipient, self.Award.recipient_id == self.Recipient.id
            ).filter(
                self.Award.source == source_stat.source,
                self.Award.amount > threshold
            ).order_by(self.Award.amount.desc()).limit(20).all()
            
            for award, recipient in outliers:
                flags.append(FraudIndicator(
                    flag_type=FlagType.UNUSUALLY_LARGE,
                    severity=Severity.MEDIUM,
                    recipient_id=recipient.id,
                    award_id=award.id,
                    description=f"${award.amount:,.2f} is {award.amount/avg:.1f}x average for {award.source}",
                    evidence={
                        "amount": award.amount,
                        "source": award.source,
                        "average_for_source": avg,
                        "recipient_name": recipient.name
                    }
                ))
        
        return flags
    
    # =========================================================================
    # CROSS-SOURCE ANALYSIS
    # =========================================================================
    
    def find_multi_source_recipients(self, min_sources: int = 2) -> List[Dict]:
        """
        Find recipients receiving funding from multiple sources.
        Useful for cross-referencing federal + state data.
        """
        results = []
        
        multi_source = self.db.query(
            self.Recipient.id,
            self.Recipient.name,
            self.Recipient.city,
            func.count(func.distinct(self.Award.source)).label("source_count"),
            func.sum(self.Award.amount).label("total_amount")
        ).join(
            self.Award, self.Award.recipient_id == self.Recipient.id
        ).group_by(
            self.Recipient.id
        ).having(
            func.count(func.distinct(self.Award.source)) >= min_sources
        ).order_by(
            func.sum(self.Award.amount).desc()
        ).limit(100).all()
        
        for r in multi_source:
            source_breakdown = self.db.query(
                self.Award.source,
                func.sum(self.Award.amount).label("amount"),
                func.count(self.Award.id).label("count")
            ).filter(
                self.Award.recipient_id == r.id
            ).group_by(self.Award.source).all()
            
            results.append({
                "recipient_id": r.id,
                "recipient_name": r.name,
                "city": r.city,
                "source_count": r.source_count,
                "total_amount": float(r.total_amount),
                "by_source": [
                    {"source": s.source, "amount": float(s.amount), "count": s.count}
                    for s in source_breakdown
                ]
            })
        
        return results
    
    # =========================================================================
    # FULL SCAN
    # =========================================================================
    
    def run_full_scan(self) -> List[FraudIndicator]:
        """
        Run all correlation checks that don't require external APIs.
        """
        all_flags = []
        
        logger.info("Starting correlation scan...")
        
        logger.info("Checking duplicate addresses...")
        all_flags.extend(self.find_duplicate_addresses())
        
        logger.info("Checking duplicate awards...")
        all_flags.extend(self.find_duplicate_awards())
        
        logger.info("Checking large awards...")
        all_flags.extend(self.find_unusually_large_awards())
        
        logger.info(f"Scan complete. Total flags: {len(all_flags)}")
        return all_flags
    
    def save_flags_to_db(self, flags: List[FraudIndicator]) -> int:
        """Save fraud indicators to the database."""
        saved = 0
        
        for flag in flags:
            existing = self.db.query(self.FraudFlag).filter(
                self.FraudFlag.flag_type == flag.flag_type.value,
                self.FraudFlag.recipient_id == flag.recipient_id,
                self.FraudFlag.award_id == flag.award_id,
                self.FraudFlag.is_resolved == False
            ).first()
            
            if existing:
                continue
            
            db_flag = self.FraudFlag(
                flag_type=flag.flag_type.value,
                severity=flag.severity.value,
                recipient_id=flag.recipient_id,
                award_id=flag.award_id,
                description=flag.description,
                evidence=json.dumps(flag.evidence)
            )
            self.db.add(db_flag)
            saved += 1
        
        self.db.commit()
        return saved
