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
from enum import Enum
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
LOAN_TYPES = ["07", "08", "09"]  # Direct, Guaranteed, Insurance
CONTRACT_TYPES = ["A", "B", "C", "D"]  # Various contract types
DIRECT_PAYMENT_TYPES = ["06", "10"]  # Unrestricted, Specified use
ALL_FINANCIAL_ASSISTANCE = GRANT_TYPES + LOAN_TYPES + DIRECT_PAYMENT_TYPES + ["11"]

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
    timeout: int = 30
    max_retries: int = 3
    rate_limit_per_minute: int = 120
    page_size: int = 100


@dataclass
class Award:
    """Represents a single award from USAspending"""
    award_id: str
    generated_unique_award_id: str
    recipient_name: str
    recipient_uei: Optional[str]
    recipient_duns: Optional[str]
    recipient_address: Optional[str]
    recipient_city: Optional[str]
    recipient_state: str
    recipient_zip: Optional[str]
    recipient_country: str
    awarding_agency: str
    awarding_sub_agency: Optional[str]
    award_type: str
    total_obligation: float
    total_outlays: Optional[float]
    description: str
    start_date: Optional[str]
    end_date: Optional[str]
    last_modified_date: Optional[str]
    cfda_number: Optional[str]
    place_of_performance_city: Optional[str]
    place_of_performance_state: Optional[str]
    place_of_performance_zip: Optional[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "Award":
        """Create Award from USAspending API response"""
        return cls(
            award_id=data.get("Award ID", "") or "",
            generated_unique_award_id=data.get("generated_unique_award_id", "") or "",
            recipient_name=data.get("Recipient Name", "") or "",
            recipient_uei=data.get("recipient_uei"),
            recipient_duns=data.get("Recipient DUNS Number"),
            recipient_address=data.get("recipient_address_line_1"),
            recipient_city=data.get("recipient_city_name"),
            recipient_state=data.get("recipient_state_code", "") or "",
            recipient_zip=data.get("recipient_zip_4_code"),
            recipient_country=data.get("recipient_country_code", "USA") or "USA",
            awarding_agency=data.get("Awarding Agency", "") or "",
            awarding_sub_agency=data.get("Awarding Sub Agency"),
            award_type=data.get("Award Type", "") or "",
            total_obligation=float(data.get("Award Amount", 0) or 0),
            total_outlays=float(data.get("Total Outlays", 0) or 0) if data.get("Total Outlays") else None,
            description=data.get("Description", "") or "",
            start_date=data.get("Start Date"),
            end_date=data.get("End Date"),
            last_modified_date=data.get("Last Modified Date"),
            cfda_number=data.get("cfda_number"),
            place_of_performance_city=data.get("pop_city_name"),
            place_of_performance_state=data.get("pop_state_code"),
            place_of_performance_zip=data.get("pop_zip_4_code"),
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
    
    Example usage:
        client = USASpendingClient()
        
        # Get all grants to Ohio
        results = client.search_awards(state="OH", award_types=GRANT_TYPES)
        
        # Iterate through large result sets
        for batch in client.iter_awards(state="OH", award_types=GRANT_TYPES):
            for award in batch:
                print(f"{award.recipient_name}: ${award.total_obligation:,.2f}")
                
        # Search by recipient name
        results = client.search_awards(
            recipient_name="Acme Corp",
            state="OH",
            start_date="2020-01-01",
            end_date="2024-12-31"
        )
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
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
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
        """Make an API request with error handling"""
        self._rate_limit()
        
        url = f"{self.config.base_url}/{endpoint.lstrip('/')}"
        
        logger.debug(f"Request: {method} {url}")
        if payload:
            logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
        
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
                raise RateLimitError("API rate limit exceeded. Please wait before retrying.")
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            error_body = e.response.text if e.response else None
            logger.error(f"HTTP error: {e}, Response: {error_body}")
            raise APIError(
                f"HTTP error: {str(e)}", 
                status_code=e.response.status_code if e.response else None,
                response_body=error_body
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise APIError(f"Request failed: {str(e)}")
    
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
        recipient_uei: Optional[str] = None,
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
                "start_date": start_date or "2007-10-01",  # FY2008 start
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
            
        if recipient_uei:
            filters["recipient_id"] = recipient_uei
            
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
        """
        Get spending totals for a state
        
        Args:
            state: Two-letter state code (e.g., "OH")
            fiscal_year: Optional fiscal year (e.g., 2024)
            
        Returns:
            Dictionary with total amounts by award type
        """
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
        sort_field: str = "Award Amount",
        sort_direction: str = "desc"
    ) -> SearchResults:
        """
        Search for awards with flexible filtering
        
        Args:
            state: Two-letter state code (e.g., "OH", "CA", "TX")
            award_types: List of award type codes. Use constants:
                - GRANT_TYPES: ["02", "03", "04", "05"]
                - LOAN_TYPES: ["07", "08", "09"]
                - CONTRACT_TYPES: ["A", "B", "C", "D"]
                - ALL_FINANCIAL_ASSISTANCE: All non-contract types
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            agencies: List of awarding agency names
            recipient_name: Partial match on recipient name
            keywords: Search terms for award descriptions
            cfda_numbers: CFDA/Assistance Listing numbers
            location_type: "recipient" or "place_of_performance"
            limit: Results per page (max 100)
            page: Page number (1-based)
            sort_field: Field to sort by
            sort_direction: "asc" or "desc"
            
        Returns:
            SearchResults object with awards and pagination info
        """
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
        
        # Ensure we have at least one filter
        if not filters:
            raise ValidationError("At least one filter parameter is required")
        
        fields = [
            "Award ID",
            "Recipient Name",
            "recipient_uei",
            "recipient_id",
            "Recipient DUNS Number",
            "recipient_address_line_1",
            "recipient_city_name",
            "recipient_state_code",
            "recipient_zip_4_code",
            "recipient_country_code",
            "Start Date",
            "End Date",
            "Award Amount",
            "Total Outlays",
            "Awarding Agency",
            "Awarding Sub Agency",
            "Award Type",
            "Description",
            "Last Modified Date",
            "cfda_number",
            "generated_unique_award_id",
            "pop_city_name",
            "pop_state_code",
            "pop_zip_4_code"
        ]
        
        payload = {
            "filters": filters,
            "fields": fields,
            "limit": min(limit, 100),
            "page": page,
            "sort": sort_field,
            "order": sort_direction
        }
        
        response = self._make_request("POST", "/search/spending_by_award/", payload=payload)
        
        # Parse results
        awards = []
        for record in response.get("results", []):
            try:
                awards.append(Award.from_api_response(record))
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
        """
        Iterate through all awards with automatic pagination
        
        Use this for large result sets. Yields batches of Award objects.
        
        Args:
            (same as search_awards)
            max_records: Optional limit on total records
            
        Yields:
            Lists of Award objects (batch size = 100)
            
        Example:
            for batch in client.iter_awards(state="OH", award_types=GRANT_TYPES):
                for award in batch:
                    save_to_database(award)
        """
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
            
            # Check limits
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
        """
        Convenience method to get all awards as a single list
        
        Warning: Can be memory-intensive for large result sets.
        Use iter_awards() for better memory efficiency.
        
        Args:
            state: Two-letter state code
            award_types: List of award type codes
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_records: Safety limit (default 10,000)
            
        Returns:
            List of Award objects
        """
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
        """
        Autocomplete search for recipients
        
        Args:
            keyword: Search term
            limit: Max results
            
        Returns:
            List of matching recipient summaries
        """
        payload = {"keyword": keyword, "limit": limit}
        response = self._make_request("POST", "/autocomplete/recipient/", payload=payload)
        return response.get("results", [])
    
    def get_recipient_profile(self, recipient_id: str) -> Dict[str, Any]:
        """
        Get detailed profile for a recipient
        
        Args:
            recipient_id: The recipient hash ID or UEI
            
        Returns:
            Full recipient profile
        """
        return self._make_request("GET", f"/recipient/{recipient_id}/")
    
    def get_award_details(self, award_id: str) -> Dict[str, Any]:
        """
        Get full details for a specific award
        
        Args:
            award_id: The generated_unique_award_id
            
        Returns:
            Complete award details
        """
        # Determine if contract or assistance
        if award_id.startswith("CONT_"):
            endpoint = f"/awards/contracts/{award_id}/"
        else:
            endpoint = f"/awards/assistance/{award_id}/"
            
        return self._make_request("GET", endpoint)
    
    def get_spending_by_category(
        self,
        state: str,
        category: str = "awarding_agency",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        award_types: Optional[List[str]] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get spending grouped by category
        
        Args:
            state: Two-letter state code
            category: One of: awarding_agency, awarding_subagency, 
                     recipient, cfda, county, district
            start_date: Start date
            end_date: End date
            award_types: Award type filter
            limit: Max categories to return
            
        Returns:
            Spending broken down by category
        """
        state = self._validate_state(state)
        
        filters = self._build_filters(
            state=state,
            award_types=award_types,
            start_date=start_date,
            end_date=end_date
        )
        
        payload = {
            "filters": filters,
            "category": category,
            "limit": limit
        }
        
        return self._make_request("POST", "/search/spending_by_category/", payload=payload)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_ohio_grants(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 1000
) -> List[Award]:
    """
    Quick function to get Ohio grants
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        max_records: Max records to retrieve
        
    Returns:
        List of Award objects
    """
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
    """
    Quick function to get grants for any state
    
    Args:
        state: Two-letter state code
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        max_records: Max records to retrieve
        
    Returns:
        List of Award objects
    """
    client = USASpendingClient()
    return client.get_all_awards(
        state=state,
        award_types=GRANT_TYPES,
        start_date=start_date,
        end_date=end_date,
        max_records=max_records
    )


# =============================================================================
# CLI / TESTING
# =============================================================================

if __name__ == "__main__":
    # Simple test
    print("Testing USAspending API Client...")
    print("=" * 60)
    
    client = USASpendingClient()
    
    # Test 1: Get state totals
    print("\n1. Getting Ohio state totals...")
    try:
        totals = client.get_state_totals("OH", fiscal_year=2024)
        print(f"   Total prime awards: ${totals.get('total_prime_amount', 0):,.2f}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test 2: Search for grants
    print("\n2. Searching for Ohio grants (2024)...")
    try:
        results = client.search_awards(
            state="OH",
            award_types=GRANT_TYPES,
            start_date="2024-01-01",
            end_date="2024-12-31",
            limit=5
        )
        print(f"   Found {results.total_count} total grants")
        print(f"   First page has {len(results.awards)} results")
        
        if results.awards:
            print("\n   Top 5 grants:")
            for award in results.awards[:5]:
                print(f"   - {award.recipient_name}: ${award.total_obligation:,.2f}")
                print(f"     Agency: {award.awarding_agency}")
                print(f"     Description: {award.description[:80]}...")
                print()
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test 3: Search by recipient
    print("\n3. Searching for recipients matching 'Ohio State'...")
    try:
        recipients = client.search_recipients("Ohio State University", limit=5)
        for r in recipients:
            print(f"   - {r}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n" + "=" * 60)
    print("Tests complete!")
