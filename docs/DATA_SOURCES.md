# Ohio Fraud Tracker - Data Sources

> **Last Updated:** September 2, 2026  
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

## 🆕 September 2026 Review — What Changed and What Is New

> Research pass done September 2, 2026 (last import work was February 2026). Government hosts were
> not directly reachable from the research environment, so items marked **(unverified)** come from
> search-index snippets or third-party scraper source code and should be confirmed by hand before
> an importer is changed.

### A. Updates to sources already imported

| Source | Status as of Sept 2026 | Action |
|--------|------------------------|--------|
| **USAspending** | FY2026 data flowing. New `POST /api/v2/download/search/` (Apr 2026) consolidates awards/transactions/subawards. New assistance type codes added Feb and Jun 2026. `spending_by_award` now returns HTTP 422 on bad requests. `download/awards` still supported; `keyword` (singular), `subawards` boolean, and `recipient/duns` endpoints deprecated. | Re-run `import_usaspending --resume` for FY2026. Check that award-type enums and error handling tolerate the new codes and 422s. |
| **SBA PPP FOIA** | Still the `*_240930.csv` cut (Oct 2024). No 2025/2026 release found **(unverified)**. | Nothing to import. Poll the CKAN API (`/api/3/action/package_show?id=ppp-foia`) for a new file. |
| **HHS OIG LEIE** | `UPDATED.csv` URL and 18-column layout unchanged. Latest is the July 2026 update. Monthly supplements at `downloadables/YYYY/YYMMexcl.csv` and `YYMMrein.csv`. | Re-run `import_leie` monthly. Validate header row on each pull. |
| **Ohio Checkbook** | Site unchanged so far. Monthly CSV export path **(unverified)**. DataOhio offers a bulk state-only download. HB 413 (mandatory local-government participation) passed the House May 2026, pending in Senate. | Download Jan–Aug 2026 monthly files and import. Consider DataOhio bulk file as a more stable source. |
| **Ohio SOS business filings** | SOS redesigned its site and launched a Business Data Transparency Dashboard (Nov/Dec 2025, `data.ohiosos.gov`). Download page now describes **free monthly bulk reports** (second Saturday of each month): new filings, subsequent filings, dissolved/debarred lists **(unverified)**. Weekly `WI####R` files may be discontinued. | Verify the new monthly file names and columns; adjust `import_ohio_sos` if headers changed. The local `data/ohio-sos/*.txt` files date from Nov 2025. |
| **Ohio SOS campaign finance** | Bulk downloads now reached via `data.ohiosos.gov/portal/campaign-finance`. 2023–2025 filings exist (2025 annual reports were due Jan 2026). Whether yearly bulk files for 2023–2026 are posted is **(unverified)**. | `import_campaign_finance` hard-codes `DEFAULT_END_YEAR = 2022`; bump it once the newer files are confirmed. |
| **ProPublica 990** | No change found. | None. |

### B. New Ohio state sources (ranked)

1. **Ohio Medicaid Provider Exclusion & Suspension List (ODM)** — HIGH value, EASY.
   - Page: https://medicaid.ohio.gov/resources-for-providers/enrollment-and-support/provider-enrollment/provider-exclusion-and-suspension-list
   - File: `https://medicaid.ohio.gov/static/Providers/Enrollment+and+Support/ExclusionSuspensionList.xlsx` **(unverified path)**. Two sheets (Individuals, Organizations). Columns per OpenSanctions crawler: `npi, provider_type, provider_id, action_date, status, date_added, last/first/middle name, dob, organization_name, address, city, state, zip`. Updated ~1st and 15th. ~2,000 active entries.
   - Also: June 4, 2026 list of 49 (later 57) home health providers whose payments were suspended, released with provider IDs (https://medicaid.ohio.gov/news/press-release/ohio-medicaid-initiates-provider-suspensions).
   - Signal: state-only exclusions not in LEIE; join to Checkbook payees, SOS officers, LEIE/NPPES by NPI. Fits the existing `ExcludedEntity` model with a `source` discriminator.
2. **Auditor of State Findings for Recovery (ORC 9.24)** — HIGH value, EASY.
   - Search: https://ffr.ohioauditor.gov/ ; export: https://ffr.ohioauditor.gov/Results/Download **(format unverified)**.
   - Fields: person/entity name, amount, audited entity, report date, resolution status. Findings since 2001. Resolved findings removed quarterly.
   - Signal: entities on this list are legally barred from state contracts; match against Checkbook vendors, USAspending/PPP recipients, SOS officers.
3. **DataOhio "State of Ohio Licensure – Individual" (eLicense bulk)** — HIGH value, EASY but large.
   - https://data.ohio.gov/wps/portal/gov/data/view/state-of-ohio-licensure — daily CSV, all 24 eLicense boards. Columns include license number, board, type, name, status, issue/expiration dates, address **(unverified)**. Disciplinary flag presence unknown.
   - Signal: lapsed/revoked licenses among Medicaid-billing home health, counseling, and nursing providers.
   - Note: DataOhio is IBM WebSphere Portal, not CKAN/Socrata. No REST API; bulk "Export Data" only.
4. **Debarment lists** — MEDIUM value, EASY (small PDFs).
   - SOS prevailing-wage debarments: https://www.ohiosos.gov/assets/debarred-contractor-list.pdf
   - DAS procurement debarments (linked from https://ofcc.ohio.gov/project-resources/debarments) and ODOT debarred contractors (under transportation.ohio.gov/working/contracts). Exact file URLs **(unverified)**.
5. **Economic development incentives** — MEDIUM-HIGH value, MEDIUM effort (PDF tables).
   - Ohio Tax Credit Authority monthly minutes (per-project company, jobs, payroll, credit) under `dam.assets.ohio.gov/.../development.ohio.gov/business/stateincentives/`.
   - AOS annual Department of Development compliance AUP (Dec 2025: 36 of 55 JCTC recipients non-compliant): https://ohioauditor.gov/auditsearch/Reports/2025/Ohio_Department_of_Development_25_Franklin_AUP_FINAL.pdf
   - DataOhio `department-of-development-tax-incentives` dataset **(contents unverified)**.
6. **Controlling Board approved requests** — MEDIUM, scrape. https://ecb.ohio.gov/Public/Search.aspx (search by supplier, request type such as competitive-bid waivers).
7. **Ohio Inspector General reports** — MEDIUM, PDF. Yearly index e.g. https://watchdog.ohio.gov/investigations/84-2026-investigations ; PDFs at `dam.assets.ohio.gov/image/upload/watchdog.ohio.gov/Investigations/2026/<case>/<case>.pdf`.
8. **Child care (DCY)** — HIGH interest, HARD.
   - https://childcaresearch.ohio.gov is lookup-only; inspection PDFs at `/pdf/<program#>_<YYYY-MM-DD>_<TYPE>.pdf`. Two open-source scrapers exist on GitHub (`Ryan-Koch/child-care-provider-scraper`, `Will-Blanton/ODJFS-Licensing-Reports-Webscraper`). ~8,000 licensed programs.
   - PFCC payments by provider: no public dataset (~$969M/yr, ~5,200 providers). Route: records request to DCY or https://data.jfs.ohio.gov data-request workflow. ABC6 obtained per-provider overpayment records via records request in 2026, so the data is releasable.
   - 2026 context: DCY 400-provider integrity review (10 agreements terminated, ~$1M overpayments); HB 647/649 passed House June 2026.
9. **Ohio AG** — MFCU press releases (monthly indictment waves in 2026) at https://www.ohioattorneygeneral.gov/media/news-releases (no first-party RSS confirmed). Charitable registry https://charitable.ohioago.gov (search only; bulk needs records request).
10. **Lower value / aggregate only**: BWC SID annual report, ODJFS unemployment fraud totals, Ohio Ethics Commission, Ohio Fraud Reporting System (confidential; aggregate counts only).

### C. New federal sources (ranked)

1. **Federal Audit Clearinghouse (FAC)** — HIGHEST value, EASY.
   - API: https://api.fac.gov/ (PostgREST). Views: `general`, `findings`, `findings_text`, `federal_awards`, `corrective_action_plans`, `passthrough`, `additional_ueis`, `additional_eins`. Free api.data.gov key in `X-Api-Key`; ~1,000 req/hour; 20,000 rows/request max.
   - Ohio pull: `GET /general?auditee_state=eq.OH&audit_year=eq.2025`, then join `findings` and `federal_awards` on `report_id`. Join to recipients on `auditee_uei` / `auditee_ein`.
   - Signal: material weaknesses, questioned costs, repeat findings, going-concern flags, modified opinions, and grantees that should have filed and did not.
2. **SAM.gov exclusions (daily public extract)** — HIGH value, EASY. Already planned in `docs/sam-gov-integration-plan.md`; use the extract, not the API (10 req/day without a SAM role).
   - List files: `https://sam.gov/api/prod/fileextractservices/v1/api/listfiles?random=<ms>&domain=Exclusions/Public%20V2&privacy=Public` then download `.../v1/api/download/<key>`. File `SAM_Exclusions_Public_V2_Extract_YYDDD.ZIP`. Columns include `Classification, Name, Excluding Agency, Exclusion Program, Exclusion Type, Unique Entity ID, CAGE, NPI, Address, City, State, Zip, Active Date, Termination Date, Record Status, SAM Number`.
3. **IRS tax-exempt bulk data** — MEDIUM value, VERY EASY.
   - EO BMF Ohio file: https://www.irs.gov/pub/irs-soi/eo_oh.csv (monthly).
   - Auto-revocation list: https://apps.irs.gov/pub/epostcard/data-download-revocation.zip (pipe-delimited, monthly).
   - 990 e-file XML index: `https://apps.irs.gov/pub/epostcard/990/xml/<YEAR>/index_<YEAR>.csv`.
   - Signal: grantee with revoked exemption, no BMF record, or ruling date after award.
4. **USAspending subawards and contracts** — MEDIUM-HIGH, trivial to add to the existing pipeline.
   - `POST /api/v2/bulk_download/awards/` with `sub_award_types: ["grant","procurement"]` and `recipient_locations: [{country:"USA", state:"OH"}]`. FSRS retired March 2025; subawards now come via SAM.gov. Dedupe on subaward number + prime award.
   - Current importer defaults to grants and loans only; contracts are one flag away.
5. **Treasury SLFRF (ARPA) public reporting** — HIGH value, MEDIUM effort (Excel, no API). https://home.treasury.gov/policy-issues/coronavirus/assistance-for-state-local-and-tribal-governments/state-and-local-fiscal-recovery-funds/public-data — Feb 2026 release covers through Dec 31, 2025. Project- and subrecipient-level rows for Ohio state, counties, cities.
6. **NPPES + CMS provider datasets** — HIGH for health fraud, LARGER effort.
   - NPPES monthly full file (V2, ~1.1 GB zip; V1 discontinued Mar 2026). Filter to Ohio practice location. NPI is the join key across LEIE, SAM, ODM exclusions.
   - data.cms.gov API pattern: `https://data.cms.gov/data-api/v1/dataset/{uuid}/data?size=5000&filter[condition][path]=STATE&filter[condition][value]=OH` (no key). Datasets: Physician & Other Practitioners, Part D Prescribers, HHA, Hospice, DMEPOS, Revalidation list. Care Compare via `https://data.cms.gov/provider-data/api/1/`. Open Payments PY2025 published June 2026. Preclusion list is not public.
7. **SBA pandemic FOIA one-time loads**: RRF (`rrf_foia.csv`), SVOG (xlsx, July 2022), COVID EIDL (only through Dec 2020; later EIDL is in USAspending already), 7(a)/504 quarterly FOIA with charge-off status.
8. **FEMA OpenFEMA** — LOW-MEDIUM, easiest API. `https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails?$filter=state eq 'OH'`.
9. **CourtListener/RECAP** — rate limits cut May 2026 (free: 5/min, 50/hr, 125/day). Use quarterly bulk CSVs at `https://storage.courtlistener.com/bulk-data/`. DOJ press pages: https://www.justice.gov/usao-ndoh/pr and /usao-sdoh/pr.
10. **DOGE API** (`https://api.doge.gov/savings/grants|contracts`) — terminated Ohio grants/contracts only; updates stopped Jan 2026. **Fraud.gov ledger** (Aug 2026) lists Ohio enforcement actions. Oversight.gov and PaymentAccuracy.gov are aggregate or scrape-only.

### D. 2026 Ohio news cycle (what to prioritize)

- **Medicaid home health / HCBS waiver fraud in Franklin County** dominates: AG MFCU indictment waves Feb, Apr, May, Jun, Jul, Aug 2026; ODM suspended 49–57 providers June 4; EO 2026-01D and 2026-02D; SB 315 "Ohio Medicaid Program Integrity and Fraud Prevention Act" signed July 7, 2026; U.S. House Oversight hearing June 3 (Auditor Faber: 56% of EVV services, $1.1B of $2B, unmatched). CMS six-month home health/hospice enrollment moratorium targeting Ohio (May 14 – Nov 14, 2026).
- **Publicly funded child care** (Jan–Jun): DCY 400-provider review, HB 647/649, Auditor fraud-tip portal (https://ohioauditor.gov/fraud/), no criminal charges yet.
- **Children's behavioral health**: S.D. Ohio June 4 indictment, 4 people incl. 2 ODJFS employees, >$30M.
- **ODJFS unemployment insider fraud**: Ohio IG Aug 2026 report, 3 ex-contractors, ~$3.28M.
- **SNAP retailer fraud**: 19 Ohio retailers sanctioned June 2026.
- AG Yost resigned June 7, 2026; Andy Wilson appointed AG through the Nov 3 election.
- Comparable trackers: https://minnesotafraudtracker.com/ and the White House Fraud.gov ledger.

### E. Recommended implementation order (Sept 2026)

1. Refresh existing imports: USAspending FY2026, Checkbook Jan–Aug 2026, LEIE, verify new SOS monthly files, bump campaign finance end year.
2. ODM Exclusion & Suspension List + June 2026 suspended-provider list (reuse LEIE matching).
3. SAM.gov daily exclusion extract (plan already written).
4. Federal Audit Clearinghouse findings for Ohio auditees.
5. Auditor of State Findings for Recovery export.
6. IRS BMF + revocation list (Ohio file).
7. USAspending subawards and contracts.
8. DataOhio licensure CSV; debarment PDFs.
9. NPPES + CMS utilization (NPI-keyed join across all exclusion lists).
10. Records requests: DCY PFCC payments by provider, ODM provider-level payments, bulk disciplinary orders.

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
  - [x] Download LEIE database
  - [x] Match against recipient names/addresses
  - [x] Auto-flag any matches
- **Script:** `api/scripts/import_leie.py`
- **Status:** ✅ READY TO RUN
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
