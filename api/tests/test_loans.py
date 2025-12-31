"""
Test loans API specifically
"""
import requests
import json

url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Test with loan type codes
payload = {
    "filters": {
        "recipient_locations": [{"country": "USA", "state": "OH"}],
        "award_type_codes": ["07", "08"],  # Direct loan, Guaranteed loan
        "time_period": [{"start_date": "2024-01-01", "end_date": "2024-12-31"}]
    },
    "fields": [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Awarding Agency",
        "Award Type",
        "Description",
        "Start Date",
        "End Date",
    ],
    "limit": 5,
    "page": 1,
    "sort": "Award Amount",
    "order": "desc"
}

print("Testing loans API...")
print(f"Payload:\n{json.dumps(payload, indent=2)}\n")

response = requests.post(url, json=payload)

print(f"Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print(f"Results: {len(data.get('results', []))}")
    print(f"Total: {data.get('page_metadata', {})}")
    if data.get("results"):
        print(f"\nFirst result:\n{json.dumps(data['results'][0], indent=2)}")
else:
    print(f"Error:\n{response.text}")
