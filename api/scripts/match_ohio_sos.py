"""
Ohio SOS Business to Recipient Matching

Matches Ohio Secretary of State business records to existing recipients
using multiple strategies with confidence scoring.

Matching strategies (in priority order):
1. Exact normalized name + same city (confidence: 1.0)
2. Exact normalized name only (confidence: 0.9)
3. Fuzzy match (>95% similarity) + same city (confidence: 0.85)
4. Fuzzy match (>90% similarity) + same city (confidence: 0.75)

Usage:
    python -m scripts.match_ohio_sos
    python -m scripts.match_ohio_sos --min-confidence 0.9
    python -m scripts.match_ohio_sos --update-recipients
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import get_db_context, init_db
from app.models import OhioSOSBusiness, Recipient, normalize_name


def levenshtein_ratio(s1: str, s2: str) -> float:
    """Calculate similarity ratio between two strings (0.0 to 1.0)"""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)

    # Quick rejection for very different lengths
    if abs(len1 - len2) > max(len1, len2) * 0.3:
        return 0.0

    # Create distance matrix
    distances = [[0] * (len2 + 1) for _ in range(len1 + 1)]

    for i in range(len1 + 1):
        distances[i][0] = i
    for j in range(len2 + 1):
        distances[0][j] = j

    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            distances[i][j] = min(
                distances[i-1][j] + 1,      # deletion
                distances[i][j-1] + 1,      # insertion
                distances[i-1][j-1] + cost  # substitution
            )

    distance = distances[len1][len2]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len) if max_len > 0 else 0.0


def build_recipient_index(db: Session) -> Tuple[Dict, Dict]:
    """Build indexes for fast recipient lookup"""
    print("  Building recipient lookup indexes...")

    # Index by normalized name
    name_index: Dict[str, List[Tuple[int, str, str]]] = defaultdict(list)

    # Index by normalized name + city
    name_city_index: Dict[str, int] = {}

    recipients = db.query(
        Recipient.id,
        Recipient.name_normalized,
        Recipient.city
    ).filter(
        Recipient.name_normalized.isnot(None),
        Recipient.name_normalized != ""
    ).all()

    for r in recipients:
        if r.name_normalized:
            name_index[r.name_normalized].append((r.id, r.name_normalized, r.city))

            if r.city:
                key = f"{r.name_normalized}|{r.city.lower()}"
                name_city_index[key] = r.id

    print(f"    Indexed {len(recipients):,} recipients")
    print(f"    Unique names: {len(name_index):,}")
    print(f"    Name+city combos: {len(name_city_index):,}")

    return name_index, name_city_index


def find_best_match(
    sos_business: OhioSOSBusiness,
    name_index: Dict,
    name_city_index: Dict,
    min_confidence: float = 0.75
) -> Tuple[Optional[int], Optional[float], Optional[str]]:
    """
    Find the best matching recipient for an SOS business.

    Returns: (recipient_id, confidence, method)
    """
    sos_name = sos_business.entity_name_normalized
    sos_city = (sos_business.principal_city or "").lower() if sos_business.principal_city else None

    if not sos_name:
        return None, None, None

    # Strategy 1: Exact name + city match (confidence: 1.0)
    if sos_city:
        key = f"{sos_name}|{sos_city}"
        if key in name_city_index:
            return name_city_index[key], 1.0, "exact_name_city"

    # Strategy 2: Exact name match (confidence: 0.9)
    if sos_name in name_index:
        matches = name_index[sos_name]
        if len(matches) == 1:
            return matches[0][0], 0.9, "exact_name"
        elif len(matches) > 1 and sos_city:
            # Multiple matches - prefer same city
            for rid, rname, rcity in matches:
                if rcity and rcity.lower() == sos_city:
                    return rid, 0.95, "exact_name_city_multi"
            # Return first match with lower confidence
            return matches[0][0], 0.7, "exact_name_multi"

    # Strategy 3: Fuzzy matching (only if exact didn't work)
    if min_confidence <= 0.85:
        best_match = None
        best_score = 0.0
        best_method = None

        # Sample candidates - names starting with same 3 chars
        prefix = sos_name[:3] if len(sos_name) >= 3 else sos_name
        candidates = [
            (rname, entries) for rname, entries in name_index.items()
            if rname.startswith(prefix) or (len(rname) >= 3 and sos_name.startswith(rname[:3]))
        ]

        for rname, entries in candidates:
            similarity = levenshtein_ratio(sos_name, rname)

            if similarity > best_score and similarity >= 0.90:
                # Check city match for higher confidence
                for rid, _, rcity in entries:
                    if sos_city and rcity and rcity.lower() == sos_city:
                        if similarity >= 0.95:
                            best_match = rid
                            best_score = similarity * 0.9  # 0.855 for 95% match
                            best_method = "fuzzy_name_city"
                        elif similarity >= 0.90:
                            best_match = rid
                            best_score = similarity * 0.8  # 0.72-0.76 for 90-95%
                            best_method = "fuzzy_name_city"
                    elif similarity >= 0.95 and best_score < similarity * 0.85:
                        best_match = entries[0][0]
                        best_score = similarity * 0.85
                        best_method = "fuzzy_name"

        if best_match and best_score >= min_confidence:
            return best_match, round(best_score, 3), best_method

    return None, None, None


def match_all_recipients(db: Session, min_confidence: float = 0.75) -> Dict:
    """Match all unmatched SOS businesses to recipients"""

    stats = {
        "total": 0,
        "already_matched": 0,
        "matched": 0,
        "unmatched": 0,
        "by_method": defaultdict(int),
    }

    # Build recipient indexes
    name_index, name_city_index = build_recipient_index(db)

    # Get unmatched SOS businesses
    print("\n  Finding unmatched SOS businesses...")
    unmatched_sos = db.query(OhioSOSBusiness).filter(
        OhioSOSBusiness.matched_recipient_id.is_(None)
    ).all()

    stats["total"] = len(unmatched_sos)
    print(f"    Found {stats['total']:,} unmatched SOS records")

    if stats["total"] == 0:
        print("    No unmatched records to process")
        return stats

    print("\n  Matching SOS businesses to recipients...")
    batch_size = 1000
    matched_updates = []

    for i, sos in enumerate(unmatched_sos):
        recipient_id, confidence, method = find_best_match(
            sos, name_index, name_city_index, min_confidence
        )

        if recipient_id:
            matched_updates.append({
                "id": sos.id,
                "matched_recipient_id": recipient_id,
                "match_confidence": confidence,
                "match_method": method,
            })
            stats["matched"] += 1
            stats["by_method"][method] += 1
        else:
            stats["unmatched"] += 1

        # Progress and batch update
        if (i + 1) % batch_size == 0:
            # Bulk update matched records
            for update in matched_updates:
                db.query(OhioSOSBusiness).filter(
                    OhioSOSBusiness.id == update["id"]
                ).update({
                    "matched_recipient_id": update["matched_recipient_id"],
                    "match_confidence": update["match_confidence"],
                    "match_method": update["match_method"],
                    "updated_at": datetime.utcnow(),
                })
            db.commit()
            matched_updates = []

            pct = (i + 1) / stats["total"] * 100
            print(f"    {i+1:,}/{stats['total']:,} ({pct:.0f}%) - Matched: {stats['matched']:,}")

    # Final batch
    if matched_updates:
        for update in matched_updates:
            db.query(OhioSOSBusiness).filter(
                OhioSOSBusiness.id == update["id"]
            ).update({
                "matched_recipient_id": update["matched_recipient_id"],
                "match_confidence": update["match_confidence"],
                "match_method": update["match_method"],
                "updated_at": datetime.utcnow(),
            })
        db.commit()

    return stats


def update_recipient_status(db: Session, min_confidence: float = 0.9) -> Dict:
    """
    Update recipient business_status from matched SOS records.
    Only updates for high-confidence matches.
    """
    print("\n  Updating recipient business status...")

    # Get high-confidence matches
    matched = db.query(
        OhioSOSBusiness.matched_recipient_id,
        OhioSOSBusiness.status,
        OhioSOSBusiness.formation_date,
        OhioSOSBusiness.entity_number,
        OhioSOSBusiness.match_confidence,
    ).filter(
        OhioSOSBusiness.matched_recipient_id.isnot(None),
        OhioSOSBusiness.match_confidence >= min_confidence,
        OhioSOSBusiness.status.isnot(None),
    ).all()

    updated = 0
    for match in matched:
        db.query(Recipient).filter(
            Recipient.id == match.matched_recipient_id
        ).update({
            "business_status": match.status,
            "formation_date": match.formation_date,
            "ohio_entity_number": match.entity_number,
            "sos_last_updated": datetime.utcnow(),
        })
        updated += 1

    db.commit()
    print(f"    Updated {updated:,} recipients with SOS status")

    return {"updated": updated}


def main():
    parser = argparse.ArgumentParser(description="Match Ohio SOS businesses to recipients")
    parser.add_argument("--min-confidence", type=float, default=0.75,
                        help="Minimum confidence for matching (0.0-1.0, default: 0.75)")
    parser.add_argument("--update-recipients", action="store_true",
                        help="Update recipient business_status from matched SOS records")

    args = parser.parse_args()

    print("=" * 70)
    print("Ohio SOS Business Matching")
    print("=" * 70)
    print(f"Minimum confidence: {args.min_confidence}")

    init_db()

    with get_db_context() as db:
        # Check if SOS table exists and has data
        try:
            sos_count = db.query(func.count(OhioSOSBusiness.id)).scalar() or 0
            print(f"\nSOS businesses in database: {sos_count:,}")

            if sos_count == 0:
                print("\nNo SOS businesses to match. Run import first:")
                print("  python -m scripts.import_ohio_sos --folder ../data/ohio-sos/")
                sys.exit(1)

            already_matched = db.query(func.count(OhioSOSBusiness.id)).filter(
                OhioSOSBusiness.matched_recipient_id.isnot(None)
            ).scalar() or 0
            print(f"Already matched: {already_matched:,}")

        except Exception as e:
            print(f"Error checking SOS table: {e}")
            print("Run import first to create the table.")
            sys.exit(1)

        # Run matching
        print("\n" + "-" * 70)
        print("MATCHING")
        print("-" * 70)

        results = match_all_recipients(db, args.min_confidence)

        print("\n" + "=" * 70)
        print("MATCHING COMPLETE")
        print("=" * 70)
        print(f"Total SOS records:    {results['total']:,}")
        print(f"Matched:              {results['matched']:,}")
        print(f"Unmatched:            {results['unmatched']:,}")
        print(f"\nMatches by method:")
        for method, count in sorted(results["by_method"].items(), key=lambda x: -x[1]):
            print(f"  {method}: {count:,}")

        # Update recipients if requested
        if args.update_recipients:
            print("\n" + "-" * 70)
            print("UPDATING RECIPIENTS")
            print("-" * 70)
            update_results = update_recipient_status(db, min_confidence=0.9)
            print(f"Recipients updated: {update_results['updated']:,}")

        # Final stats
        print("\n" + "-" * 70)
        final_matched = db.query(func.count(OhioSOSBusiness.id)).filter(
            OhioSOSBusiness.matched_recipient_id.isnot(None)
        ).scalar() or 0
        print(f"Total matched SOS records: {final_matched:,} / {sos_count:,}")


if __name__ == "__main__":
    main()
