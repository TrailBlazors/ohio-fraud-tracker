"""
OpenCorporates API Client

Provides access to business registry data from Ohio Secretary of State
via the OpenCorporates aggregated database.

API Documentation: https://api.opencorporates.com/documentation/API-Reference
Apply for free access: https://opencorporates.com/api_accounts/new

For public benefit projects (fraud detection qualifies), API access is free.
"""

import os
import time
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime, date
import json

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class OpenCorporatesConfig:
    """Configuration for OpenCorporates API client"""
    base_url: str = "https://api.opencorporates.com/v0.4"
    api_token: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    rate_limit_per_minute: int = 50  # Free tier limit
    
    def __post_init__(self):
        if not self.api_token:
            self.api_token = os.getenv("OPENCORPORATES_API_TOKEN")


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CompanyOfficer:
    """Represents a company officer/director"""
    name: str
    position: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    
    @classmethod
    def from_api(cls, data: Dict) -> "CompanyOfficer":
        officer = data.get("officer", {})
        return cls(
            name=officer.get("name", ""),
            position=officer.get("position", ""),
            start_date=officer.get("start_date"),
            end_date=officer.get("end_date")
        )


@dataclass
class CompanyFiling:
    """Represents a company filing"""
    title: str
    filing_date: Optional[str]
    filing_type: Optional[str]
    
    @classmethod
    def from_api(cls, data: Dict) -> "CompanyFiling":
        filing = data.get("filing", {})
        return cls(
            title=filing.get("title", ""),
            filing_date=filing.get("date"),
            filing_type=filing.get("filing_type")
        )


@dataclass 
class Company:
    """Represents a company from OpenCorporates"""
    company_number: str  # Ohio entity number
    name: str
    jurisdiction_code: str
    incorporation_date: Optional[str]
    dissolution_date: Optional[str]
    company_type: Optional[str]
    current_status: Optional[str]
    registered_address: Optional[str]
    registered_agent: Optional[str]
    opencorporates_url: str
    source_url: Optional[str]
    officers: List[CompanyOfficer] = None
    filings: List[CompanyFiling] = None
    
    def __post_init__(self):
        if self.officers is None:
            self.officers = []
        if self.filings is None:
            self.filings = []
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['officers'] = [asdict(o) for o in self.officers]
        result['filings'] = [asdict(f) for f in self.filings]
        return result
    
    @classmethod
    def from_api(cls, data: Dict) -> "Company":
        """Create Company from OpenCorporates API response"""
        company = data.get("company", data)
        
        # Parse registered address
        address = company.get("registered_address_in_full") or ""
        if not address and company.get("registered_address"):
            addr = company.get("registered_address", {})
            parts = [
                addr.get("street_address", ""),
                addr.get("locality", ""),
                addr.get("region", ""),
                addr.get("postal_code", "")
            ]
            address = ", ".join(p for p in parts if p)
        
        return cls(
            company_number=company.get("company_number", ""),
            name=company.get("name", ""),
            jurisdiction_code=company.get("jurisdiction_code", ""),
            incorporation_date=company.get("incorporation_date"),
            dissolution_date=company.get("dissolution_date"),
            company_type=company.get("company_type"),
            current_status=company.get("current_status"),
            registered_address=address,
            registered_agent=company.get("agent_name"),
            opencorporates_url=company.get("opencorporates_url", ""),
            source_url=company.get("registry_url"),
            officers=[],
            filings=[]
        )
    
    def is_active(self) -> bool:
        """Check if company is currently active"""
        if not self.current_status:
            return True  # Assume active if unknown
        status_lower = self.current_status.lower()
        inactive_statuses = ['inactive', 'dissolved', 'cancelled', 'canceled', 
                           'dead', 'revoked', 'terminated', 'expired']
        return not any(s in status_lower for s in inactive_statuses)
    
    def was_active_on(self, check_date: date) -> bool:
        """Check if company was active on a specific date"""
        # Parse incorporation date
        inc_date = None
        if self.incorporation_date:
            try:
                inc_date = datetime.strptime(self.incorporation_date, "%Y-%m-%d").date()
            except ValueError:
                pass
        
        # Company didn't exist yet
        if inc_date and check_date < inc_date:
            return False
        
        # Parse dissolution date
        diss_date = None
        if self.dissolution_date:
            try:
                diss_date = datetime.strptime(self.dissolution_date, "%Y-%m-%d").date()
            except ValueError:
                pass
        
        # Company was already dissolved
        if diss_date and check_date > diss_date:
            return False
        
        return True


@dataclass
class SearchResults:
    """Container for search results"""
    companies: List[Company]
    total_count: int
    page: int
    per_page: int
    total_pages: int


# =============================================================================
# EXCEPTIONS
# =============================================================================

class OpenCorporatesError(Exception):
    """Base exception"""
    pass

class RateLimitError(OpenCorporatesError):
    """Rate limit exceeded"""
    pass

class APIError(OpenCorporatesError):
    """API error"""
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


# =============================================================================
# CLIENT
# =============================================================================

class OpenCorporatesClient:
    """
    Client for the OpenCorporates API
    
    Usage:
        client = OpenCorporatesClient()
        
        # Search for Ohio companies
        results = client.search_companies("ACME Corp", jurisdiction="us_oh")
        
        # Get specific company
        company = client.get_company("us_oh", "1234567")
        
        # Check if company was active when it received funding
        was_active = company.was_active_on(date(2020, 4, 15))
    """
    
    OHIO_JURISDICTION = "us_oh"
    
    def __init__(self, config: Optional[OpenCorporatesConfig] = None):
        self.config = config or OpenCorporatesConfig()
        self._session = self._create_session()
        self._last_request_time = 0.0
        
    def _create_session(self) -> requests.Session:
        session = requests.Session()
        
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _rate_limit(self):
        """Simple rate limiting"""
        min_interval = 60.0 / self.config.rate_limit_per_minute
        elapsed = time.time() - self._last_request_time
        
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
            
        self._last_request_time = time.time()
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make API request"""
        self._rate_limit()
        
        url = f"{self.config.base_url}/{endpoint.lstrip('/')}"
        
        if params is None:
            params = {}
        
        if self.config.api_token:
            params["api_token"] = self.config.api_token
        
        logger.debug(f"Request: GET {url}")
        
        try:
            response = self._session.get(url, params=params, timeout=self.config.timeout)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            
            if response.status_code == 401:
                raise APIError("Invalid API token", 401)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise APIError(f"Request failed: {e}")
    
    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================
    
    def search_companies(
        self,
        query: str,
        jurisdiction: str = OHIO_JURISDICTION,
        current_status: Optional[str] = None,
        company_type: Optional[str] = None,
        page: int = 1,
        per_page: int = 30
    ) -> SearchResults:
        """
        Search for companies by name
        """
        params = {
            "q": query,
            "jurisdiction_code": jurisdiction,
            "page": page,
            "per_page": min(per_page, 100)
        }
        
        if current_status:
            params["current_status"] = current_status
        if company_type:
            params["company_type"] = company_type
        
        data = self._make_request("/companies/search", params)
        
        results = data.get("results", {})
        companies = [
            Company.from_api(c) 
            for c in results.get("companies", [])
        ]
        
        return SearchResults(
            companies=companies,
            total_count=results.get("total_count", 0),
            page=results.get("page", 1),
            per_page=results.get("per_page", 30),
            total_pages=results.get("total_pages", 0)
        )
    
    def get_company(
        self, 
        jurisdiction: str, 
        company_number: str,
        include_officers: bool = False,
        include_filings: bool = False
    ) -> Optional[Company]:
        """Get detailed company information"""
        try:
            data = self._make_request(f"/companies/{jurisdiction}/{company_number}")
            company = Company.from_api(data.get("results", {}))
            
            if include_officers:
                company.officers = self.get_company_officers(jurisdiction, company_number)
            
            if include_filings:
                company.filings = self.get_company_filings(jurisdiction, company_number)
            
            return company
            
        except APIError as e:
            if e.status_code == 404:
                return None
            raise
    
    def get_company_officers(
        self, 
        jurisdiction: str, 
        company_number: str
    ) -> List[CompanyOfficer]:
        """Get officers for a company"""
        try:
            data = self._make_request(
                f"/companies/{jurisdiction}/{company_number}/officers"
            )
            results = data.get("results", {})
            return [
                CompanyOfficer.from_api(o) 
                for o in results.get("officers", [])
            ]
        except APIError:
            return []
    
    def get_company_filings(
        self, 
        jurisdiction: str, 
        company_number: str
    ) -> List[CompanyFiling]:
        """Get filings for a company"""
        try:
            data = self._make_request(
                f"/companies/{jurisdiction}/{company_number}/filings"
            )
            results = data.get("results", {})
            return [
                CompanyFiling.from_api(f) 
                for f in results.get("filings", [])
            ]
        except APIError:
            return []
    
    def lookup_ohio_company(self, name: str) -> Optional[Company]:
        """Convenience method to find an Ohio company by name."""
        results = self.search_companies(name, jurisdiction=self.OHIO_JURISDICTION)
        
        if not results.companies:
            return None
        
        # Try to find exact match first
        name_lower = name.lower().strip()
        for company in results.companies:
            if company.name.lower().strip() == name_lower:
                return company
        
        # Return first result as best match
        return results.companies[0]
    
    def verify_company_existed(
        self, 
        name: str, 
        check_date: date,
        city: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Verify a company existed and was active on a specific date.
        
        Returns dict with verification results useful for fraud detection.
        """
        results = self.search_companies(name, jurisdiction=self.OHIO_JURISDICTION)
        
        if not results.companies:
            return {
                "found": False,
                "company": None,
                "was_active": False,
                "status": "Company not found in Ohio SOS records"
            }
        
        # Find best match
        best_match = None
        name_lower = name.lower().strip()
        
        for company in results.companies:
            if company.name.lower().strip() == name_lower:
                best_match = company
                break
            if city and company.registered_address:
                if city.lower() in company.registered_address.lower():
                    best_match = company
                    break
        
        if not best_match:
            best_match = results.companies[0]
        
        was_active = best_match.was_active_on(check_date)
        
        if was_active:
            status = f"Company was active on {check_date}"
        else:
            if best_match.dissolution_date:
                status = f"Company dissolved on {best_match.dissolution_date}"
            elif best_match.incorporation_date:
                status = f"Company not formed until {best_match.incorporation_date}"
            else:
                status = f"Company status: {best_match.current_status}"
        
        return {
            "found": True,
            "company": best_match,
            "was_active": was_active,
            "status": status
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def lookup_ohio_business(name: str, api_token: Optional[str] = None) -> Optional[Company]:
    """Quick lookup of an Ohio business by name"""
    config = OpenCorporatesConfig(api_token=api_token)
    client = OpenCorporatesClient(config)
    return client.lookup_ohio_company(name)


def verify_business_for_award(
    business_name: str,
    award_date: date,
    city: Optional[str] = None,
    api_token: Optional[str] = None
) -> Dict[str, Any]:
    """Verify a business was active when it received an award."""
    config = OpenCorporatesConfig(api_token=api_token)
    client = OpenCorporatesClient(config)
    return client.verify_company_existed(business_name, award_date, city)


if __name__ == "__main__":
    print("Testing OpenCorporates Client...")
    client = OpenCorporatesClient()
    
    print("\nSearching for 'Kroger' in Ohio...")
    try:
        results = client.search_companies("Kroger", jurisdiction="us_oh")
        print(f"Found {results.total_count} results")
        
        if results.companies:
            company = results.companies[0]
            print(f"  Name: {company.name}")
            print(f"  Status: {company.current_status}")
    except APIError as e:
        print(f"API Error: {e}")
        print("Get a free API token at https://opencorporates.com/api_accounts/new")
