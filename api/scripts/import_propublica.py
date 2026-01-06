"""
ProPublica Nonprofit Explorer Import Script

Enriches Ohio recipients with IRS Form 990 data from ProPublica's Nonprofit Explorer API.
Searches by organization NAME since USAspending doesn't provide EINs.

API docs: https://projects.propublica.org/nonprofits/api

Usage:
    python scripts/import_propublica.py [--limit 100] [--force] [--migrate]
"""

import os
import sys
import time
import re
import argparse
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, or_, and_, text
from app.database import SessionLocal
from app.models import Recipient, DataImport, Award

# ProPublica API base URL
PROPUBLICA_API_BASE = "https://projects.propublica.org/nonprofits/api/v2"

# Rate limiting: ProPublica doesn't specify limits, but be respectful
REQUESTS_PER_SECOND = 2
REQUEST_DELAY = 1.0 / REQUESTS_PER_SECOND

# Cache API responses to avoid duplicate calls
_api_cache: Dict[str, Any] = {}

# Patterns that suggest an organization might be a nonprofit
NONPROFIT_PATTERNS = [
    r'\buniversity\b', r'\bcollege\b', r'\bschool\b',
    r'\bhospital\b', r'\bmedical center\b', r'\bclinic\b',
    r'\bfoundation\b', r'\bcharit(y|ies)\b', r'\btrust\b',
    r'\bchurch\b', r'\bministr(y|ies)\b', r'\btemple\b', r'\bmosque\b',
    r'\bmuseum\b', r'\blibrary\b', r'\bsociety\b',
    r'\bassociation\b', r'\binstitute\b', r'\bcenter\b',
    r'\bcouncil\b', r'\bleague\b', r'\bfederation\b',
    r'\bvolunteer\b', r'\bcommunity\b', r'\bservice\b',
    r'\bymca\b', r'\bywca\b', r'\bboys?\s*(and|&)\s*girls?\b',
    r'\bred cross\b', r'\bsalvation army\b', r'\bunited way\b',
    r'\bhabitat\b', r'\bgoodwill\b',
]
NONPROFIT_REGEX = re.compile('|'.join(NONPROFIT_PATTERNS), re.IGNORECASE)


def looks_like_nonprofit(name: str) -> bool:
    """Check if a name looks like it could be a nonprofit"""
    if not name:
        return False
    return bool(NONPROFIT_REGEX.search(name))


def search_org_by_name(name: str, state: str = "OH") -> Optional[Dict]:
    """
    Search ProPublica for an organization by name.
    Returns the best match or None.
    """
    # Clean name for search
    search_name = name.strip()
    # Remove common suffixes that might confuse search
    for suffix in [' Inc', ' Inc.', ' LLC', ' Corp', ' Corp.', ' Co', ' Co.']:
        if search_name.endswith(suffix):
            search_name = search_name[:-len(suffix)]
    
    # Check cache
    cache_key = f"search:{search_name}:{state}"
    if cache_key in _api_cache:
        return _api_cache[cache_key]
    
    try:
        url = f"{PROPUBLICA_API_BASE}/search.json"
        params = {
            "q": search_name,
            "state[id]": state,
        }
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 404:
            _api_cache[cache_key] = None
            return None
            
        response.raise_for_status()
        data = response.json()
        
        orgs = data.get("organizations", [])
        if not orgs:
            _api_cache[cache_key] = None
            return None
        
        # Try to find best match
        name_lower = name.lower().strip()
        for org in orgs:
            org_name = (org.get("name") or "").lower().strip()
            # Exact match
            if org_name == name_lower:
                _api_cache[cache_key] = org
                return org
            # Starts with same words
            if org_name.startswith(name_lower[:20]) or name_lower.startswith(org_name[:20]):
                _api_cache[cache_key] = org
                return org
        
        # Return first result as fallback
        _api_cache[cache_key] = orgs[0]
        return orgs[0]
        
    except requests.exceptions.RequestException as e:
        print(f" API error: {e}")
        return None


def fetch_org_details(ein) -> Optional[Dict]:
    """
    Fetch full organization details including 990 filings by EIN.
    """
    ein_clean = str(ein).replace("-", "").strip()
    
    if len(ein_clean) != 9:
        return None
    
    # Check cache
    if ein_clean in _api_cache:
        return _api_cache[ein_clean]
    
    try:
        url = f"{PROPUBLICA_API_BASE}/organizations/{ein_clean}.json"
        response = requests.get(url, timeout=30)
        
        if response.status_code == 404:
            _api_cache[ein_clean] = None
            return None
        
        response.raise_for_status()
        data = response.json()
        
        _api_cache[ein_clean] = data
        return data
        
    except requests.exceptions.RequestException as e:
        print(f" API error for EIN {ein_clean}: {e}")
        return None


def extract_990_metrics(org_data: Dict) -> Dict[str, Any]:
    """
    Extract relevant metrics from ProPublica organization data.
    """
    org = org_data.get("organization", {})
    filings = org_data.get("filings_with_data", [])
    
    result = {
        "propublica_id": org.get("id"),
        "is_nonprofit": True,
        "nonprofit_ein": org.get("ein"),
        "tax_period": None,
        "form_type": None,
        "irs_total_revenue": None,
        "irs_total_expenses": None,
        "irs_net_assets": None,
        "irs_total_liabilities": None,
        "irs_total_compensation": None,
        "irs_top_salary": None,
        "irs_num_employees": None,
        "irs_program_expenses": None,
        "irs_admin_expenses": None,
        "irs_fundraising_expenses": None,
        "irs_program_ratio": None,
        "irs_comp_ratio": None,
    }
    
    # Get latest filing with data
    if filings:
        latest = filings[0]  # Already sorted by tax_period desc
        
        result["tax_period"] = latest.get("tax_prd")
        result["form_type"] = latest.get("formtype")
        
        # Financial metrics
        result["irs_total_revenue"] = latest.get("totrevenue")
        result["irs_total_expenses"] = latest.get("totfuncexpns")
        result["irs_net_assets"] = latest.get("totassetsend")
        result["irs_total_liabilities"] = latest.get("totliabend")
        
        # Compensation
        result["irs_total_compensation"] = latest.get("compnsatncurrofcr")
        
        # Employee count
        result["irs_num_employees"] = latest.get("totemployee")
        
        # Program expenses (Form 990 Part IX)
        prog_exp = latest.get("prgmservexpns") or latest.get("totprgmrevnue")
        mgmt_exp = latest.get("mgmtandgenexpns")
        fund_exp = latest.get("fundraisingexpns")
        
        result["irs_program_expenses"] = prog_exp
        result["irs_admin_expenses"] = mgmt_exp
        result["irs_fundraising_expenses"] = fund_exp
        
        # Calculate ratios
        total_exp = latest.get("totfuncexpns")
        if total_exp and total_exp > 0:
            if prog_exp:
                result["irs_program_ratio"] = round(prog_exp / total_exp, 3)
            
            comp = latest.get("compnsatncurrofcr") or 0
            if comp:
                result["irs_comp_ratio"] = round(comp / total_exp, 3)
    
    # Also check organization-level data for some fields
    if org.get("income_amount") and not result["irs_total_revenue"]:
        result["irs_total_revenue"] = org.get("income_amount")
    
    if org.get("asset_amount") and not result["irs_net_assets"]:
        result["irs_net_assets"] = org.get("asset_amount")
    
    return result


def import_propublica_data(limit: int = None, force: bool = False):
    """
    Main import function. Enriches recipients with 990 data.
    Searches by name since EINs aren't available from USAspending.
    
    Args:
        limit: Max number of recipients to process (for testing)
        force: Re-fetch even if already have 990 data
    """
    db = SessionLocal()
    
    # Track import
    import_record = DataImport(
        source="propublica_990",
        started_at=datetime.now(timezone.utc),
        status="running"
    )
    db.add(import_record)
    db.commit()
    
    try:
        # Find recipients to enrich
        # Priority: recipients with grants that look like nonprofits
        # Order by most funding first
        query = db.query(
            Recipient.id,
            Recipient.name,
            Recipient.city,
            Recipient.ein,
            func.sum(Award.amount).label("total_awards")
        ).join(
            Award, Award.recipient_id == Recipient.id
        ).group_by(Recipient.id)
        
        # Skip already processed unless force
        if not force:
            query = query.filter(
                or_(
                    Recipient.irs_last_updated.is_(None),
                    Recipient.propublica_id.is_(None)
                )
            )
        
        # Order by total funding descending (prioritize big recipients)
        query = query.order_by(func.sum(Award.amount).desc())
        
        if limit:
            query = query.limit(limit)
        
        recipients = query.all()
        total = len(recipients)
        
        print(f"Processing {total} recipients...")
        
        processed = 0
        enriched = 0
        not_found = 0
        skipped = 0
        errors = 0
        
        for i, row in enumerate(recipients):
            try:
                # Rate limit
                time.sleep(REQUEST_DELAY)
                
                name_display = row.name[:45] if row.name else "Unknown"
                print(f"[{i+1}/{total}] {name_display}...", end=" ", flush=True)
                
                # Check if name looks like a nonprofit
                if not looks_like_nonprofit(row.name):
                    print("⊘ Skip (not nonprofit pattern)")
                    skipped += 1
                    processed += 1
                    continue
                
                # Search by name
                search_result = search_org_by_name(row.name, "OH")
                
                if not search_result:
                    print("✗ Not found")
                    # Mark as checked
                    db.execute(
                        text("UPDATE recipients SET is_nonprofit = FALSE, irs_last_updated = :now WHERE id = :id"),
                        {"now": datetime.now(timezone.utc), "id": row.id}
                    )
                    not_found += 1
                    processed += 1
                    continue
                
                # Get EIN from search result
                ein = search_result.get("ein")
                if not ein:
                    print("✗ No EIN in result")
                    not_found += 1
                    processed += 1
                    continue
                
                # Fetch full 990 details
                org_data = fetch_org_details(ein)
                
                if org_data:
                    metrics = extract_990_metrics(org_data)
                    
                    # Update recipient - build SET clause dynamically
                    set_parts = []
                    params = {"id": row.id, "now": datetime.now(timezone.utc)}
                    
                    for key, value in metrics.items():
                        if value is not None:
                            set_parts.append(f"{key} = :{key}")
                            params[key] = value
                    
                    # Also update ein if we found one
                    if ein and not row.ein:
                        set_parts.append("ein = :ein")
                        params["ein"] = str(ein)
                    
                    set_parts.append("irs_last_updated = :now")
                    
                    sql = f"UPDATE recipients SET {', '.join(set_parts)} WHERE id = :id"
                    db.execute(text(sql), params)
                    
                    enriched += 1
                    org_name = search_result.get("name", "")[:30]
                    print(f"✓ Found: {org_name} (EIN: {ein})")
                else:
                    print(f"✗ No 990 data for EIN {ein}")
                    not_found += 1
                
                processed += 1
                
                # Commit in batches
                if processed % 25 == 0:
                    db.commit()
                    print(f"  --- Committed batch ({enriched} enriched, {not_found} not found, {skipped} skipped)")
                
            except Exception as e:
                print(f"Error: {e}")
                errors += 1
                continue
        
        # Final commit
        db.commit()
        
        # Update import record
        import_record.completed_at = datetime.now(timezone.utc)
        import_record.status = "completed"
        import_record.records_processed = processed
        import_record.records_updated = enriched
        db.commit()
        
        print(f"\n{'='*40}")
        print(f"=== Import Complete ===")
        print(f"{'='*40}")
        print(f"Processed: {processed}")
        print(f"Enriched:  {enriched}")
        print(f"Not found: {not_found}")
        print(f"Skipped:   {skipped} (didn't look like nonprofit)")
        print(f"Errors:    {errors}")
        
    except Exception as e:
        import_record.status = "failed"
        import_record.error_message = str(e)
        db.commit()
        raise
    
    finally:
        db.close()


def add_migration_columns():
    """
    Add new 990 columns to existing database.
    Run this once before importing.
    """
    db = SessionLocal()
    
    columns = [
        ("is_nonprofit", "BOOLEAN DEFAULT FALSE"),
        ("nonprofit_ein", "VARCHAR(10)"),
        ("tax_period", "VARCHAR(6)"),
        ("form_type", "VARCHAR(10)"),
        ("irs_total_revenue", "FLOAT"),
        ("irs_total_expenses", "FLOAT"),
        ("irs_net_assets", "FLOAT"),
        ("irs_total_liabilities", "FLOAT"),
        ("irs_total_compensation", "FLOAT"),
        ("irs_top_salary", "FLOAT"),
        ("irs_num_employees", "INTEGER"),
        ("irs_program_expenses", "FLOAT"),
        ("irs_admin_expenses", "FLOAT"),
        ("irs_fundraising_expenses", "FLOAT"),
        ("irs_program_ratio", "FLOAT"),
        ("irs_comp_ratio", "FLOAT"),
        ("propublica_id", "INTEGER"),
        ("irs_last_updated", "TIMESTAMP"),
    ]
    
    print("Adding 990 columns to recipients table...")
    
    for col_name, col_type in columns:
        try:
            db.execute(text(f"ALTER TABLE recipients ADD COLUMN {col_name} {col_type}"))
            db.commit()
            print(f"  ✓ Added {col_name}")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print(f"  - {col_name} already exists")
            else:
                print(f"  ✗ Error adding {col_name}: {e}")
            db.rollback()
    
    # Add indexes
    indexes = [
        ("ix_recipients_nonprofit", "CREATE INDEX IF NOT EXISTS ix_recipients_nonprofit ON recipients(is_nonprofit, ein)"),
        ("ix_recipients_propublica", "CREATE INDEX IF NOT EXISTS ix_recipients_propublica ON recipients(propublica_id)"),
    ]
    
    for idx_name, idx_sql in indexes:
        try:
            db.execute(text(idx_sql))
            db.commit()
            print(f"  ✓ Created index {idx_name}")
        except Exception as e:
            print(f"  Index {idx_name}: {e}")
            db.rollback()
    
    db.close()
    print("\nMigration complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import ProPublica 990 data")
    parser.add_argument("--limit", type=int, help="Max recipients to process")
    parser.add_argument("--force", action="store_true", help="Re-fetch already processed")
    parser.add_argument("--migrate", action="store_true", help="Add new columns to database")
    
    args = parser.parse_args()
    
    if args.migrate:
        add_migration_columns()
    else:
        import_propublica_data(limit=args.limit, force=args.force)
