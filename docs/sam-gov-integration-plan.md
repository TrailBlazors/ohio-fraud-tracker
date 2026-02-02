# SAM.gov Integration Plan

## Overview

SAM.gov (System for Award Management) is the authoritative source for federal exclusions (debarred/suspended entities). Integrating this data will flag recipients who are banned from receiving federal contracts and grants.

**Value**: Direct fraud signal - if a recipient is on the SAM.gov exclusion list, they should NOT be receiving federal funds.

---

## Data Available

### SAM.gov Exclusions API
- **Endpoint**: `https://api.sam.gov/entity-information/v4/exclusions`
- **Data**: All parties with active exclusions from federal procurement/nonprocurement
- **Update frequency**: Daily
- **Records**: ~70,000+ active exclusions

### Key Fields
| Field | Description | Use |
|-------|-------------|-----|
| `ueiSAM` | 12-char Unique Entity ID | Direct match to recipients |
| `exclusionName` | Entity/individual name | Fuzzy matching |
| `cageCode` | Commercial and Government Entity code | Secondary identifier |
| `exclusionType` | Ineligible, Prohibition, Voluntary | Severity indicator |
| `exclusionProgram` | Procurement, Nonprocurement, Reciprocal | Scope of ban |
| `excludingAgencyCode` | Agency that issued exclusion | Context |
| `activationDate` | When exclusion became active | Timeline |
| `terminationDate` | When exclusion ends (if any) | Current status |
| `ssnOrTinOrEin` | Tax ID (requires name param) | Strong match signal |

---

## API Access

### Rate Limits
| Account Type | Limit |
|--------------|-------|
| Personal (no role) | 10 requests/day |
| Personal (with role) | 1,000 requests/day |
| Federal system | 10,000 requests/day |

### Authentication
1. Create account at SAM.gov
2. Request API key from Account Details page
3. Pass key as `api_key` query parameter or `x-api-key` header

### Recommended Approach
Use **Bulk Extract** for initial load, then **Daily API** for updates:
- Extract endpoint: Same URL with `format=CSV` parameter
- Returns download token, then fetch file
- Max 1,000,000 records per extract

---

## Implementation Plan

### Phase 1: Database Model
**File**: `api/app/models.py`

Add new `SAMExclusion` model (separate from existing `ExcludedEntity` which is OIG LEIE):

```python
class SAMExclusion(Base):
    """SAM.gov excluded parties - debarred/suspended from federal awards"""
    __tablename__ = "sam_exclusions"

    id = Column(Integer, primary_key=True)

    # Identifiers
    uei_sam = Column(String(12), index=True, nullable=True)
    cage_code = Column(String(10), index=True, nullable=True)
    ein = Column(String(10), index=True, nullable=True)

    # Classification
    classification = Column(String(20))  # Individual, Firm, Vessel, Special Entity
    exclusion_name = Column(String(255), nullable=False)
    name_normalized = Column(String(255), index=True)

    # Exclusion details
    exclusion_type = Column(String(50))  # Ineligible, Prohibition/Restriction, Voluntary
    exclusion_program = Column(String(30))  # Procurement, Nonprocurement, Reciprocal
    excluding_agency_code = Column(String(10))
    excluding_agency_name = Column(String(255))

    # Dates
    activation_date = Column(Date, index=True)
    termination_date = Column(Date, nullable=True)
    create_date = Column(Date)
    update_date = Column(Date)

    # Address
    address_line1 = Column(String(255))
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), index=True)
    state = Column(String(2), index=True)
    zip_code = Column(String(10))
    country = Column(String(3))

    # Cross-reference to recipient
    matched_recipient_id = Column(Integer, ForeignKey("recipients.id"), nullable=True, index=True)
    match_confidence = Column(Float, nullable=True)
    match_method = Column(String(50), nullable=True)

    # Metadata
    sam_record_id = Column(String(50), unique=True)  # SAM's internal ID
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

### Phase 2: Import Script
**File**: `api/scripts/import_sam_exclusions.py`

```
1. Download bulk CSV extract (or paginated API for daily updates)
2. Parse and normalize records
3. Batch insert/update into sam_exclusions table
4. Cross-reference against recipients table:
   - Match by UEI (exact)
   - Match by EIN (exact)
   - Match by normalized name + state (fuzzy)
5. Create fraud flags for matches
```

### Phase 3: Fraud Flag Integration
**Flag type**: `sam_excluded`
**Severity**: `critical` (stronger than OIG LEIE since it's all federal programs)

```python
flag = FraudFlag(
    recipient_id=recipient.id,
    flag_type="sam_excluded",
    severity="critical",
    description=f"Recipient is DEBARRED/SUSPENDED on SAM.gov. "
                f"Excluded from {exclusion.exclusion_program} programs "
                f"by {exclusion.excluding_agency_name} on {exclusion.activation_date}. "
                f"Exclusion type: {exclusion.exclusion_type}.",
    evidence=json.dumps({...})
)
```

### Phase 4: API Endpoint
**File**: `api/app/routers/exclusions.py`

```
GET /api/exclusions/sam
  - List SAM exclusions with filters
  - Parameters: state, classification, agency, date_range

GET /api/exclusions/sam/check?uei=XXX&name=YYY
  - Check if entity is excluded
  - Used by frontend for real-time lookup
```

### Phase 5: Frontend Integration
- Add "SAM.gov Excluded" badge to recipient cards
- Add exclusion details to recipient detail page
- Add to red flags dashboard

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `api/app/models.py` | Modify | Add `SAMExclusion` model |
| `api/scripts/import_sam_exclusions.py` | Create | Import script |
| `api/app/routers/exclusions.py` | Create | API endpoints |
| `frontend/src/pages/red-flags/sam-excluded.astro` | Create | Red flags page |
| `frontend/src/components/SAMExclusionBadge.astro` | Create | Badge component |

---

## Environment Setup

Add to `.env`:
```
SAM_GOV_API_KEY=your_api_key_here
```

---

## Verification Plan

1. **Unit test**: Verify import script parses sample CSV correctly
2. **Integration test**: Import subset, verify DB records
3. **Match test**: Verify cross-reference finds known matches
4. **API test**: Verify endpoints return correct data
5. **Manual test**: Check a known excluded entity shows flag in UI

---

## Estimated Work

| Task | Effort |
|------|--------|
| Get SAM.gov API key | 1-2 days (approval process) |
| Database model | 30 min |
| Import script | 2-3 hours |
| Matching logic | 1-2 hours |
| API endpoints | 1 hour |
| Frontend integration | 1-2 hours |
| Testing | 1 hour |

**Total**: ~1 day of dev work (after API key obtained)

---

## Sources

- [SAM.gov Exclusions API](https://open.gsa.gov/api/exclusions-api/)
- [SAM.gov Entity/Exclusions Extracts](https://open.gsa.gov/api/sam-entity-extracts-api/)
- [SAM.gov API Guide](https://govconapi.com/sam-gov-api-guide)
- [2 CFR Part 180 - Exclusions](https://www.ecfr.gov/current/title-2/subtitle-A/chapter-I/part-180/subpart-E)
