# Ohio Fraud Tracker - Data Sources

> **Last Updated:** January 1, 2026  
> **Status:** Living document - update as sources are identified or acquired

---

## ✅ Currently Implemented

### 1. USAspending.gov (Federal Awards)
- **What:** Federal grants, contracts, loans, and other financial assistance to Ohio recipients
- **Records:** ~14,000+ awards
- **Acquisition:** Public API - https://api.usaspending.gov
- **Update Frequency:** Can refresh monthly
- **Status:** ✅ Imported and working

### 2. SBA PPP Loans
- **What:** Paycheck Protection Program loans issued during COVID-19
- **Records:** Ohio businesses that received PPP loans
- **Acquisition:** Public dataset from SBA
- **Status:** ✅ Imported and working

### 3. Ohio Checkbook (State Spending)
- **What:** Ohio state government expenditures
- **Acquisition:** https://ohiocheckbook.gov - Public API/bulk download
- **Status:** ✅ Imported and working

---

## 🔴 High Priority - Current News Cycle

### 4. Ohio Childcare Provider Payments (DCY)
- **What:** State-subsidized childcare facility payments, attendance data, provider info
- **Why Critical:** Minnesota fraud scandal has 125M+ views; Ohio lawmakers calling for audits; Columbus has large Somali population like Minneapolis
- **Source Agency:** Ohio Department of Children and Youth (DCY)
- **Acquisition Methods:**
  - [ ] Public records request to DCY for provider payment data
  - [ ] FOIA for federal CCDF (Child Care Development Fund) disbursements
  - [ ] Scrape licensed provider list from: https://childcaresearch.ohio.gov
- **Data Points Needed:**
  - Provider name, address, license number
  - Monthly/annual payment amounts
  - Enrollment vs attendance figures
  - Inspection history
  - Complaints/violations
- **Difficulty:** Medium - May require legal push
- **Timeline:** 2-4 weeks for public records request

### 5. Ohio Medicaid Provider Payments
- **What:** Payments to Medicaid providers (healthcare, home health, mental health services)
- **Why Critical:** AG Yost actively prosecuting Medicaid fraud; home health fraud mentioned in legislative letter
- **Source Agency:** Ohio Department of Medicaid
- **Acquisition Methods:**
  - [ ] CMS Open Payments database (federal): https://openpaymentsdata.cms.gov
  - [ ] Ohio Medicaid provider directory (public)
  - [ ] Public records request for Ohio-specific payment data
- **Cross-reference with:** OIG Exclusion List, AG fraud cases
- **Difficulty:** Medium
- **Timeline:** 2-4 weeks

### 6. Ohio AG Fraud Prosecutions
- **What:** Attorney General Dave Yost's fraud prosecution announcements and case details
- **Why Critical:** Provides confirmed fraud cases to highlight; shows patterns
- **Acquisition Methods:**
  - [ ] Scrape press releases: https://www.ohioattorneygeneral.gov/Media/News-Releases
  - [ ] PACER federal court records for Ohio district
  - [ ] Ohio court records system
- **Data Points:**
  - Defendant names/businesses
  - Fraud amount
  - Program defrauded
  - Case status/outcome
- **Difficulty:** Easy-Medium
- **Timeline:** 1-2 weeks

---

## 🟡 Medium Priority - Strong Fraud Detection Value

### 7. Ohio Secretary of State - Business Registry
- **What:** Business registration status, filing history, registered agents
- **Why Important:** Verify if award recipients are legitimate, active businesses
- **Acquisition Methods:**
  - [ ] Bulk data purchase/public records request
  - [ ] API access (if available)
  - [ ] Scrape business search: https://businesssearch.ohiosos.gov
- **Use Case:** Flag awards to dissolved/inactive businesses
- **Difficulty:** Medium - May require fee or legal request
- **Timeline:** 2-6 weeks

### 8. OIG LEIE (Excluded Providers List)
- **What:** Federal list of individuals/entities excluded from Medicare/Medicaid
- **Why Important:** Any excluded entity receiving federal funds = automatic red flag
- **Acquisition:** Public download: https://oig.hhs.gov/exclusions/exclusions_list.asp
- **Implementation:**
  - [ ] Download LEIE database
  - [ ] Match against recipient names/addresses
  - [ ] Auto-flag any matches
- **Difficulty:** Easy
- **Timeline:** 1 week

### 9. SAM.gov Exclusions
- **What:** System for Award Management - debarred/suspended federal contractors
- **Why Important:** Entities banned from federal contracting still receiving awards
- **Acquisition:** Public API: https://sam.gov/data-services
- **Difficulty:** Easy
- **Timeline:** 1 week

### 10. CMS Nursing Home Compare
- **What:** Nursing home ratings, inspection results, staffing, complaints
- **Why Important:** Cross-reference with Medicaid payments; identify low-quality facilities receiving large payments
- **Acquisition:** Public download: https://data.cms.gov/provider-data
- **Difficulty:** Easy
- **Timeline:** 1 week

### 11. Ohio Home Health Agency Data
- **What:** Licensed home health agencies, inspection results
- **Why Critical:** Specifically mentioned in Ohio legislative audit request
- **Source:** Ohio Department of Health, CMS Home Health Compare
- **Acquisition Methods:**
  - [ ] CMS Home Health Compare dataset
  - [ ] Ohio DOH licensed provider list
  - [ ] Public records for payment data
- **Difficulty:** Medium
- **Timeline:** 2-3 weeks

---

## 🟢 Lower Priority - Long-term Enhancements

### 12. Ohio BWC (Workers' Comp) Fraud Cases
- **What:** Bureau of Workers' Compensation fraud prosecutions
- **Acquisition:** BWC press releases, court records
- **Difficulty:** Easy
- **Timeline:** Ongoing

### 13. Ohio Unemployment Fraud Data
- **What:** ODJFS unemployment fraud cases (significant during COVID)
- **Acquisition:** Public records request, press releases
- **Difficulty:** Medium
- **Timeline:** 2-4 weeks

### 14. Federal Court Records (PACER)
- **What:** Federal civil/criminal cases in Ohio districts
- **Why Useful:** Find fraud indictments, settlements, judgments
- **Acquisition:** PACER access ($0.10/page, capped at $3/doc)
- **Difficulty:** Medium (requires account, fees)
- **Timeline:** Ongoing

### 15. Ohio State Court Records
- **What:** State-level fraud prosecutions, civil cases
- **Acquisition:** County court systems vary; some online
- **Difficulty:** Hard (fragmented across 88 counties)
- **Timeline:** Long-term

### 16. IRS Exempt Organizations (990s)
- **What:** Nonprofit tax returns showing revenue, expenses, executive compensation
- **Why Useful:** Cross-reference nonprofit grant recipients with their reported finances
- **Acquisition:** IRS 990 database, ProPublica Nonprofit Explorer API
- **Difficulty:** Easy
- **Timeline:** 2 weeks

### 17. Ohio Lottery Retailers
- **What:** Licensed lottery retailers - sometimes used in fraud schemes
- **Acquisition:** Ohio Lottery Commission
- **Difficulty:** Easy
- **Timeline:** 1 week

### 18. Property Records
- **What:** County auditor property records - verify business addresses
- **Why Useful:** Identify shell companies at residential addresses, vacant lots
- **Acquisition:** County auditor websites (88 counties)
- **Difficulty:** Hard (fragmented)
- **Timeline:** Long-term

### 19. Corporate Ownership (OpenCorporates)
- **What:** Business ownership, related entities, officers
- **Acquisition:** OpenCorporates API (paid for bulk)
- **Difficulty:** Medium (cost)
- **Timeline:** As budget allows

### 20. Political Contribution Data
- **What:** Campaign contributions from award recipients
- **Why Useful:** Identify potential pay-to-play patterns
- **Acquisition:** FEC data, Ohio Secretary of State campaign finance
- **Difficulty:** Easy-Medium
- **Timeline:** 2-3 weeks

---

## 📊 Data Enhancement Sources

### 21. NAICS Code Database
- **What:** Industry classification codes and descriptions
- **Use:** Categorize recipients by industry, identify unusual patterns
- **Acquisition:** Census Bureau, public datasets
- **Status:** Not yet implemented

### 22. ZIP Code Demographics
- **What:** Census data by ZIP code - income, population, etc.
- **Use:** Contextualize awards relative to population
- **Acquisition:** Census API
- **Difficulty:** Easy

### 23. Geocoding Services
- **What:** Convert addresses to lat/long for mapping
- **Use:** Visualize award distribution, identify clusters
- **Acquisition:** Google Maps API, Census Geocoder (free)
- **Difficulty:** Easy

---

## 🔗 Cross-Reference Opportunities

| Source A | Source B | Fraud Signal |
|----------|----------|--------------|
| USAspending | Ohio SOS | Awards to dissolved businesses |
| Medicaid payments | OIG LEIE | Payments to excluded providers |
| Childcare payments | Inspection records | High payments to low-rated facilities |
| Any recipient | Court records | Active fraud cases |
| PPP Loans | Business registry | Loans to fake businesses |
| Grant recipients | 990 data | Nonprofits with suspicious finances |
| Multiple awards | Same address | Shell company networks |

---

## 📝 Acquisition Checklist

### Public Records Request Template Needed For:
- [ ] Ohio DCY - Childcare provider payments
- [ ] Ohio Medicaid - Provider payment details  
- [ ] Ohio SOS - Bulk business data
- [ ] Ohio DOH - Home health provider data

### APIs to Integrate:
- [ ] OIG LEIE download
- [ ] SAM.gov exclusions API
- [ ] CMS Provider Data APIs
- [ ] IRS 990 / ProPublica API

### Scraping Needed:
- [ ] Ohio AG press releases
- [ ] Ohio childcare provider search
- [ ] County property records (prioritize Franklin, Cuyahoga, Hamilton)

---

## 📅 Recommended Implementation Order

**Phase 1 - Launch (Now)**
1. ✅ USAspending, PPP, Ohio Checkbook (done)
2. OIG LEIE exclusion matching (1 week)
3. Ohio AG fraud cases (1 week)

**Phase 2 - Post-Launch (Weeks 2-4)**
4. Ohio Childcare provider data (public records request)
5. Ohio SOS business registry
6. CMS Nursing Home / Home Health data

**Phase 3 - Expansion (Month 2+)**
7. Ohio Medicaid detailed payments
8. Court records integration
9. 990 nonprofit data
10. Geographic analysis tools

---

## 💡 Notes & Ideas

- SomaliScan focuses on childcare + PPP + SBA - we have PPP, should add childcare
- Minnesota fraud involved: childcare, housing services, autism programs, Medicaid
- Columbus has 2nd largest Somali population - same fraud patterns possible
- AG Yost actively prosecuting - good source for confirmed cases
- Consider "tip line" feature for crowdsourced fraud reports

---

*This document should be updated as new sources are identified or data is acquired.*
