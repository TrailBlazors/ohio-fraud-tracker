"""
Test pagination with the USAspending API

Run this to verify small batch retrieval works.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.data_sources.usaspending import USASpendingClient, GRANT_TYPES


def test_pagination():
    """Test retrieving small batches of records"""
    
    client = USASpendingClient()
    
    print("=" * 60)
    print("PAGINATION TEST")
    print("=" * 60)
    
    # Test 1: Get just 5 records
    print("\n1. Fetching 5 Ohio grants (page 1)...")
    results = client.search_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        limit=5,
        page=1
    )
    
    print(f"   Total available: {results.total_count:,}")
    print(f"   Retrieved: {len(results.awards)}")
    print(f"   Current page: {results.page}")
    print(f"   Has next page: {results.has_next}")
    
    print("\n   Awards:")
    for i, award in enumerate(results.awards, 1):
        print(f"   {i}. {award.recipient_name[:50]}: ${award.total_obligation:,.2f}")
    
    # Test 2: Get page 2
    print("\n2. Fetching page 2 (5 more records)...")
    results_p2 = client.search_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        limit=5,
        page=2
    )
    
    print(f"   Retrieved: {len(results_p2.awards)}")
    print(f"   Current page: {results_p2.page}")
    
    print("\n   Awards:")
    for i, award in enumerate(results_p2.awards, 1):
        print(f"   {i}. {award.recipient_name[:50]}: ${award.total_obligation:,.2f}")
    
    # Test 3: Very small batch
    print("\n3. Fetching just 3 records...")
    results_small = client.search_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        limit=3,
        page=1
    )
    
    print(f"   Requested: 3")
    print(f"   Retrieved: {len(results_small.awards)}")
    
    # Test 4: Different sort order
    print("\n4. Fetching 5 smallest grants (ascending order)...")
    results_asc = client.search_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        limit=5,
        page=1,
        sort_direction="asc"
    )
    
    print("\n   Smallest grants:")
    for i, award in enumerate(results_asc.awards, 1):
        print(f"   {i}. {award.recipient_name[:50]}: ${award.total_obligation:,.2f}")
    
    print("\n" + "=" * 60)
    print("PAGINATION TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    test_pagination()
