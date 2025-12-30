"""
Seed the database with sample data for testing.
Run this after setting up the API to see the UI working.
"""

import sys
from pathlib import Path
from datetime import date, datetime
import random

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import init_db, get_db_context
from app.models import Recipient, Agency, SubAgency, Award, normalize_name


# Sample data
AGENCIES = [
    ("HHS", "Department of Health and Human Services"),
    ("ED", "Department of Education"),
    ("DOT", "Department of Transportation"),
    ("HUD", "Housing and Urban Development"),
    ("DOE", "Department of Energy"),
    ("NSF", "National Science Foundation"),
    ("USDA", "Department of Agriculture"),
    ("EPA", "Environmental Protection Agency"),
    ("DOJ", "Department of Justice"),
    ("DOL", "Department of Labor"),
    ("NIH", "National Institutes of Health"),
    ("CDC", "Centers for Disease Control"),
    ("SBA", "Small Business Administration"),
]

SUB_AGENCIES = {
    "HHS": ["Health Resources and Services Admin", "Centers for Medicare & Medicaid", "Administration for Children and Families"],
    "ED": ["Office of Postsecondary Education", "Office of Elementary and Secondary Ed", "Office of Special Education"],
    "DOT": ["Federal Highway Administration", "Federal Transit Administration", "Federal Aviation Administration"],
    "NIH": ["National Cancer Institute", "National Heart, Lung, and Blood Institute", "National Institute of Allergy"],
}

RECIPIENTS = [
    ("Ohio State University", "Columbus", "43210", "active"),
    ("Cleveland Clinic Foundation", "Cleveland", "44195", "active"),
    ("Case Western Reserve University", "Cleveland", "44106", "active"),
    ("University of Cincinnati", "Cincinnati", "45221", "active"),
    ("Cincinnati Children's Hospital", "Cincinnati", "45229", "active"),
    ("Kent State University", "Kent", "44242", "active"),
    ("Miami University", "Oxford", "45056", "active"),
    ("Ohio University", "Athens", "45701", "active"),
    ("City of Columbus", "Columbus", "43215", "active"),
    ("City of Cleveland", "Cleveland", "44114", "active"),
    ("City of Cincinnati", "Cincinnati", "45202", "active"),
    ("Cuyahoga County", "Cleveland", "44113", "active"),
    ("Franklin County", "Columbus", "43215", "active"),
    ("Hamilton County", "Cincinnati", "45202", "active"),
    ("Ohio Department of Health", "Columbus", "43215", "active"),
    ("Akron Children's Hospital", "Akron", "44308", "active"),
    ("Nationwide Children's Hospital", "Columbus", "43205", "active"),
    ("MetroHealth System", "Cleveland", "44109", "active"),
    ("Wright State University", "Dayton", "45435", "active"),
    ("University of Toledo", "Toledo", "43606", "active"),
    ("Youngstown State University", "Youngstown", "44555", "active"),
    ("Bowling Green State University", "Bowling Green", "43403", "active"),
    ("Shawnee State University", "Portsmouth", "45662", "active"),
    ("Acme Consulting LLC", "Columbus", "43215", "inactive"),  # Flagged
    ("XYZ Holdings Inc", "Cleveland", "44114", "dissolved"),  # Flagged
]

AWARD_TYPES = [
    "block_grant", "formula_grant", "project_grant", 
    "cooperative_agreement", "direct_loan", "direct_payment"
]

DESCRIPTIONS = [
    "Research grant for biomedical studies",
    "Infrastructure improvement project",
    "Education program funding",
    "Healthcare services expansion",
    "Environmental remediation project",
    "Workforce development initiative",
    "Community development block grant",
    "Public health emergency response",
    "Scientific research and development",
    "Transportation improvement program",
    "Housing assistance program",
    "Child and family services",
]


def seed_database():
    """Populate database with sample data"""
    
    print("Initializing database...")
    init_db()
    
    with get_db_context() as db:
        # Check if already seeded
        existing = db.query(Agency).count()
        if existing > 0:
            print(f"Database already has {existing} agencies. Skipping seed.")
            return
        
        print("Creating agencies...")
        agency_map = {}
        for code, name in AGENCIES:
            agency = Agency(code=code, name=name)
            db.add(agency)
            db.flush()
            agency_map[code] = agency.id
        
        print("Creating sub-agencies...")
        sub_agency_map = {}
        for agency_code, subs in SUB_AGENCIES.items():
            for sub_name in subs:
                sub = SubAgency(
                    agency_id=agency_map[agency_code],
                    name=sub_name
                )
                db.add(sub)
                db.flush()
                sub_agency_map[sub_name] = sub.id
        
        print("Creating recipients...")
        recipient_map = {}
        for name, city, zip_code, status in RECIPIENTS:
            recipient = Recipient(
                name=name,
                name_normalized=normalize_name(name),
                city=city,
                state="OH",
                zip_code=zip_code,
                business_status=status,
                uei=f"UEI{random.randint(100000000, 999999999)}",
            )
            db.add(recipient)
            db.flush()
            recipient_map[name] = recipient.id
        
        print("Creating awards...")
        award_count = 0
        
        for recipient_name, recipient_id in recipient_map.items():
            # Each recipient gets 2-10 awards
            num_awards = random.randint(2, 10)
            
            for i in range(num_awards):
                agency_code = random.choice([a[0] for a in AGENCIES])
                
                award = Award(
                    source="usaspending",
                    source_award_id=f"ASST_{random.randint(10000000, 99999999)}",
                    recipient_id=recipient_id,
                    agency_id=agency_map[agency_code],
                    award_type=random.choice(AWARD_TYPES),
                    amount=random.randint(50000, 20000000),
                    description=random.choice(DESCRIPTIONS),
                    award_date=date(
                        random.randint(2020, 2024),
                        random.randint(1, 12),
                        random.randint(1, 28)
                    ),
                    cfda_number=f"{random.randint(10, 99)}.{random.randint(100, 999)}",
                    pop_city=RECIPIENTS[list(recipient_map.keys()).index(recipient_name)][1],
                    pop_state="OH",
                )
                db.add(award)
                award_count += 1
        
        db.commit()
        
        print(f"\nSeeding complete!")
        print(f"  - {len(agency_map)} agencies")
        print(f"  - {len(sub_agency_map)} sub-agencies")
        print(f"  - {len(recipient_map)} recipients")
        print(f"  - {award_count} awards")


if __name__ == "__main__":
    seed_database()
