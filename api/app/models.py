"""
Database models for Ohio Fraud Tracker

Uses SQLAlchemy with SQLite locally, Turso in production.
Schema designed to minimize storage while enabling cross-referencing.
"""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, 
    ForeignKey, Index, Text, Boolean, Enum as SQLEnum
)
from sqlalchemy.orm import relationship, declarative_base
from enum import Enum

Base = declarative_base()


# =============================================================================
# ENUMS
# =============================================================================

class AwardType(str, Enum):
    """Federal award types"""
    BLOCK_GRANT = "block_grant"
    FORMULA_GRANT = "formula_grant"
    PROJECT_GRANT = "project_grant"
    COOPERATIVE_AGREEMENT = "cooperative_agreement"
    DIRECT_LOAN = "direct_loan"
    GUARANTEED_LOAN = "guaranteed_loan"
    INSURANCE = "insurance"
    DIRECT_PAYMENT = "direct_payment"
    CONTRACT = "contract"
    OTHER = "other"


class DataSource(str, Enum):
    """Data source identifiers"""
    USASPENDING = "usaspending"
    SBA_PPP = "sba_ppp"
    SBA_EIDL = "sba_eidl"
    SBIR = "sbir"
    OHIO_CHECKBOOK = "ohio_checkbook"
    OHIO_SOS = "ohio_sos"


class BusinessStatus(str, Enum):
    """Ohio Secretary of State business status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    CANCELLED = "cancelled"
    DISSOLVED = "dissolved"
    UNKNOWN = "unknown"


# =============================================================================
# CORE TABLES
# =============================================================================

class Recipient(Base):
    """
    Normalized recipient/business entity.
    One record per unique business, linked to multiple awards.
    """
    __tablename__ = "recipients"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Identifiers (for matching across sources)
    uei = Column(String(12), unique=True, index=True, nullable=True)  # Unique Entity ID
    duns = Column(String(9), index=True, nullable=True)  # Legacy DUNS
    ein = Column(String(10), index=True, nullable=True)  # Tax ID
    ohio_entity_number = Column(String(20), index=True, nullable=True)  # SOS filing number
    
    # Core info
    name = Column(String(255), nullable=False, index=True)
    name_normalized = Column(String(255), index=True)  # Lowercase, stripped for matching
    
    # Business classification
    naics_code = Column(String(6), nullable=True, index=True)  # e.g., "484121" for trucking
    business_type = Column(String(100), nullable=True)  # e.g., "Corporation", "LLC", "Sole Proprietorship"
    
    # Location
    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True, index=True)
    state = Column(String(2), default="OH")
    zip_code = Column(String(10), nullable=True)
    county = Column(String(50), nullable=True)
    
    # Ohio SOS data
    business_status = Column(String(20), default="unknown")
    formation_date = Column(Date, nullable=True)
    sos_last_updated = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    awards = relationship("Award", back_populates="recipient")
    
    # Indexes for fast lookups
    __table_args__ = (
        Index("ix_recipients_name_city", "name_normalized", "city"),
        Index("ix_recipients_status", "business_status"),
        Index("ix_recipients_naics", "naics_code"),
    )


class NaicsCode(Base):
    """
    NAICS (North American Industry Classification System) lookup table.
    Used to provide human-readable industry descriptions.
    """
    __tablename__ = "naics_codes"
    
    code = Column(String(6), primary_key=True)  # e.g., "484121"
    title = Column(String(255), nullable=False)  # e.g., "General Freight Trucking, Long-Distance, Truckload"
    sector = Column(String(2), nullable=True)  # First 2 digits, e.g., "48" for Transportation
    sector_title = Column(String(255), nullable=True)  # e.g., "Transportation and Warehousing"
    
    __table_args__ = (
        Index("ix_naics_sector", "sector"),
    )


class Agency(Base):
    """
    Federal awarding agencies (normalized to reduce duplication)
    """
    __tablename__ = "agencies"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), unique=True, nullable=False)  # e.g., "HHS", "DOT"
    name = Column(String(255), nullable=False)
    
    # Relationships
    sub_agencies = relationship("SubAgency", back_populates="agency")
    awards = relationship("Award", back_populates="agency")


class SubAgency(Base):
    """
    Sub-agencies under main federal agencies
    """
    __tablename__ = "sub_agencies"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agency_id = Column(Integer, ForeignKey("agencies.id"), nullable=False)
    code = Column(String(20), nullable=True)
    name = Column(String(255), nullable=False)
    
    # Relationships
    agency = relationship("Agency", back_populates="sub_agencies")
    awards = relationship("Award", back_populates="sub_agency")
    
    __table_args__ = (
        Index("ix_sub_agencies_agency", "agency_id"),
    )


class Award(Base):
    """
    Individual grant, loan, or contract award.
    This is the main table - kept lean for storage efficiency.
    """
    __tablename__ = "awards"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Source tracking
    source = Column(String(20), nullable=False, index=True)  # usaspending, sba_ppp, etc.
    source_award_id = Column(String(100), nullable=False)  # Original ID from source
    
    # Foreign keys
    recipient_id = Column(Integer, ForeignKey("recipients.id"), nullable=False, index=True)
    agency_id = Column(Integer, ForeignKey("agencies.id"), nullable=True, index=True)
    sub_agency_id = Column(Integer, ForeignKey("sub_agencies.id"), nullable=True)
    
    # Award details
    award_type = Column(String(30), nullable=False, index=True)
    amount = Column(Float, nullable=False, index=True)  # Total obligation/loan amount
    
    # Dates
    award_date = Column(Date, nullable=True, index=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    
    # Description (truncated to save space)
    description = Column(String(500), nullable=True)
    
    # Program info
    cfda_number = Column(String(10), nullable=True, index=True)  # e.g., "93.859"
    cfda_title = Column(String(255), nullable=True)
    
    # Location (place of performance, may differ from recipient)
    pop_city = Column(String(100), nullable=True)
    pop_state = Column(String(2), nullable=True)
    pop_zip = Column(String(10), nullable=True)
    
    # Metadata
    last_modified = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    recipient = relationship("Recipient", back_populates="awards")
    agency = relationship("Agency", back_populates="awards")
    sub_agency = relationship("SubAgency", back_populates="awards")
    
    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_awards_source_id", "source", "source_award_id", unique=True),
        Index("ix_awards_date_amount", "award_date", "amount"),
        Index("ix_awards_type_date", "award_type", "award_date"),
        Index("ix_awards_recipient_date", "recipient_id", "award_date"),
    )


# =============================================================================
# SUPPLEMENTARY TABLES
# =============================================================================

class PPPLoan(Base):
    """
    SBA PPP-specific fields (linked to main Award)
    Only stores PPP-specific data not in base Award table.
    """
    __tablename__ = "ppp_loans"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    award_id = Column(Integer, ForeignKey("awards.id"), unique=True, nullable=False)
    
    # PPP-specific fields
    jobs_retained = Column(Integer, nullable=True)
    loan_status = Column(String(50), nullable=True)  # Active, Paid in Full, etc.
    forgiveness_amount = Column(Float, nullable=True)
    forgiveness_date = Column(Date, nullable=True)
    lender_name = Column(String(255), nullable=True)
    naics_code = Column(String(6), nullable=True)
    business_type = Column(String(100), nullable=True)  # LLC, Corp, Sole Prop, etc.
    
    # Relationship
    award = relationship("Award")


class FraudFlag(Base):
    """
    Flags for potential issues found during cross-referencing.
    """
    __tablename__ = "fraud_flags"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # What's flagged
    recipient_id = Column(Integer, ForeignKey("recipients.id"), nullable=True, index=True)
    award_id = Column(Integer, ForeignKey("awards.id"), nullable=True, index=True)
    
    # Flag details
    flag_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), default="medium")  # low, medium, high
    description = Column(Text, nullable=False)
    
    # Evidence
    evidence = Column(Text, nullable=True)  # JSON string with supporting data
    
    # Status
    is_resolved = Column(Boolean, default=False)
    reviewed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    recipient = relationship("Recipient")
    award = relationship("Award")
    
    __table_args__ = (
        Index("ix_fraud_flags_type_severity", "flag_type", "severity"),
    )


class DataImport(Base):
    """
    Track data import jobs for incremental updates.
    """
    __tablename__ = "data_imports"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(20), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running")  # running, completed, failed
    records_processed = Column(Integer, default=0)
    records_created = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    
    __table_args__ = (
        Index("ix_data_imports_source_status", "source", "status"),
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_name(name: str) -> str:
    """Normalize business name for matching"""
    if not name:
        return ""
    # Lowercase, remove common suffixes, strip whitespace
    normalized = name.lower().strip()
    for suffix in [" llc", " inc", " corp", " ltd", " co", " company", " incorporated"]:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    return normalized.strip()


def map_award_type_code(code: str) -> str:
    """Map USAspending award type codes to our enum"""
    mapping = {
        "02": "block_grant",
        "03": "formula_grant", 
        "04": "project_grant",
        "05": "cooperative_agreement",
        "06": "direct_payment",
        "07": "direct_loan",
        "08": "guaranteed_loan",
        "09": "insurance",
        "10": "direct_payment",
        "11": "other",
        "A": "contract",
        "B": "contract",
        "C": "contract",
        "D": "contract",
    }
    return mapping.get(code, "other")
