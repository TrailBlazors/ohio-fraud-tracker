"""
NAICS Code Import Script

Loads NAICS (North American Industry Classification System) codes into the database.
These provide human-readable industry descriptions for business type searches.

Data source: https://www.census.gov/naics/

Common NAICS codes for fraud detection:
- 484: Truck Transportation
- 624: Social Assistance (includes day care)
- 621: Ambulatory Health Care
- 722: Food Services and Drinking Places
- 236: Construction of Buildings
- 238: Specialty Trade Contractors

Usage:
    python -m scripts.import_naics
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_db_context, init_db
from app.models import NaicsCode

# Common NAICS codes with titles
# Format: (code, title, sector, sector_title)
NAICS_DATA = [
    # Transportation (48-49)
    ("48", "Transportation", "48", "Transportation and Warehousing"),
    ("484", "Truck Transportation", "48", "Transportation and Warehousing"),
    ("484110", "General Freight Trucking, Local", "48", "Transportation and Warehousing"),
    ("484121", "General Freight Trucking, Long-Distance, Truckload", "48", "Transportation and Warehousing"),
    ("484122", "General Freight Trucking, Long-Distance, Less Than Truckload", "48", "Transportation and Warehousing"),
    ("484210", "Used Household and Office Goods Moving", "48", "Transportation and Warehousing"),
    ("484220", "Specialized Freight Trucking, Local", "48", "Transportation and Warehousing"),
    ("484230", "Specialized Freight Trucking, Long-Distance", "48", "Transportation and Warehousing"),
    ("485", "Transit and Ground Passenger Transportation", "48", "Transportation and Warehousing"),
    ("485110", "Urban Transit Systems", "48", "Transportation and Warehousing"),
    ("485210", "Interurban and Rural Bus Transportation", "48", "Transportation and Warehousing"),
    ("485310", "Taxi Service", "48", "Transportation and Warehousing"),
    ("485320", "Limousine Service", "48", "Transportation and Warehousing"),
    ("485410", "School and Employee Bus Transportation", "48", "Transportation and Warehousing"),
    ("485510", "Charter Bus Industry", "48", "Transportation and Warehousing"),
    ("485990", "Other Transit and Ground Passenger Transportation", "48", "Transportation and Warehousing"),
    
    # Social Assistance / Child Care (62)
    ("62", "Health Care and Social Assistance", "62", "Health Care and Social Assistance"),
    ("624", "Social Assistance", "62", "Health Care and Social Assistance"),
    ("624110", "Child and Youth Services", "62", "Health Care and Social Assistance"),
    ("624120", "Services for the Elderly and Persons with Disabilities", "62", "Health Care and Social Assistance"),
    ("624190", "Other Individual and Family Services", "62", "Health Care and Social Assistance"),
    ("624210", "Community Food Services", "62", "Health Care and Social Assistance"),
    ("624221", "Temporary Shelters", "62", "Health Care and Social Assistance"),
    ("624229", "Other Community Housing Services", "62", "Health Care and Social Assistance"),
    ("624230", "Emergency and Other Relief Services", "62", "Health Care and Social Assistance"),
    ("624310", "Vocational Rehabilitation Services", "62", "Health Care and Social Assistance"),
    ("624410", "Child Day Care Services", "62", "Health Care and Social Assistance"),
    
    # Health Care (62)
    ("621", "Ambulatory Health Care Services", "62", "Health Care and Social Assistance"),
    ("621111", "Offices of Physicians (except Mental Health)", "62", "Health Care and Social Assistance"),
    ("621112", "Offices of Physicians, Mental Health Specialists", "62", "Health Care and Social Assistance"),
    ("621210", "Offices of Dentists", "62", "Health Care and Social Assistance"),
    ("621310", "Offices of Chiropractors", "62", "Health Care and Social Assistance"),
    ("621320", "Offices of Optometrists", "62", "Health Care and Social Assistance"),
    ("621330", "Offices of Mental Health Practitioners", "62", "Health Care and Social Assistance"),
    ("621340", "Offices of Physical, Occupational and Speech Therapists", "62", "Health Care and Social Assistance"),
    ("621391", "Offices of Podiatrists", "62", "Health Care and Social Assistance"),
    ("621399", "Offices of All Other Miscellaneous Health Practitioners", "62", "Health Care and Social Assistance"),
    ("621410", "Family Planning Centers", "62", "Health Care and Social Assistance"),
    ("621420", "Outpatient Mental Health and Substance Abuse Centers", "62", "Health Care and Social Assistance"),
    ("621491", "HMO Medical Centers", "62", "Health Care and Social Assistance"),
    ("621492", "Kidney Dialysis Centers", "62", "Health Care and Social Assistance"),
    ("621493", "Freestanding Ambulatory Surgical and Emergency Centers", "62", "Health Care and Social Assistance"),
    ("621498", "All Other Outpatient Care Centers", "62", "Health Care and Social Assistance"),
    ("621511", "Medical Laboratories", "62", "Health Care and Social Assistance"),
    ("621512", "Diagnostic Imaging Centers", "62", "Health Care and Social Assistance"),
    ("621610", "Home Health Care Services", "62", "Health Care and Social Assistance"),
    ("621910", "Ambulance Services", "62", "Health Care and Social Assistance"),
    ("621991", "Blood and Organ Banks", "62", "Health Care and Social Assistance"),
    ("621999", "All Other Miscellaneous Ambulatory Health Care Services", "62", "Health Care and Social Assistance"),
    ("622", "Hospitals", "62", "Health Care and Social Assistance"),
    ("622110", "General Medical and Surgical Hospitals", "62", "Health Care and Social Assistance"),
    ("622210", "Psychiatric and Substance Abuse Hospitals", "62", "Health Care and Social Assistance"),
    ("622310", "Specialty Hospitals", "62", "Health Care and Social Assistance"),
    ("623", "Nursing and Residential Care Facilities", "62", "Health Care and Social Assistance"),
    ("623110", "Nursing Care Facilities (Skilled Nursing Facilities)", "62", "Health Care and Social Assistance"),
    ("623210", "Residential Intellectual and Developmental Disability Facilities", "62", "Health Care and Social Assistance"),
    ("623220", "Residential Mental Health and Substance Abuse Facilities", "62", "Health Care and Social Assistance"),
    ("623311", "Continuing Care Retirement Communities", "62", "Health Care and Social Assistance"),
    ("623312", "Assisted Living Facilities for the Elderly", "62", "Health Care and Social Assistance"),
    ("623990", "Other Residential Care Facilities", "62", "Health Care and Social Assistance"),
    
    # Construction (23)
    ("23", "Construction", "23", "Construction"),
    ("236", "Construction of Buildings", "23", "Construction"),
    ("236115", "New Single-Family Housing Construction", "23", "Construction"),
    ("236116", "New Multifamily Housing Construction", "23", "Construction"),
    ("236117", "New Housing For-Sale Builders", "23", "Construction"),
    ("236118", "Residential Remodelers", "23", "Construction"),
    ("236210", "Industrial Building Construction", "23", "Construction"),
    ("236220", "Commercial and Institutional Building Construction", "23", "Construction"),
    ("237", "Heavy and Civil Engineering Construction", "23", "Construction"),
    ("237110", "Water and Sewer Line and Related Structures Construction", "23", "Construction"),
    ("237120", "Oil and Gas Pipeline and Related Structures Construction", "23", "Construction"),
    ("237130", "Power and Communication Line and Related Structures Construction", "23", "Construction"),
    ("237210", "Land Subdivision", "23", "Construction"),
    ("237310", "Highway, Street, and Bridge Construction", "23", "Construction"),
    ("237990", "Other Heavy and Civil Engineering Construction", "23", "Construction"),
    ("238", "Specialty Trade Contractors", "23", "Construction"),
    ("238110", "Poured Concrete Foundation and Structure Contractors", "23", "Construction"),
    ("238120", "Structural Steel and Precast Concrete Contractors", "23", "Construction"),
    ("238130", "Framing Contractors", "23", "Construction"),
    ("238140", "Masonry Contractors", "23", "Construction"),
    ("238150", "Glass and Glazing Contractors", "23", "Construction"),
    ("238160", "Roofing Contractors", "23", "Construction"),
    ("238170", "Siding Contractors", "23", "Construction"),
    ("238190", "Other Foundation, Structure, and Building Exterior Contractors", "23", "Construction"),
    ("238210", "Electrical Contractors and Other Wiring Installation Contractors", "23", "Construction"),
    ("238220", "Plumbing, Heating, and Air-Conditioning Contractors", "23", "Construction"),
    ("238290", "Other Building Equipment Contractors", "23", "Construction"),
    ("238310", "Drywall and Insulation Contractors", "23", "Construction"),
    ("238320", "Painting and Wall Covering Contractors", "23", "Construction"),
    ("238330", "Flooring Contractors", "23", "Construction"),
    ("238340", "Tile and Terrazzo Contractors", "23", "Construction"),
    ("238350", "Finish Carpentry Contractors", "23", "Construction"),
    ("238390", "Other Building Finishing Contractors", "23", "Construction"),
    ("238910", "Site Preparation Contractors", "23", "Construction"),
    ("238990", "All Other Specialty Trade Contractors", "23", "Construction"),
    
    # Food Services (72)
    ("72", "Accommodation and Food Services", "72", "Accommodation and Food Services"),
    ("722", "Food Services and Drinking Places", "72", "Accommodation and Food Services"),
    ("722310", "Food Service Contractors", "72", "Accommodation and Food Services"),
    ("722320", "Caterers", "72", "Accommodation and Food Services"),
    ("722330", "Mobile Food Services", "72", "Accommodation and Food Services"),
    ("722410", "Drinking Places (Alcoholic Beverages)", "72", "Accommodation and Food Services"),
    ("722511", "Full-Service Restaurants", "72", "Accommodation and Food Services"),
    ("722513", "Limited-Service Restaurants", "72", "Accommodation and Food Services"),
    ("722514", "Cafeterias, Grill Buffets, and Buffets", "72", "Accommodation and Food Services"),
    ("722515", "Snack and Nonalcoholic Beverage Bars", "72", "Accommodation and Food Services"),
    ("721", "Accommodation", "72", "Accommodation and Food Services"),
    ("721110", "Hotels (except Casino Hotels) and Motels", "72", "Accommodation and Food Services"),
    ("721120", "Casino Hotels", "72", "Accommodation and Food Services"),
    ("721191", "Bed-and-Breakfast Inns", "72", "Accommodation and Food Services"),
    ("721199", "All Other Traveler Accommodation", "72", "Accommodation and Food Services"),
    ("721211", "RV (Recreational Vehicle) Parks and Campgrounds", "72", "Accommodation and Food Services"),
    ("721214", "Recreational and Vacation Camps", "72", "Accommodation and Food Services"),
    ("721310", "Rooming and Boarding Houses, Dormitories, and Workers' Camps", "72", "Accommodation and Food Services"),
    
    # Retail Trade (44-45)
    ("44", "Retail Trade", "44", "Retail Trade"),
    ("441", "Motor Vehicle and Parts Dealers", "44", "Retail Trade"),
    ("441110", "New Car Dealers", "44", "Retail Trade"),
    ("441120", "Used Car Dealers", "44", "Retail Trade"),
    ("441210", "Recreational Vehicle Dealers", "44", "Retail Trade"),
    ("441222", "Boat Dealers", "44", "Retail Trade"),
    ("441228", "Motorcycle, ATV, and All Other Motor Vehicle Dealers", "44", "Retail Trade"),
    ("441310", "Automotive Parts and Accessories Retailers", "44", "Retail Trade"),
    ("441320", "Tire Dealers", "44", "Retail Trade"),
    ("445", "Food and Beverage Retailers", "44", "Retail Trade"),
    ("445110", "Supermarkets and Other Grocery Retailers", "44", "Retail Trade"),
    ("445131", "Convenience Retailers", "44", "Retail Trade"),
    ("445132", "Vending Machine Operators", "44", "Retail Trade"),
    ("445230", "Fruit and Vegetable Retailers", "44", "Retail Trade"),
    ("445240", "Meat Retailers", "44", "Retail Trade"),
    ("445250", "Fish and Seafood Retailers", "44", "Retail Trade"),
    ("445291", "Baked Goods Retailers", "44", "Retail Trade"),
    ("445292", "Confectionery and Nut Retailers", "44", "Retail Trade"),
    ("445298", "All Other Specialty Food Retailers", "44", "Retail Trade"),
    ("445310", "Beer, Wine, and Liquor Retailers", "44", "Retail Trade"),
    ("447", "Gasoline Stations and Fuel Dealers", "44", "Retail Trade"),
    ("447110", "Gasoline Stations with Convenience Stores", "44", "Retail Trade"),
    ("447190", "Other Gasoline Stations", "44", "Retail Trade"),
    
    # Professional Services (54)
    ("54", "Professional, Scientific, and Technical Services", "54", "Professional, Scientific, and Technical Services"),
    ("541", "Professional, Scientific, and Technical Services", "54", "Professional, Scientific, and Technical Services"),
    ("541110", "Offices of Lawyers", "54", "Professional, Scientific, and Technical Services"),
    ("541191", "Title Abstract and Settlement Offices", "54", "Professional, Scientific, and Technical Services"),
    ("541199", "All Other Legal Services", "54", "Professional, Scientific, and Technical Services"),
    ("541211", "Offices of Certified Public Accountants", "54", "Professional, Scientific, and Technical Services"),
    ("541213", "Tax Preparation Services", "54", "Professional, Scientific, and Technical Services"),
    ("541214", "Payroll Services", "54", "Professional, Scientific, and Technical Services"),
    ("541219", "Other Accounting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541310", "Architectural Services", "54", "Professional, Scientific, and Technical Services"),
    ("541320", "Landscape Architectural Services", "54", "Professional, Scientific, and Technical Services"),
    ("541330", "Engineering Services", "54", "Professional, Scientific, and Technical Services"),
    ("541340", "Drafting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541350", "Building Inspection Services", "54", "Professional, Scientific, and Technical Services"),
    ("541360", "Geophysical Surveying and Mapping Services", "54", "Professional, Scientific, and Technical Services"),
    ("541370", "Surveying and Mapping Services", "54", "Professional, Scientific, and Technical Services"),
    ("541380", "Testing Laboratories and Services", "54", "Professional, Scientific, and Technical Services"),
    ("541511", "Custom Computer Programming Services", "54", "Professional, Scientific, and Technical Services"),
    ("541512", "Computer Systems Design Services", "54", "Professional, Scientific, and Technical Services"),
    ("541513", "Computer Facilities Management Services", "54", "Professional, Scientific, and Technical Services"),
    ("541519", "Other Computer Related Services", "54", "Professional, Scientific, and Technical Services"),
    ("541611", "Administrative Management and General Management Consulting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541612", "Human Resources Consulting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541613", "Marketing Consulting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541614", "Process, Physical Distribution, and Logistics Consulting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541618", "Other Management Consulting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541620", "Environmental Consulting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541690", "Other Scientific and Technical Consulting Services", "54", "Professional, Scientific, and Technical Services"),
    ("541713", "Research and Development in Nanotechnology", "54", "Professional, Scientific, and Technical Services"),
    ("541714", "Research and Development in Biotechnology", "54", "Professional, Scientific, and Technical Services"),
    ("541715", "Research and Development in the Physical, Engineering, and Life Sciences", "54", "Professional, Scientific, and Technical Services"),
    ("541720", "Research and Development in the Social Sciences and Humanities", "54", "Professional, Scientific, and Technical Services"),
    ("541810", "Advertising Agencies", "54", "Professional, Scientific, and Technical Services"),
    ("541820", "Public Relations Agencies", "54", "Professional, Scientific, and Technical Services"),
    ("541830", "Media Buying Agencies", "54", "Professional, Scientific, and Technical Services"),
    ("541840", "Media Representatives", "54", "Professional, Scientific, and Technical Services"),
    ("541850", "Indoor and Outdoor Display Advertising", "54", "Professional, Scientific, and Technical Services"),
    ("541860", "Direct Mail Advertising", "54", "Professional, Scientific, and Technical Services"),
    ("541870", "Advertising Material Distribution Services", "54", "Professional, Scientific, and Technical Services"),
    ("541890", "Other Services Related to Advertising", "54", "Professional, Scientific, and Technical Services"),
    ("541910", "Marketing Research and Public Opinion Polling", "54", "Professional, Scientific, and Technical Services"),
    ("541921", "Photography Studios, Portrait", "54", "Professional, Scientific, and Technical Services"),
    ("541922", "Commercial Photography", "54", "Professional, Scientific, and Technical Services"),
    ("541930", "Translation and Interpretation Services", "54", "Professional, Scientific, and Technical Services"),
    ("541940", "Veterinary Services", "54", "Professional, Scientific, and Technical Services"),
    ("541990", "All Other Professional, Scientific, and Technical Services", "54", "Professional, Scientific, and Technical Services"),
    
    # Education (61)
    ("61", "Educational Services", "61", "Educational Services"),
    ("611", "Educational Services", "61", "Educational Services"),
    ("611110", "Elementary and Secondary Schools", "61", "Educational Services"),
    ("611210", "Junior Colleges", "61", "Educational Services"),
    ("611310", "Colleges, Universities, and Professional Schools", "61", "Educational Services"),
    ("611410", "Business and Secretarial Schools", "61", "Educational Services"),
    ("611420", "Computer Training", "61", "Educational Services"),
    ("611430", "Professional and Management Development Training", "61", "Educational Services"),
    ("611511", "Cosmetology and Barber Schools", "61", "Educational Services"),
    ("611512", "Flight Training", "61", "Educational Services"),
    ("611513", "Apprenticeship Training", "61", "Educational Services"),
    ("611519", "Other Technical and Trade Schools", "61", "Educational Services"),
    ("611610", "Fine Arts Schools", "61", "Educational Services"),
    ("611620", "Sports and Recreation Instruction", "61", "Educational Services"),
    ("611630", "Language Schools", "61", "Educational Services"),
    ("611691", "Exam Preparation and Tutoring", "61", "Educational Services"),
    ("611692", "Automobile Driving Schools", "61", "Educational Services"),
    ("611699", "All Other Miscellaneous Schools and Instruction", "61", "Educational Services"),
    ("611710", "Educational Support Services", "61", "Educational Services"),
    
    # Manufacturing (31-33)
    ("31", "Manufacturing", "31", "Manufacturing"),
    ("311", "Food Manufacturing", "31", "Manufacturing"),
    ("312", "Beverage and Tobacco Product Manufacturing", "31", "Manufacturing"),
    ("313", "Textile Mills", "31", "Manufacturing"),
    ("314", "Textile Product Mills", "31", "Manufacturing"),
    ("315", "Apparel Manufacturing", "31", "Manufacturing"),
    ("316", "Leather and Allied Product Manufacturing", "31", "Manufacturing"),
    ("321", "Wood Product Manufacturing", "31", "Manufacturing"),
    ("322", "Paper Manufacturing", "31", "Manufacturing"),
    ("323", "Printing and Related Support Activities", "31", "Manufacturing"),
    ("324", "Petroleum and Coal Products Manufacturing", "31", "Manufacturing"),
    ("325", "Chemical Manufacturing", "31", "Manufacturing"),
    ("326", "Plastics and Rubber Products Manufacturing", "31", "Manufacturing"),
    ("327", "Nonmetallic Mineral Product Manufacturing", "31", "Manufacturing"),
    ("331", "Primary Metal Manufacturing", "31", "Manufacturing"),
    ("332", "Fabricated Metal Product Manufacturing", "31", "Manufacturing"),
    ("333", "Machinery Manufacturing", "31", "Manufacturing"),
    ("334", "Computer and Electronic Product Manufacturing", "31", "Manufacturing"),
    ("335", "Electrical Equipment, Appliance, and Component Manufacturing", "31", "Manufacturing"),
    ("336", "Transportation Equipment Manufacturing", "31", "Manufacturing"),
    ("337", "Furniture and Related Product Manufacturing", "31", "Manufacturing"),
    ("339", "Miscellaneous Manufacturing", "31", "Manufacturing"),
    
    # Agriculture (11)
    ("11", "Agriculture, Forestry, Fishing and Hunting", "11", "Agriculture, Forestry, Fishing and Hunting"),
    ("111", "Crop Production", "11", "Agriculture, Forestry, Fishing and Hunting"),
    ("112", "Animal Production and Aquaculture", "11", "Agriculture, Forestry, Fishing and Hunting"),
    ("113", "Forestry and Logging", "11", "Agriculture, Forestry, Fishing and Hunting"),
    ("114", "Fishing, Hunting and Trapping", "11", "Agriculture, Forestry, Fishing and Hunting"),
    ("115", "Support Activities for Agriculture and Forestry", "11", "Agriculture, Forestry, Fishing and Hunting"),
    
    # Other Services (81)
    ("81", "Other Services (except Public Administration)", "81", "Other Services"),
    ("811", "Repair and Maintenance", "81", "Other Services"),
    ("811111", "General Automotive Repair", "81", "Other Services"),
    ("811112", "Automotive Exhaust System Repair", "81", "Other Services"),
    ("811113", "Automotive Transmission Repair", "81", "Other Services"),
    ("811118", "Other Automotive Mechanical and Electrical Repair", "81", "Other Services"),
    ("811121", "Automotive Body, Paint, and Interior Repair", "81", "Other Services"),
    ("811122", "Automotive Glass Replacement Shops", "81", "Other Services"),
    ("811191", "Automotive Oil Change and Lubrication Shops", "81", "Other Services"),
    ("811192", "Car Washes", "81", "Other Services"),
    ("811198", "All Other Automotive Repair and Maintenance", "81", "Other Services"),
    ("811210", "Electronic and Precision Equipment Repair and Maintenance", "81", "Other Services"),
    ("811310", "Commercial and Industrial Machinery and Equipment Repair and Maintenance", "81", "Other Services"),
    ("811411", "Home and Garden Equipment Repair and Maintenance", "81", "Other Services"),
    ("811412", "Appliance Repair and Maintenance", "81", "Other Services"),
    ("811420", "Reupholstery and Furniture Repair", "81", "Other Services"),
    ("811430", "Footwear and Leather Goods Repair", "81", "Other Services"),
    ("811490", "Other Personal and Household Goods Repair and Maintenance", "81", "Other Services"),
    ("812", "Personal and Laundry Services", "81", "Other Services"),
    ("812111", "Barber Shops", "81", "Other Services"),
    ("812112", "Beauty Salons", "81", "Other Services"),
    ("812113", "Nail Salons", "81", "Other Services"),
    ("812191", "Diet and Weight Reducing Centers", "81", "Other Services"),
    ("812199", "Other Personal Care Services", "81", "Other Services"),
    ("812210", "Funeral Homes and Funeral Services", "81", "Other Services"),
    ("812220", "Cemeteries and Crematories", "81", "Other Services"),
    ("812310", "Coin-Operated Laundries and Drycleaners", "81", "Other Services"),
    ("812320", "Drycleaning and Laundry Services (except Coin-Operated)", "81", "Other Services"),
    ("812331", "Linen Supply", "81", "Other Services"),
    ("812332", "Industrial Launderers", "81", "Other Services"),
    ("812910", "Pet Care (except Veterinary) Services", "81", "Other Services"),
    ("812921", "Photofinishing Laboratories (except One-Hour)", "81", "Other Services"),
    ("812922", "One-Hour Photofinishing", "81", "Other Services"),
    ("812930", "Parking Lots and Garages", "81", "Other Services"),
    ("812990", "All Other Personal Services", "81", "Other Services"),
    ("813", "Religious, Grantmaking, Civic, Professional Organizations", "81", "Other Services"),
    ("813110", "Religious Organizations", "81", "Other Services"),
    ("813211", "Grantmaking Foundations", "81", "Other Services"),
    ("813212", "Voluntary Health Organizations", "81", "Other Services"),
    ("813219", "Other Grantmaking and Giving Services", "81", "Other Services"),
    ("813311", "Human Rights Organizations", "81", "Other Services"),
    ("813312", "Environment, Conservation and Wildlife Organizations", "81", "Other Services"),
    ("813319", "Other Social Advocacy Organizations", "81", "Other Services"),
    ("813410", "Civic and Social Organizations", "81", "Other Services"),
    ("813910", "Business Associations", "81", "Other Services"),
    ("813920", "Professional Organizations", "81", "Other Services"),
    ("813930", "Labor Unions and Similar Labor Organizations", "81", "Other Services"),
    ("813940", "Political Organizations", "81", "Other Services"),
    ("813990", "Other Similar Organizations", "81", "Other Services"),
]


def main():
    print("=" * 60)
    print("NAICS Code Import")
    print("=" * 60)
    
    init_db()
    
    with get_db_context() as db:
        # Clear existing
        existing = db.query(NaicsCode).count()
        if existing > 0:
            print(f"Clearing {existing} existing NAICS codes...")
            db.query(NaicsCode).delete()
            db.commit()
        
        # Insert all codes
        count = 0
        for code, title, sector, sector_title in NAICS_DATA:
            naics = NaicsCode(
                code=code,
                title=title,
                sector=sector,
                sector_title=sector_title
            )
            db.add(naics)
            count += 1
        
        db.commit()
        print(f"✓ Imported {count} NAICS codes")
        
        # Show some examples
        print("\nSample codes:")
        samples = db.query(NaicsCode).filter(
            NaicsCode.code.in_(["484121", "624410", "722511", "238220"])
        ).all()
        for s in samples:
            print(f"  {s.code}: {s.title}")


if __name__ == "__main__":
    main()
