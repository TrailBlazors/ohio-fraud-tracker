"""
Debug script to test USAspending API requests
"""
import requests
import json

url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Minimal test payload based on API docs
payload = {
    "filters": {
        "recipient_locations": [
            {"country": "USA", "state": "OH"}
        ],
        "award_type_codes": ["02", "03", "04", "05"],  # Grants
        "time_period": [
            {"start_date": "2024-01-01", "end_date": "2024-12-31"}
        ]
    },
    "fields": [
        "Award ID",
        "Recipient Name",
        "Start Date",
        "End Date",
        "Award Amount",
        "Awarding Agency",
        "Awarding Sub Agency",
        "Award Type",
        "Description"
    ],
    "limit": 5,
    "page": 1,
    "sort": "Award Amount",
    "order": "desc"
}

print("Testing USAspending API...")
print(f"URL: {url}")
print(f"Payload:\n{json.dumps(payload, indent=2)}")

response = requests.post(url, json=payload)

print(f"\nStatus: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print(f"Results: {len(data.get('results', []))}")
    print(f"Total: {data.get('page_metadata', {}).get('total', 'N/A')}")
    if data.get('results'):
        print(f"\nFirst result:\n{json.dumps(data['results'][0], indent=2)}")
else:
    print(f"Error: {response.text}")
