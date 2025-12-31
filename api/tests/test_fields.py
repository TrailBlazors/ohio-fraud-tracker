"""
Debug script to find valid USAspending API fields
"""
import requests
import json

url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Start with minimal fields that we KNOW work from the first test
base_payload = {
    "filters": {
        "recipient_locations": [{"country": "USA", "state": "OH"}],
        "award_type_codes": ["02", "03", "04", "05"],
        "time_period": [{"start_date": "2024-01-01", "end_date": "2024-12-31"}]
    },
    "limit": 1,
    "page": 1,
    "sort": "Award Amount",
    "order": "desc"
}

# Test different field sets
field_sets = {
    "minimal": [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Awarding Agency",
        "Award Type",
        "Description",
        "Start Date",
        "End Date",
    ],
    "with_sub_agency": [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Awarding Agency",
        "Awarding Sub Agency",
        "Award Type",
    ],
    "with_recipient_location": [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "recipient_city_name",
        "recipient_state_code",
    ],
    "with_cfda": [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "cfda_number",
    ],
    "with_pop": [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Place of Performance City",
        "Place of Performance State",
    ],
}

print("Testing USAspending API field names...\n")

for name, fields in field_sets.items():
    payload = base_payload.copy()
    payload["fields"] = fields
    
    response = requests.post(url, json=payload)
    
    if response.status_code == 200:
        data = response.json()
        result = data.get("results", [{}])[0] if data.get("results") else {}
        print(f"✅ {name}: OK")
        print(f"   Returned keys: {list(result.keys())}")
    else:
        print(f"❌ {name}: {response.status_code}")
        try:
            error = response.json()
            print(f"   Error: {error.get('detail', response.text[:200])}")
        except:
            print(f"   Error: {response.text[:200]}")
    print()

# Now test getting ALL available fields by not specifying any
print("\n--- Testing with NO fields specified ---")
payload = base_payload.copy()
# Don't include 'fields' key at all
response = requests.post(url, json=payload)

if response.status_code == 200:
    data = response.json()
    result = data.get("results", [{}])[0] if data.get("results") else {}
    print(f"✅ No fields specified: OK")
    print(f"   Available keys:\n")
    for k, v in sorted(result.items()):
        print(f"   {k}: {type(v).__name__} = {str(v)[:50]}")
else:
    print(f"❌ Failed: {response.status_code}")
    print(response.text[:500])
