# Ohio Campaign Finance Integration Plan

## Overview

Integrate Ohio Secretary of State campaign finance data to identify potential pay-to-play patterns between political donors and government award recipients.

**Fraud Detection Value**: Cross-reference recipients against campaign contributors to find entities that donated to politicians and subsequently received government awards.

---

## Data Source

### Primary: Ohio Secretary of State FTP
- **URL**: https://www6.ohiosos.gov/ords/
- **Format**: CSV files by committee type and year
- **Coverage**: 1990-2022 (update annually)
- **Records**: ~12-16 million contribution records
- **Size**: ~2.3 GB total

### Alternative: Accountability Project (Pre-Cleaned)
- **URL**: https://www.publicaccountability.org/datasets/55/oh_contribs/
- **GitHub**: https://github.com/irworkshop/accountability_datacleaning/tree/master/state/oh
- **Benefit**: Already normalized names, addresses, cleaned data
- **Records**: 16,576,543 contributions + 1,568,931 expenditures

---

## Data Structure

### File Organization
Files split by committee type and calendar year:
- `CAN_YYYY.csv` - Candidate committees
- `PAC_YYYY.csv` - Political Action Committees
- `PAR_YYYY.csv` - Party committees

### Key Columns (31 total)

| Column | Type | Description |
|--------|------|-------------|
| `com_name` | string | Committee receiving contribution |
| `first`, `middle`, `last`, `suffix` | string | Contributor name parts |
| `address`, `city`, `state`, `zip` | string | Contributor address |
| `amount` | float | Contribution amount |
| `date` | date | Contribution date |
| `rpt_year` | int | Report year |
| `master_key` | int | Committee identifier |
| `file_type` | string | CAN/PAC/PAR |
| `district` | int | Electoral district |

---

## Implementation Plan

### Phase 1: Database Model
**File**: `api/app/models.py`

```python
class CampaignContribution(Base):
    """Ohio campaign finance contributions"""
    __tablename__ = "campaign_contributions"

    id = Column(Integer, primary_key=True)

    # Committee (recipient of contribution)
    committee_name = Column(String(255), nullable=False, index=True)
    committee_type = Column(String(10))  # CAN, PAC, PAR
    master_key = Column(Integer, index=True)
    district = Column(Integer, nullable=True)

    # Contributor
    contributor_first = Column(String(100))
    contributor_middle = Column(String(100))
    contributor_last = Column(String(100))
    contributor_suffix = Column(String(20))
    contributor_name_normalized = Column(String(255), index=True)

    # Address
    address = Column(String(255))
    city = Column(String(100), index=True)
    state = Column(String(2))
    zip_code = Column(String(10))

    # Contribution details
    amount = Column(Float, nullable=False, index=True)
    contribution_date = Column(Date, index=True)
    report_year = Column(Integer, index=True)

    # Cross-reference
    matched_recipient_id = Column(Integer, ForeignKey("recipients.id"), nullable=True, index=True)
    match_confidence = Column(Float, nullable=True)

    # Metadata
    source_file = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class Politician(Base):
    """Ohio politicians (candidates) for linking"""
    __tablename__ = "politicians"

    id = Column(Integer, primary_key=True)
    master_key = Column(Integer, unique=True, index=True)  # Links to contributions
    name = Column(String(255), nullable=False)
    party = Column(String(50))
    office = Column(String(100))
    district = Column(String(50))

    # Totals (denormalized for performance)
    total_contributions = Column(Float, default=0)
    contribution_count = Column(Integer, default=0)
```

### Phase 2: Import Script
**File**: `api/scripts/import_campaign_finance.py`

```
1. Download CSV files from Ohio SOS FTP (or use Accountability Project cleaned data)
2. Parse each file, normalize contributor names
3. Batch insert into campaign_contributions table
4. Build politicians lookup table from unique committees
5. Cross-reference contributors against recipients table:
   - Match by normalized name
   - Match by address components
6. Create fraud flags for matches with significant donations
```

### Phase 3: Correlation Analysis
**File**: `api/app/routers/correlation.py` (extend existing)

Add new correlation type: `political_donor`

```python
def find_political_donors():
    """
    Find recipients who:
    1. Donated to political campaigns
    2. Subsequently received government awards
    3. Calculate donation-to-award ratio
    """
    # Query: recipients with both contributions AND awards
    # Flag if: contribution date < award date (timeline suggests influence)
    # Severity based on: donation amount, award amount, time proximity
```

### Phase 4: Fraud Flag Integration
**Flag type**: `political_donor`
**Severity**: Based on amounts and timing

```python
flag = FraudFlag(
    recipient_id=recipient.id,
    flag_type="political_donor",
    severity="medium",  # or high if large amounts
    description=f"Recipient donated ${total_donated:,.0f} to political campaigns "
                f"and received ${total_awards:,.0f} in government awards. "
                f"Donations to: {committee_names}.",
    evidence=json.dumps({
        "donations": [...],
        "awards_after_donation": [...],
        "timeline": "donation preceded award by X days"
    })
)
```

### Phase 5: API Endpoints
**File**: `api/app/routers/campaign_finance.py`

```
GET /api/campaign-finance/contributions
  - Search contributions by contributor name, committee, date range, amount
  - Pagination support

GET /api/campaign-finance/top-donors
  - Top contributors by total amount
  - Filter by committee type, year range

GET /api/campaign-finance/recipient/{id}/donations
  - All donations made by a specific recipient
  - Timeline view with awards overlaid

GET /api/campaign-finance/stats
  - Summary statistics for dashboard
```

### Phase 6: Frontend Integration

**New page**: `frontend/src/pages/red-flags/political-donors.astro`
- List recipients flagged as political donors
- Show donation amounts alongside award amounts
- Timeline visualization

**Recipient detail enhancement**:
- Add "Campaign Contributions" tab
- Show donations made by recipient
- Highlight if donations preceded awards

**Dashboard widget**:
- "Political Connections" summary card
- Link to detailed analysis

**IMPORTANT - UI must display data coverage**:
- Show "Data covers 1990-2022" prominently on campaign finance pages
- Add last-updated timestamp
- Note in footer/disclaimer about data currency

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `api/app/models.py` | Modify | Add `CampaignContribution`, `Politician` models |
| `api/scripts/import_campaign_finance.py` | Create | Import script for CSV files |
| `api/app/routers/campaign_finance.py` | Create | API endpoints |
| `api/app/routers/correlation.py` | Modify | Add political donor correlation |
| `frontend/src/pages/red-flags/political-donors.astro` | Create | Red flags page |
| `frontend/src/pages/campaign-finance/index.astro` | Create | Campaign finance search |
| `frontend/src/components/PoliticalDonorBadge.astro` | Create | Badge component |

---

## Matching Strategy

### Name Matching
1. Normalize contributor name: `first + middle + last` → lowercase, strip suffixes
2. Compare against `recipients.name_normalized`
3. Use fuzzy matching (Levenshtein distance < 3) for close matches
4. Require city match for confidence boost

### Entity Matching Challenges
- Individuals vs. business names
- Name variations (Bob vs Robert)
- Business name changes over time

### Recommended Approach
```python
def match_contributor_to_recipient(contribution, db):
    # 1. Exact name match
    exact = db.query(Recipient).filter(
        Recipient.name_normalized == contribution.contributor_name_normalized
    ).first()
    if exact:
        return exact, 1.0

    # 2. Fuzzy name + city match
    candidates = db.query(Recipient).filter(
        Recipient.city == contribution.city,
        Recipient.state == "OH"
    ).all()

    for r in candidates:
        similarity = fuzzy_match(r.name_normalized, contribution.contributor_name_normalized)
        if similarity > 0.85:
            return r, similarity

    return None, 0.0
```

---

## Storage Estimates

| Table | Records | Est. Size |
|-------|---------|-----------|
| campaign_contributions | 16M | ~2 GB |
| politicians | ~10K | ~2 MB |

**Note**: May want to import only recent years (2015+) initially to reduce size.

---

## Verification Plan

1. **Import test**: Load sample year, verify record counts match source
2. **Match test**: Spot-check known matches (public figures)
3. **Correlation test**: Verify timeline logic (donation before award)
4. **UI test**: Confirm data coverage dates displayed correctly
5. **Performance test**: Query speed with 16M records

---

## UI Data Coverage Requirements

Per user request, all campaign finance UI must clearly display:

1. **Header/Banner**: "Campaign Finance Data: 1990-2022"
2. **Last Updated**: Show import timestamp
3. **Disclaimer**: "Data from Ohio Secretary of State. Updated annually."
4. **Search filters**: Year range selector with min/max bounds
5. **Empty state**: If searching outside covered years, show clear message

---

## Estimated Work

| Task | Effort |
|------|--------|
| Database models | 30 min |
| Import script | 3-4 hours |
| Matching logic | 2-3 hours |
| Correlation analysis | 2 hours |
| API endpoints | 2 hours |
| Frontend pages | 3-4 hours |
| Testing | 2 hours |

**Total**: ~2 days of dev work

---

## Sources

- [Ohio SOS Campaign Finance](https://www.ohiosos.gov/campaign-finance/)
- [Ohio SOS Search/Download](https://www.ohiosos.gov/campaign-finance/search/)
- [Accountability Project - Ohio Contributions](https://www.publicaccountability.org/datasets/55/oh_contribs/)
- [GitHub - Data Cleaning Scripts](https://github.com/irworkshop/accountability_datacleaning)
