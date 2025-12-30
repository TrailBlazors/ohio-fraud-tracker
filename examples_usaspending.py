"""
Example: Using the USAspending API Client

This script demonstrates various ways to query federal spending data
for fraud investigation purposes.
"""

import json
import csv
from datetime import datetime
from pathlib import Path

# Add the src directory to the path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.data_sources.usaspending import (
    USASpendingClient,
    GRANT_TYPES,
    LOAN_TYPES,
    ALL_FINANCIAL_ASSISTANCE,
    US_STATES,
)


def example_basic_search():
    """Basic search for Ohio grants"""
    print("\n" + "="*70)
    print("EXAMPLE 1: Basic Search for Ohio Grants")
    print("="*70)
    
    client = USASpendingClient()
    
    # Search for grants in Ohio for 2024
    results = client.search_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        end_date="2024-12-31",
        limit=10
    )
    
    print(f"\nTotal grants found: {results.total_count:,}")
    print(f"Showing first {len(results.awards)} results:\n")
    
    for i, award in enumerate(results.awards, 1):
        print(f"{i}. {award.recipient_name}")
        print(f"   Amount: ${award.total_obligation:,.2f}")
        print(f"   Agency: {award.awarding_agency}")
        print(f"   Location: {award.recipient_city}, {award.recipient_state}")
        print(f"   Description: {award.description[:100]}..." if award.description else "   No description")
        print()


def example_search_any_state(state_code: str):
    """Search grants for any US state"""
    print("\n" + "="*70)
    print(f"EXAMPLE 2: Search for {US_STATES.get(state_code, state_code)} Grants")
    print("="*70)
    
    client = USASpendingClient()
    
    results = client.search_awards(
        state=state_code,
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        limit=5
    )
    
    print(f"\nTotal grants in {state_code}: {results.total_count:,}")
    
    for award in results.awards:
        print(f"- {award.recipient_name}: ${award.total_obligation:,.2f}")


def example_search_loans():
    """Search for federal loans in Ohio"""
    print("\n" + "="*70)
    print("EXAMPLE 3: Search for Ohio Federal Loans")
    print("="*70)
    
    client = USASpendingClient()
    
    results = client.search_awards(
        state="OH",
        award_types=LOAN_TYPES,
        start_date="2020-01-01",  # Includes COVID-era loans
        limit=10
    )
    
    print(f"\nTotal loans found: {results.total_count:,}")
    print(f"\nTop 10 by amount:")
    
    for award in results.awards:
        print(f"- {award.recipient_name}")
        print(f"  Amount: ${award.total_obligation:,.2f}")
        print(f"  Type: {award.award_type}")
        print()


def example_search_by_recipient():
    """Search for a specific recipient"""
    print("\n" + "="*70)
    print("EXAMPLE 4: Search by Recipient Name")
    print("="*70)
    
    client = USASpendingClient()
    
    # First, use autocomplete to find recipients
    print("\nSearching for recipients matching 'Ohio State University'...")
    recipients = client.search_recipients("Ohio State University", limit=5)
    
    print(f"Found {len(recipients)} matching recipients:")
    for r in recipients:
        print(f"  - {r}")
    
    # Now search for awards to that recipient
    print("\nSearching for awards to 'Ohio State University'...")
    results = client.search_awards(
        state="OH",
        recipient_name="Ohio State University",
        start_date="2023-01-01",
        limit=10
    )
    
    print(f"\nFound {results.total_count:,} awards")
    
    total_amount = sum(a.total_obligation for a in results.awards)
    print(f"Total in first page: ${total_amount:,.2f}")


def example_search_by_agency():
    """Search by awarding agency"""
    print("\n" + "="*70)
    print("EXAMPLE 5: Search by Agency")
    print("="*70)
    
    client = USASpendingClient()
    
    # Search for HHS grants in Ohio
    results = client.search_awards(
        state="OH",
        award_types=GRANT_TYPES,
        agencies=["Department of Health and Human Services"],
        start_date="2024-01-01",
        limit=10
    )
    
    print(f"\nHHS grants to Ohio: {results.total_count:,}")
    
    for award in results.awards[:5]:
        print(f"- {award.recipient_name}: ${award.total_obligation:,.2f}")
        print(f"  Sub-agency: {award.awarding_sub_agency}")


def example_spending_by_category():
    """Get spending broken down by category"""
    print("\n" + "="*70)
    print("EXAMPLE 6: Spending by Category")
    print("="*70)
    
    client = USASpendingClient()
    
    # Get spending by awarding agency
    print("\nOhio spending by awarding agency (2024):")
    result = client.get_spending_by_category(
        state="OH",
        category="awarding_agency",
        start_date="2024-01-01",
        award_types=ALL_FINANCIAL_ASSISTANCE,
        limit=10
    )
    
    for item in result.get("results", [])[:10]:
        name = item.get("name", "Unknown")
        amount = item.get("amount", 0)
        print(f"  {name}: ${amount:,.2f}")


def example_iterate_large_dataset():
    """Demonstrate pagination through large datasets"""
    print("\n" + "="*70)
    print("EXAMPLE 7: Iterating Through Large Datasets")
    print("="*70)
    
    client = USASpendingClient()
    
    print("\nIterating through Ohio grants (limited to 500 for demo)...")
    
    total_count = 0
    total_amount = 0
    recipients = set()
    
    for batch in client.iter_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        max_records=500
    ):
        for award in batch:
            total_count += 1
            total_amount += award.total_obligation
            recipients.add(award.recipient_name)
    
    print(f"\nProcessed {total_count} awards")
    print(f"Total amount: ${total_amount:,.2f}")
    print(f"Unique recipients: {len(recipients)}")


def example_export_to_csv():
    """Export results to CSV for analysis"""
    print("\n" + "="*70)
    print("EXAMPLE 8: Export to CSV")
    print("="*70)
    
    client = USASpendingClient()
    
    # Get Ohio grants
    results = client.search_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        limit=100
    )
    
    # Create data directory if needed
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    
    # Export to CSV
    csv_path = data_dir / "ohio_grants_sample.csv"
    
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            "Award ID",
            "Recipient Name", 
            "Recipient City",
            "Recipient State",
            "Recipient ZIP",
            "Amount",
            "Awarding Agency",
            "Description",
            "Start Date",
            "End Date",
            "CFDA Number"
        ])
        
        # Data rows
        for award in results.awards:
            writer.writerow([
                award.award_id,
                award.recipient_name,
                award.recipient_city,
                award.recipient_state,
                award.recipient_zip,
                award.total_obligation,
                award.awarding_agency,
                award.description[:200] if award.description else "",
                award.start_date,
                award.end_date,
                award.cfda_number
            ])
    
    print(f"\nExported {len(results.awards)} records to: {csv_path}")


def example_export_to_json():
    """Export results to JSON"""
    print("\n" + "="*70)
    print("EXAMPLE 9: Export to JSON")
    print("="*70)
    
    client = USASpendingClient()
    
    results = client.search_awards(
        state="OH",
        award_types=GRANT_TYPES,
        start_date="2024-01-01",
        limit=50
    )
    
    # Create data directory
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    
    json_path = data_dir / "ohio_grants_sample.json"
    
    # Convert to JSON-serializable format
    data = {
        "query": {
            "state": "OH",
            "award_types": GRANT_TYPES,
            "start_date": "2024-01-01",
            "exported_at": datetime.now().isoformat()
        },
        "total_count": results.total_count,
        "awards": [award.to_dict() for award in results.awards]
    }
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    
    print(f"\nExported {len(results.awards)} records to: {json_path}")


def main():
    """Run all examples"""
    print("\n" + "#"*70)
    print("# USAspending API Client - Examples")
    print("# " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("#"*70)
    
    try:
        # Basic examples
        example_basic_search()
        example_search_any_state("TX")  # Try Texas
        example_search_loans()
        
        # Advanced examples
        example_search_by_recipient()
        example_search_by_agency()
        example_spending_by_category()
        
        # Data processing examples
        example_iterate_large_dataset()
        example_export_to_csv()
        example_export_to_json()
        
        print("\n" + "="*70)
        print("All examples completed successfully!")
        print("="*70)
        
    except Exception as e:
        print(f"\nError running examples: {e}")
        raise


if __name__ == "__main__":
    main()
