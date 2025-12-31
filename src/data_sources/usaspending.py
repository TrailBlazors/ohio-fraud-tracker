"""
USAspending.gov API Client

Provides access to federal spending data including grants, contracts, loans,
and other financial assistance. Supports filtering by state, recipient,
time period, and award type.

API Documentation: https://api.usaspending.gov/
GitHub: https://github.com/fedspendingtransparency/usaspending-api
"""

import os
import time
import logging
from typing import Optional, List, Dict, Any, Generator
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
# CONSTANTS
# =============================================================================

# Award Type Codes - these are used in API filters
GRANT_TYPES = ["02", "03", "04", "05"]  # Block, Formula, Project, Cooperative
LOAN_TYPES = ["07", "08"]  # Direct Loan, Guaranteed Loan (09 is Insurance, not a loan)
CONTRACT_TYPES = ["A", "B", "C", "D"]  # Various contract types
DIRECT_PAYMENT_TYPES = ["06", "10"]  # Unrestricted, Specified use
OTHER_ASSISTANCE_TYPES = ["09", "11"]  # Insurance, Other
ALL_FINANCIAL_ASSISTANCE = GRANT_TYPES + LOAN_TYPES + DIRECT_PAYMENT_TYPES + OTHER_ASSISTANCE_TYPES

# US State and Territory codes
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico", "VI": "Virgin Islands", "GU": "Guam",
    "AS": "American Samoa", "MP": "Northern Mariana Islands"
}

# State FIPS codes (needed for some endpoints)
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "FL": "12", "GA": "13", "HI": "15", "ID": "16",
    "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22",
    "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34",
    "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40",
    "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47",
    "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56", "DC": "11", "PR": "72", "VI": "78", "GU": "66",
    "AS": "60", "MP": "69"
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class USASpendingConfig:
    """Configuration for USAspending API client"""
    base_url: str = "https://api.usaspending.gov/api/v2"
    timeout: int = 60  # Increased timeout
    max_retries: int = 5  # More retries
    rate_limit_per_minute: int = 30  # Slower - was 120
    page_size: int = 100
    retry_delay: float = 5.0  # Delay between retries


@dataclass
class Award:
    """Represents a single award from USAspending"""
    award_id: str
    generated_internal_id: str
    recipient_name: str
    recipient_city: Optional[str]
    recipient_state: Optional[str]
    awarding_agency: str
    awarding_sub_agency: Optional[str]
    award_type: str
    total_obligation: float
    description: str
    start_date: Optional[str]
    end_date: Optional[str]
    cfda_number: Optional[str]
    place_of_performance_city: Optional[str]
    place_of_performance_state: Optional[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any], is_loans: bool = False) -> "Award":
        """Create Award from USAspending API response"""
        
        # Get amount - loans use different field names
        amount = 0.0
        for field in ["Award Amount", "Subsidy Cost", "Face Value of Loan", "Total Loan Value"]:
            if data.get(field):
                try:
                    amount = float(data.get(field, 0) or 0)
                    if amount != 0:
                        break
                except (ValueError, TypeError):
                    continue
        
        # Get date - loans use "Issued Date", grants use "Start Date"
        start_date = data.get("Start Date") or data.get("Issued Date")
        
        return cls(
            award_id=data.get("Award ID", "") or "",
            generated_internal_id=data.get("generated_internal_id", "") or "",
            recipient_name=data.get("Recipient Name", "") or "",
            recipient_city=data.get("recipient_city_name") or data.get("Recipient Location City"),
            recipient_state=data.get("recipient_state_code") or data.get("Recipient Location State"),
            awarding_agency=data.get("Awarding Agency", "") or "",
            awarding_sub_agency=data.get("Awarding Sub Agency"),
            award_type=data.get("Award Type", "") or "",
            total_obligation=amount,
            description=data.get("Description", "") or "",
            start_date=start_date,
            end_date=data.get("End Date"),
            cfda_number=data.get("cfda_number") or data.get("CFDA Number"),
            place_of_performance_city=data.get("Place of Performance City"),
            place_of_performance_state=data.get("Place of Performance State"),
        )


@dataclass 
class SearchResults:
    """Container for search results with metadata"""
    awards: List[Award]
    total_count: int
    page: int
    has_next: bool
    messages: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "awards": [a.to_dict() for a in self.awards],
            "total_count": self.total_count,
            "page": self.page,
            "has_next": self.has_next,
            "messages": self.messages
        }


# =============================================================================
# EXCEPTIONS
# =============================================================================

class USASpendingError(Exception):
    """Base exception for USAspending API errors"""
    pass


class RateLimitError(USASpendingError):
    """Raised when rate limit is exceeded"""
    pass


class APIError(USASpendingError):
    """Raised for API errors"""
    def __init__(self, message: str, status_code: int = None, response_body: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class ValidationError(USASpendingError):
    """Raised for input validation errors"""
    pass


# =============================================================================
# CLIENT
# =============================================================================

class USASpendingClient:
    """
    Client for the USAspending.gov API
    """
    
    def __init__(self, config: Optional[USASpendingConfig] = None):
        self.config = config or USASpendingConfig()
        self._session = self._create_session()
        self._last_request_time = 0.0
        
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic"""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=2,  # Exponential backoff: 2, 4, 8, 16 seconds
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False  # Don't raise, let us handle it
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        
        return session
    
    def _rate_limit(self):
        """Simple rate limiting to avoid API throttling"""
        min_interval = 60.0 / self.config.rate_limit_per_minute
        elapsed = time.time() - self._last_request_time
        
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
            
        self._last_request_time = time.time()
        
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        payload: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make an API request with error handling and retry logic"""
        self._rate_limit()
        
        url = f"{self.config.base_url}/{endpoint.lstrip('/')}"
        
        logger.debug(f"Request: {method} {url}")
        if payload:
            logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
        
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                if method.upper() == "GET":
                    response = self._session.get(
                        url, 
                        params=params, 
                        timeout=self.config.timeout
                    )
                else:
                    response = self._session.post(
                        url, 
                        json=payload, 
                        timeout=self.config.timeout
                    )
                    
                if response.status_code == 429:
                    wait_time = 60  # Wait a minute on rate limit
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                # Log 422 errors with full response for debugging
                if response.status_code == 422:
                    logger.error(f"422 Unprocessable Entity. Response: {response.text}")
                    logger.error(f"Request payload was: {json.dumps(payload, indent=2)}")
                    
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.ConnectionError as e:
                if attempt < max_attempts - 1:
                    wait_time = self.config.retry_delay * (attempt + 1)
                    logger.warning(f"Connection error (attempt {attempt + 1}/{max_attempts}), retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    # Recreate session to get fresh connection
                    self._session = self._create_session()
                    continue
                logger.error(f"Request failed after {max_attempts} attempts: {e}")
                raise APIError(f"Request failed: {str(e)}")
                
            except requests.exceptions.HTTPError as e:
                error_body = e.response.text if e.response else None
                logger.error(f"HTTP error: {e}, Response: {error_body}")
                raise APIError(
                    f"HTTP error: {str(e)}", 
                    status_code=e.response.status_code if e.response else None,
                    response_body=error_body
                )
            except requests.exceptions.RequestException as e:
                if attempt < max_attempts - 1:
                    wait_time = self.config.retry_delay * (attempt + 1)
                    logger.warning(f"Request error (attempt {attempt + 1}/{max_attempts}), retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                logger.error(f"Request failed: {e}")
                raise APIError(f"Request failed: {str(e)}")
        
        raise APIError("Max retries exceeded")
    
    def _validate_state(self, state: str) -> str:
        """Validate and normalize state code"""
        state = state.upper().strip()
        if state not in US_STATES:
            raise ValidationError(
                f"Invalid state code: '{state}'. "
                f"Must be a valid US state/territory code (e.g., 'OH', 'CA', 'TX')."
            )
        return state
    
    def _build_filters(
        self,
        state: Optional[str] = None,
        award_types: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        agencies: Optional[List[str]] = None,
        recipient_name: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        cfda_numbers: Optional[List[str]] = None,
        location_type: str = "recipient"
    ) -> Dict[str, Any]:
        """Build the filters object for search queries"""
        filters = {}
        
        # State filter
        if state:
            state = self._validate_state(state)
            location_filter = {"country": "USA", "state": state}
            
            if location_type == "recipient":
                filters["recipient_locations"] = [location_filter]
            else:
                filters["place_of_performance_locations"] = [location_filter]
        
        # Award type filter
        if award_types:
            filters["award_type_codes"] = award_types
            
        # Time period filter
        if start_date or end_date:
            time_period = {
                "start_date": start_date or "2007-10-01",
                "end_date": end_date or date.today().isoformat()
            }
            filters["time_period"] = [time_period]
            
        # Agency filter
        if agencies:
            filters["agencies"] = [
                {"type": "awarding", "tier": "toptier", "name": agency}
                for agency in agencies
            ]
            
        # Recipient search
        if recipient_name:
            filters["recipient_search_text"] = recipient_name
            
        # Keyword search
        if keywords:
            filters["keywords"] = keywords
            
        # CFDA filter
        if cfda_numbers:
            filters["program_numbers"] = cfda_numbers
            
        return filters
    
    # =========================================================================
    # PUBLIC API METHODS
    # =========================================================================
    
    def get_state_totals(self, state: str, fiscal_year: Optional[int] = None) -> Dict[str, Any]:
        """Get spending totals for a state"""
        state = self._validate_state(state)
        fips = STATE_FIPS.get(state)
        
        endpoint = f"/recipient/state/{fips}/"
        params = {"year": fiscal_year} if fiscal_year else {}
            
        return self._make_request("GET", endpoint, params=params)
    
    def search_awards(
        self,
        state: Optional[str] = None,
        award_types: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        agencies: Optional[List[str]] = None,
        recipient_name: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        cfda_numbers: Optional[List[str]] = None,
        location_type: str = "recipient",
        limit: int = 100,
        page: int = 1,
        sort_field: Optional[str] = None,
        sort_direction: str = "desc"
    ) -> SearchResults:
        """Search for awards with flexible filtering"""
        filters = self._build_filters(
            state=state,
            award_types=award_types,
            start_date=start_date,
            end_date=end_date,
            agencies=agencies,
            recipient_name=recipient_name,
            keywords=keywords,
            cfda_numbers=cfda_numbers,
            location_type=location_type
        )
        
        if not filters:
            raise ValidationError("At least one filter parameter is required")
        
        # Check if this is a loans query (07 = Direct Loan, 08 = Guaranteed Loan)
        is_loans = award_types and all(t in ["07", "08"] for t in award_types)
        
        if is_loans:
            # Loan-specific fields per USAspending API docs
            # https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md
            fields = [
                "Award ID",
                "Recipient Name",
                "Issued Date",
                "Loan Value",
                "Subsidy Cost",
                "Awarding Agency",
                "Awarding Sub Agency",
                "Award Type",
                "recipient_city_name",
                "recipient_state_code",
            ]
            default_sort = "Loan Value"
        else:
            # Grant/other assistance fields
            fields = [
                "Award ID",
                "Recipient Name",
                "Start Date",
                "End Date",
                "Award Amount",
                "Awarding Agency",
                "Awarding Sub Agency",
                "Award Type",
                "Description",
                "cfda_number",
                "recipient_city_name",
                "recipient_state_code",
                "Place of Performance City",
                "Place of Performance State",
            ]
            default_sort = "Award Amount"
        
        payload = {
            "filters": filters,
            "fields": fields,
            "limit": min(limit, 100),
            "page": page,
            "sort": sort_field or default_sort,
            "order": sort_direction
        }
        
        response = self._make_request("POST", "/search/spending_by_award/", payload=payload)
        
        # Parse results
        awards = []
        for record in response.get("results", []):
            try:
                awards.append(Award.from_api_response(record, is_loans=is_loans))
            except Exception as e:
                logger.warning(f"Failed to parse award: {e}")
        
        page_meta = response.get("page_metadata", {})
        
        return SearchResults(
            awards=awards,
            total_count=page_meta.get("total", len(awards)),
            page=page_meta.get("page", page),
            has_next=page_meta.get("hasNext", False),
            messages=response.get("messages", [])
        )
    
    def iter_awards(
        self,
        state: Optional[str] = None,
        award_types: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        agencies: Optional[List[str]] = None,
        recipient_name: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        max_records: Optional[int] = None,
        **kwargs
    ) -> Generator[List[Award], None, None]:
        """Iterate through all awards with automatic pagination"""
        page = 1
        total_retrieved = 0
        
        while True:
            results = self.search_awards(
                state=state,
                award_types=award_types,
                start_date=start_date,
                end_date=end_date,
                agencies=agencies,
                recipient_name=recipient_name,
                keywords=keywords,
                page=page,
                **kwargs
            )
            
            if not results.awards:
                break
                
            total_retrieved += len(results.awards)
            logger.info(
                f"Page {page}: Retrieved {len(results.awards)} awards "
                f"(total: {total_retrieved}/{results.total_count})"
            )
            
            yield results.awards
            
            if max_records and total_retrieved >= max_records:
                logger.info(f"Reached max_records limit: {max_records}")
                break
                
            if not results.has_next:
                logger.info("No more pages available")
                break
                
            page += 1
    
    def get_all_awards(
        self,
        state: str,
        award_types: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_records: int = 10000
    ) -> List[Award]:
        """Convenience method to get all awards as a single list"""
        all_awards = []
        
        for batch in self.iter_awards(
            state=state,
            award_types=award_types,
            start_date=start_date,
            end_date=end_date,
            max_records=max_records
        ):
            all_awards.extend(batch)
            
        return all_awards
    
    def search_recipients(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Autocomplete search for recipients"""
        payload = {"keyword": keyword, "limit": limit}
        response = self._make_request("POST", "/autocomplete/recipient/", payload=payload)
        return response.get("results", [])


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_ohio_grants(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 1000
) -> List[Award]:
    """Quick function to get Ohio grants"""
    client = USASpendingClient()
    return client.get_all_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date=start_date,
        end_date=end_date,
        max_records=max_records
    )


def get_state_grants(
    state: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 1000
) -> List[Award]:
    """Quick function to get grants for any state"""
    client = USASpendingClient()
    return client.get_all_awards(
        state=state,
        award_types=GRANT_TYPES,
        start_date=start_date,
        end_date=end_date,
        max_records=max_records
    )


if __name__ == "__main__":
    print("Testing USAspending API Client...")
    print("=" * 60)
    
    client = USASpendingClient()
    
    print("\nSearching for Ohio grants (2024)...")
    try:
        results = client.search_awards(
            state="OH",
            award_types=GRANT_TYPES,
            start_date="2024-01-01",
            end_date="2024-12-31",
            limit=5
        )
        print(f"Found {results.total_count} total grants")
        print(f"First page has {len(results.awards)} results")
        
        if results.awards:
            print("\nTop 5 grants:")
            for award in results.awards[:5]:
                print(f"- {award.recipient_name}: ${award.total_obligation:,.2f}")
                print(f"  Agency: {award.awarding_agency}")
                print(f"  City: {award.recipient_city}, {award.recipient_state}")
                print()
    except Exception as e:
        print(f"Error: {e}")
    
    print("=" * 60)
    print("Test complete!")
