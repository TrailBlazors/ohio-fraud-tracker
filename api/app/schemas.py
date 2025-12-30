"""
Pydantic schemas for API request/response validation.
"""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# RECIPIENT SCHEMAS
# =============================================================================

class RecipientBase(BaseModel):
    name: str
    city: Optional[str] = None
    state: str = "OH"
    zip_code: Optional[str] = None


class RecipientSummary(RecipientBase):
    """Minimal recipient info for lists"""
    id: int
    business_status: str = "unknown"
    total_awards: int = 0
    total_amount: float = 0
    
    class Config:
        from_attributes = True


class RecipientDetail(RecipientBase):
    """Full recipient info"""
    id: int
    uei: Optional[str] = None
    ein: Optional[str] = None
    ohio_entity_number: Optional[str] = None
    address: Optional[str] = None
    county: Optional[str] = None
    business_status: str = "unknown"
    formation_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# =============================================================================
# AGENCY SCHEMAS
# =============================================================================

class AgencyBase(BaseModel):
    code: str
    name: str


class AgencySummary(AgencyBase):
    """Agency with award counts"""
    id: int
    total_awards: int = 0
    total_amount: float = 0
    
    class Config:
        from_attributes = True


# =============================================================================
# AWARD SCHEMAS
# =============================================================================

class AwardBase(BaseModel):
    source: str
    award_type: str
    amount: float
    description: Optional[str] = None


class AwardListItem(AwardBase):
    """Award info for table listings"""
    id: int
    recipient_name: str
    recipient_city: Optional[str] = None
    agency_code: Optional[str] = None
    agency_name: Optional[str] = None
    award_date: Optional[date] = None
    cfda_number: Optional[str] = None
    
    class Config:
        from_attributes = True


class AwardDetail(AwardBase):
    """Full award details"""
    id: int
    source_award_id: str
    recipient_id: int
    recipient_name: str
    recipient_city: Optional[str] = None
    recipient_state: str = "OH"
    agency_id: Optional[int] = None
    agency_code: Optional[str] = None
    agency_name: Optional[str] = None
    sub_agency_name: Optional[str] = None
    award_date: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    cfda_number: Optional[str] = None
    cfda_title: Optional[str] = None
    pop_city: Optional[str] = None
    pop_state: Optional[str] = None
    pop_zip: Optional[str] = None
    last_modified: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# =============================================================================
# PPP LOAN SCHEMAS
# =============================================================================

class PPPLoanDetail(BaseModel):
    """PPP-specific loan details"""
    award_id: int
    jobs_retained: Optional[int] = None
    loan_status: Optional[str] = None
    forgiveness_amount: Optional[float] = None
    forgiveness_date: Optional[date] = None
    lender_name: Optional[str] = None
    naics_code: Optional[str] = None
    business_type: Optional[str] = None
    
    class Config:
        from_attributes = True


# =============================================================================
# SEARCH & FILTER SCHEMAS
# =============================================================================

class AwardSearchParams(BaseModel):
    """Query parameters for award search"""
    q: Optional[str] = Field(None, description="Search term (recipient name, keyword)")
    recipient_id: Optional[int] = None
    agency_code: Optional[str] = None
    award_type: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    city: Optional[str] = None
    cfda_number: Optional[str] = None
    source: Optional[str] = None
    
    # Pagination
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)
    
    # Sorting
    sort_by: str = Field("amount", description="Field to sort by")
    sort_order: str = Field("desc", pattern="^(asc|desc)$")


class RecipientSearchParams(BaseModel):
    """Query parameters for recipient search"""
    q: Optional[str] = Field(None, description="Search term (name)")
    city: Optional[str] = None
    business_status: Optional[str] = None
    has_awards: Optional[bool] = None
    
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)
    sort_by: str = Field("name", description="Field to sort by")
    sort_order: str = Field("asc", pattern="^(asc|desc)$")


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class PaginatedResponse(BaseModel):
    """Base paginated response"""
    page: int
    page_size: int
    total_count: int
    total_pages: int
    has_next: bool
    has_prev: bool


class AwardListResponse(PaginatedResponse):
    """Paginated list of awards"""
    items: List[AwardListItem]


class RecipientListResponse(PaginatedResponse):
    """Paginated list of recipients"""
    items: List[RecipientSummary]


# =============================================================================
# STATS SCHEMAS
# =============================================================================

class DashboardStats(BaseModel):
    """Homepage statistics"""
    total_awards: int
    total_amount: float
    total_recipients: int
    total_flagged: int
    awards_by_type: dict
    awards_by_source: dict
    top_agencies: List[AgencySummary]
    recent_awards: List[AwardListItem]


class AgencyStats(BaseModel):
    """Stats for a single agency"""
    agency: AgencySummary
    awards_by_type: dict
    awards_by_year: dict
    top_recipients: List[RecipientSummary]


# =============================================================================
# FRAUD FLAG SCHEMAS
# =============================================================================

class FraudFlagBase(BaseModel):
    flag_type: str
    severity: str = "medium"
    description: str


class FraudFlagDetail(FraudFlagBase):
    id: int
    recipient_id: Optional[int] = None
    award_id: Optional[int] = None
    evidence: Optional[str] = None
    is_resolved: bool = False
    reviewed_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class FraudFlagListResponse(PaginatedResponse):
    """Paginated list of fraud flags"""
    items: List[FraudFlagDetail]


# =============================================================================
# IMPORT STATUS SCHEMAS
# =============================================================================

class ImportStatus(BaseModel):
    """Data import job status"""
    id: int
    source: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    records_processed: int
    records_created: int
    records_updated: int
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True


# =============================================================================
# HEALTH CHECK
# =============================================================================

class HealthCheck(BaseModel):
    """API health status"""
    status: str = "healthy"
    database: str
    version: str = "0.1.0"
