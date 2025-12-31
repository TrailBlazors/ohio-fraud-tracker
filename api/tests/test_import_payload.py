"""
Test the exact payload being sent by the import script
"""
import requests
import json

url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# This is what our client should be sending
payload = {
    "filters": {
        "recipient_locations": [{"country": "USA", "state": "OH"}],
        "award_type_codes": ["02", "03", "04", "05", "07", "08", "09"],
        "time_period": [{"start_date": "2020-01-01", "end_date": "2025-12-31"}]
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
        "Description",
        "cfda_number",
        "recipient_city_name",
        "recipient_state_code",
        "Place of Performance City",
        "Place of Performance State",
    ],
    "limit": 100,
    "page": 1,
    "sort": "Award Amount",
    "order": "desc"
}

print("Testing full import payload...")
print(f"Payload:\n{json.dumps(payload, indent=2)}\n")

response = requests.post(url, json=payload)

print(f"Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print(f"Results: {len(data.get('results', []))}")
    print(f"Page metadata: {data.get('page_metadata', {})}")
    if data.get("results"):
        print(f"\nFirst result keys: {list(data['results'][0].keys())}")
else:
    print(f"Error response:\n{response.text}")
