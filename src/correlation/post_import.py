"""
Post-Import Correlation Hook

Automatically runs correlation analysis after data imports.
Call this after any data import completes.

Usage:
    from src.correlation.post_import import run_post_import_analysis
    
    # After importing data:
    run_post_import_analysis(db, source="usaspending", new_recipient_ids=[1,2,3])
"""

import logging
from typing import List, Optional
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import func

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_post_import_analysis(
    db: Session,
    source: str,
    new_recipient_ids: Optional[List[int]] = None,
    new_award_ids: Optional[List[int]] = None,
) -> dict:
    """
    Run correlation analysis after a data import.
    
    Args:
        db: Database session
        source: Source of the import (usaspending, ohio_checkbook, etc.)
        new_recipient_ids: IDs of newly created recipients
        new_award_ids: IDs of newly created awards
    
    Returns:
        dict with analysis results
    """
    from api.app.models import Award, Recipient, FraudFlag
    from src.correlation.engine import CorrelationEngine, FlagType, Severity, FraudIndicator
    
    results = {
        "source": source,
        "timestamp": datetime.utcnow().isoformat(),
        "new_recipients": len(new_recipient_ids) if new_recipient_ids else 0,
        "new_awards": len(new_award_ids) if new_award_ids else 0,
        "flags_created": 0,
        "flags_by_type": {},
    }
    
    logger.info(f"Running post-import analysis for {source}")
    logger.info(f"  New recipients: {results['new_recipients']}")
    logger.info(f"  New awards: {results['new_awards']}")
    
    flags = []
    
    # Batch size for SQLite variable limit
    BATCH_SIZE = 500
    
    # 1. Check for duplicate awards in new data
    if new_award_ids:
        logger.info("Checking for duplicate awards...")
        
        # Batch the query to avoid SQLite limits
        new_awards = []
        for i in range(0, len(new_award_ids), BATCH_SIZE):
            batch_ids = new_award_ids[i:i + BATCH_SIZE]
            new_awards.extend(db.query(Award).filter(Award.id.in_(batch_ids)).all())
        
        for award in new_awards:
            # Check if this looks like a duplicate of existing data
            existing = db.query(Award).filter(
                Award.id != award.id,
                Award.recipient_id == award.recipient_id,
                Award.amount == award.amount,
                Award.award_date == award.award_date
            ).first()
            
            if existing:
                recipient = db.query(Recipient).filter(
                    Recipient.id == award.recipient_id
                ).first()
                
                flags.append(FraudIndicator(
                    flag_type=FlagType.DUPLICATE_AWARD,
                    severity=Severity.HIGH,
                    recipient_id=award.recipient_id,
                    award_id=award.id,
                    description=f"Potential duplicate: ${award.amount:,.2f} to {recipient.name if recipient else 'Unknown'} on {award.award_date}",
                    evidence={
                        "new_award_id": award.id,
                        "existing_award_id": existing.id,
                        "amount": award.amount,
                        "date": str(award.award_date),
                        "new_source": award.source,
                        "existing_source": existing.source
                    }
                ))
    
    # 2. Check new recipients for multi-source funding
    if new_recipient_ids:
        logger.info("Checking for multi-source recipients...")
        
        # Batch queries to avoid SQLite "too many SQL variables" error
        multi_source = []
        
        for i in range(0, len(new_recipient_ids), BATCH_SIZE):
            batch_ids = new_recipient_ids[i:i + BATCH_SIZE]
            
            batch_results = db.query(
                Recipient.id,
                Recipient.name,
                func.count(func.distinct(Award.source)).label("source_count")
            ).join(
                Award, Award.recipient_id == Recipient.id
            ).filter(
                Recipient.id.in_(batch_ids)
            ).group_by(
                Recipient.id
            ).having(
                func.count(func.distinct(Award.source)) >= 2
            ).all()
            
            multi_source.extend(batch_results)
        
        for r in multi_source:
            flags.append(FraudIndicator(
                flag_type=FlagType.MULTIPLE_SOURCES,
                severity=Severity.LOW,  # Not fraud, just notable
                recipient_id=r.id,
                award_id=None,
                description=f"{r.name} receives funding from {r.source_count} sources",
                evidence={"source_count": r.source_count}
            ))
    
    # 3. Check for unusually large awards in new data
    if new_award_ids:
        logger.info("Checking for outlier awards...")
        
        # Get average for this source
        avg_amount = db.query(func.avg(Award.amount)).filter(
            Award.source == source
        ).scalar() or 0
        
        if avg_amount > 0:
            threshold = avg_amount * 5  # 5x average
            
            # Batch the outlier query
            outliers = []
            for i in range(0, len(new_award_ids), BATCH_SIZE):
                batch_ids = new_award_ids[i:i + BATCH_SIZE]
                outliers.extend(
                    db.query(Award, Recipient).join(
                        Recipient, Award.recipient_id == Recipient.id
                    ).filter(
                        Award.id.in_(batch_ids),
                        Award.amount > threshold
                    ).all()
                )
            
            for award, recipient in outliers:
                flags.append(FraudIndicator(
                    flag_type=FlagType.UNUSUALLY_LARGE,
                    severity=Severity.MEDIUM,
                    recipient_id=recipient.id,
                    award_id=award.id,
                    description=f"${award.amount:,.2f} is {award.amount/avg_amount:.1f}x average for {source}",
                    evidence={
                        "amount": award.amount,
                        "average": avg_amount,
                        "multiple": award.amount / avg_amount
                    }
                ))
    
    # 4. Save flags to database
    if flags:
        engine = CorrelationEngine(db)
        saved = engine.save_flags_to_db(flags)
        results["flags_created"] = saved
        
        # Count by type
        for flag in flags:
            typ = flag.flag_type.value
            results["flags_by_type"][typ] = results["flags_by_type"].get(typ, 0) + 1
    
    logger.info(f"Post-import analysis complete:")
    logger.info(f"  Flags created: {results['flags_created']}")
    
    return results


def quick_scan_new_data(db: Session, since_hours: int = 24) -> dict:
    """
    Quick scan of data added in the last N hours.
    Useful for scheduled jobs.
    """
    from api.app.models import Award, Recipient
    from datetime import timedelta
    
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    
    # Find recently added recipients
    new_recipient_ids = [r.id for r in db.query(Recipient.id).filter(
        Recipient.created_at >= cutoff
    ).all()]
    
    # Find recently added awards
    new_award_ids = [a.id for a in db.query(Award.id).filter(
        Award.created_at >= cutoff
    ).all()]
    
    if not new_recipient_ids and not new_award_ids:
        return {"message": "No new data to analyze", "since_hours": since_hours}
    
    return run_post_import_analysis(
        db=db,
        source="scheduled_scan",
        new_recipient_ids=new_recipient_ids,
        new_award_ids=new_award_ids,
    )
