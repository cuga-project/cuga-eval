"""Playbooks and Tool Enrichments for Oak Health Insurance tasks.

This file contains policy definitions for medium and hard difficulty tasks
based on the test cases in oak_data.json.
"""

from typing import List

from cuga.backend.cuga_graph.policy.models import (
    AlwaysTrigger,
    NaturalLanguageTrigger,
    Playbook,
    PolicyType,
    ToolGuide,
)

# ===== PLAYBOOKS =====


def create_claims_eob_pdf_playbook() -> Playbook:
    """Playbook for retrieving approved claims with EOB PDFs."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-claims-eob-pdf",
        name="Get Approved Claims with EOB PDFs",
        description="Guide for retrieving approved claims and their EOB PDF documents",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "show my last approved claims and share the URL of any EOB PDF",
                    "download EOB PDF for approved claims",
                    "show my last 3 approved claims and share the URL of any EOB PDF",
                    "approved claims with EOB PDF",
                    "get EOB PDF for approved claims",
                    "get the EOB PDF document URL for each approved claim",
                ],
                target="intent",
                threshold=0.95,
            ),
        ],
        markdown_content="""# Get Approved Claims with EOB PDFs

## Overview
Retrieve the member's approved claims and obtain the EOB (Explanation of Benefits) PDF documents for each approved claim.

## Steps

### Step 1: Retrieve and Filter Claims
1. Retrieve all claims for the member
2. Filter the results to only include claims with `classification.status.identifier == "APRVD"` (Approved)
3. Sort by start date (descending) to get the most recent first
4. Limit to the requested number (typically 3)

**Expected Outcome**: List of approved claims with claim IDs and unique identifiers

### Step 2: Obtain EOB PDFs
1. For each approved claim from Step 1, use the claim's `identifiers.uniqueId`
2. Retrieve the EOB PDF document for each approved claim
3. Extract the EOB PDF URLs from `explanations[].documentUrl` in the response

**Expected Outcome**: EOB PDF URLs for each approved claim

### Step 3: Format Response
1. Combine claim information with EOB PDF URLs
2. Present in a clear format showing:
   - Claim ID (`identifiers.displayId`)
   - EOB PDF URL (`explanations[].documentUrl`, if available)

**Expected Outcome**: Formatted response with claim IDs and EOB PDF URLs
""",
        priority=10,
        enabled=True,
    )


def create_find_care_providers_playbook() -> Playbook:
    """Playbook for finding care providers (MRI, PCP, surgeons, etc.)."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-find-care-providers",
        name="Find Care Providers",
        description="Guide for finding in-network care providers near the member",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "find care providers near me",
                    "find doctors nearby",
                    "find in-network providers",
                    "find primary care doctors",
                    "find MRI providers",
                    "find knee surgeons",
                    "find me all primary care doctors near me",
                    "find in-network care providers near me for an MRI scan",
                    "find all primary care doctors near me that accept new patients",
                    "find all Spanish speaking primary care doctors near me",
                ],
                target="intent",
                threshold=0.7,
            ),
        ],
        markdown_content="""# Find Care Providers

## Overview
Find in-network care providers based on specialty, location, and other criteria. The member must have location information and active coverage.

**CRITICAL - Location Format**: Pass `stateCode` and `zipCode` as **direct kwargs** (query parameters). Example call:
```python
find_care_suggestions(search_text="mri", brand_code="ACME", stateCode="NY", zipCode="11211", memberId="121231234")
```

## Steps

### Step 1: Retrieve Active Coverage Information
1. Retrieve the member's active coverage information
2. Extract from the **active** eligibility entry (status `"A"`):
   - `contract_uid` ← `eligibility[i].identifiers.contractUniqueId`
   - `brand_code` ← `eligibility[i].brand.identifier`

**Expected Outcome**: Contract identifier and brand code needed for provider search

### Step 2: Get Care Suggestions (MANDATORY - Do NOT Skip)

**ALWAYS** call `find_care_suggestions` before calling `find_care_specialty`.

Call parameters (all as kwargs):
- `search_text`: a **short keyword** distilled from the user's query — NOT the full sentence.
  Use exactly: `"mri"`, `"primary care"`, `"knee surgery"`, or `"radiology"`.
  Example: for "Find in-network care providers near me for an MRI scan" → use `"mri"`.
- `brand_code`: from Step 1
- `stateCode`: from user context (e.g., `"NY"`)
- `zipCode`: from user context (e.g., `"11211"`)
- `memberId`: the member's ID

**Extract these three values from `suggestionList[0]` in the response:**

1. **`specialty_category_codes`** → read `suggestionList[0].criteria.specialtyCategoryList`, collect every `.identifier` into a list.
   - Example response field: `[{"identifier": "75", "label": "Imaging Centers"}]` → extract `["75"]`
   - Fallback if empty: `["75"]` for MRI, `["25"]` for primary care, `["220"]` for knee surgery. Valid codes: `"25"`, `"75"`, `"220"`, `"231"`.

2. **`taxonomy_codes`** → read `suggestionList[0].criteria.taxonomyList`, collect every `.code` into a list.
   - Example response field: `[{"code": "261QR0200X", ...}]` → extract `["261QR0200X"]`
   - If the list is empty, use `None` — **never pass an empty list `[]`**.

3. **`distance`** → read `suggestionList[0].dplQueryParams.distance` as a string.
   - If missing, default to `"20"`.

**Expected Outcome**: `specialty_category_codes`, `taxonomy_codes`, and `distance` ready for Step 3

### Step 3: Find Providers by Specialty
Call `find_care_specialty` with (all as kwargs):
- `contract_uid`: from Step 1
- `brand_code`: from Step 1
- `specialty_category_codes`: list from Step 2
- `taxonomy_codes` (optional): from Step 2 — omit entirely if `None`
- `distance`: from Step 2 `dplQueryParams.distance`
- `page_index`: start at `0`; `size`: `5`
- `stateCode`: from user context (e.g., `"NY"`)
- `zipCode`: from user context (e.g., `"11211"`)
- `memberId`: the member's ID

**Pagination — must collect ALL providers:**
- If the response `providers` list is empty or has fewer than `size` items → stop (last page).
- Otherwise increment `page_index` and call again. Merge all pages before filtering.

**Filter results:**
- Keep only providers where `network.status == "TP_INNETWORK"` (NOT `"INN"`).
- Apply any additional criteria from the user's query (e.g., `accept_new_patients == true`, language).

**Expected Outcome**: Complete list of all matching in-network providers (from all pages)

### Step 4: Format Response
Present each matching provider with:
- Provider name and facility name
- Full address
- Phone number from `address.contact.phone` (if available)
- Distance from `address.coordinates.distanceMiles`

If no providers match, state clearly that no providers were found near the member's location.

---

## Worked Example — MRI query

**User query**: "Find in-network care providers near me for an MRI scan"
**Member context**: `memberId=121231234`, `stateCode=NY`, `zipCode=11211`

**Step 1** — `get_coverage_period` body: `{"memberId": "121231234"}`
→ extracts: `contract_uid="CONTRACT-UID-JOHN-1001"`, `brand_code="ACME"`

**Step 2** — `find_care_suggestions(search_text="mri", brand_code="ACME", stateCode="NY", zipCode="11211", memberId="121231234")`
→ response contains `suggestionList[0].criteria.specialtyCategoryList = [{"identifier": "75"}]`
→ response contains `suggestionList[0].criteria.taxonomyList = [{"code": "261QR0200X"}]`
→ response contains `suggestionList[0].dplQueryParams.distance = "30"`
→ extracts: `specialty_category_codes=["75"]`, `taxonomy_codes=["261QR0200X"]`, `distance="30"`

**Step 3** — `find_care_specialty(contract_uid="CONTRACT-UID-JOHN-1001", brand_code="ACME", specialty_category_codes=["75"], taxonomy_codes=["261QR0200X"], distance="30", page_index=0, size=5, stateCode="NY", zipCode="11211", memberId="121231234")`
→ returns providers including Sophia Ramirez at Vista Radiology Center

---

## Distance reference (state/zip model)
- Same state + same ZIP → 0 miles
- Same state + different ZIP → 15 miles (considered "nearby")
- Different state → 999 miles (always excluded)

Default `"20"` covers all same-state providers. Use `"999"` for exhaustive same-state sweep.
""",
        priority=10,
        enabled=True,
    )


def create_benefits_with_providers_playbook() -> Playbook:
    """Playbook for finding providers and their associated benefits."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-benefits-with-providers",
        name="Find Providers and Benefits",
        description="Guide for finding care providers and their associated benefit information",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "find providers and what are my benefits",
                    "find surgeons and show benefits",
                    "find doctors nearby and benefits",
                    "find knee surgeons nearby and what are my benefits",
                    "find providers and show my benefits",
                ],
                target="intent",
                threshold=0.7,
            ),
        ],
        markdown_content="""# Find Providers and Benefits

## Overview
Find care providers and retrieve their associated benefit information for the requested procedure or service.

## Steps

### Step 1: Retrieve Active Coverage Information
1. Retrieve the member's active coverage information
2. Extract the contract identifier, coverage start date, coverage end date, and brand code

**Expected Outcome**: Coverage information with dates needed for benefit search

### Step 2: Get Care Suggestions (MANDATORY - Do NOT Skip)
1. **ALWAYS** call `find_care_suggestions` first before calling `find_care_specialty`
2. Search for care suggestions using:
   - The search query text (e.g., "knee surgery", "primary care", "mri")
   - The brand code from Step 1
   - The member's location from user context as **query parameters**: `stateCode=<member stateCode>`, `zipCode=<member zipCode>`
3. Extract specialty category codes from `suggestionList[].criteria.specialtyCategoryList[].identifier`
   - **For MRI queries**: Extract code `"75"` (Imaging Centers) from the first suggestion
   - **For knee surgery queries**: Extract code `"220"` (Surgery/Orthopedics)
   - **For primary care queries**: Extract code `"25"` (Family/General Practice)
4. Extract taxonomy codes from `suggestionList[].criteria.taxonomyList[].code` (optional)
   - **For MRI queries**: May include `"261QR0200X"` (Radiology Clinic/Center)
   - **IMPORTANT**: If no taxonomy codes extracted, use `None` (not empty list `[]`) when calling `find_care_specialty`
5. **If no specialty codes were extracted** (should be rare), use fallback codes:
   - **For MRI queries**: Use `["75"]` (Imaging Centers)
   - **For knee surgery queries**: Use `["220"]` (Surgery/Orthopedics)
   - **For primary care queries**: Use `["25"]` (Family/General Practice)
   - **DO NOT** use invalid codes like `"23"` - valid codes are: "25", "231", "75", "220"

**Expected Outcome**: Specialty category codes (e.g., "75" for MRI) and taxonomy codes ready to use in Step 3

### Step 3: Find Providers by Specialty
1. Search for providers by specialty using:
   - The contract identifier from Step 1
   - The brand code from Step 1
   - The specialty category codes from Step 2 (e.g., "220" for knee surgeons)
   - The taxonomy codes from Step 2 (optional, e.g., "207X00000X" for orthopedic surgery)
   - The `distance` value from Step 2's `dplQueryParams` (or default "20") as a **query parameter**
   - The member's location from user context as **query parameters**: `stateCode=<member stateCode>`, `zipCode=<member zipCode>`
2. **CRITICAL - Pagination**: The API returns providers in pages (max 5 per page). To get ALL matching providers:
   - Start with `page_index=0` and `size=5`
   - Continue checking additional pages (`page_index=1`, `page_index=2`, etc.) until:
     - No more providers are returned, OR
     - Fewer than `size` providers are returned (indicating last page)
   - Collect providers from all pages before filtering
3. Filter results to only include in-network providers:
   - Check `providers[].network.status == "TP_INNETWORK"` (NOT "INN")
4. Extract provider information including names, addresses, and contact details

**Expected Outcome**: Complete list of all matching in-network providers with contact information (from all pages)

### Step 4: Search Benefits
1. Search for benefits using:
   - The procedure or service keyword (e.g., "knee surgery", "mri", "knee injury", "office visit")
   - The contract identifier from Step 1
   - The coverage start date from Step 1 (extract from `eligibility[].periods[].dates.start`, format: YYYY-MM-DD)
   - The coverage end date from Step 1 (extract from `eligibility[].periods[].dates.end`, format: YYYY-MM-DD)
2. Extract benefit information from response:
   - `benefitResults[].context.documentId` → Document identifier (save for get_benefit_details if needed)
   - `benefitResults[].categories[].categories[].services[].benefits[].systemIdentifier` → Benefit system identifier (save for get_benefit_details if needed)
   - Network code "INN" (In-Network) or "OON" (Out-of-Network) within cost structures
   - Deductibles, coinsurance percentages, copays, precertification requirements

**Expected Outcome**: Benefit details for the procedure/service with identifiers for detailed lookup if needed

### Step 4: Format Combined Response
1. Present providers with their information
2. Present benefits separately with clear In-Network vs Out-of-Network details

**Expected Outcome**: Combined response with providers and benefits
""",
        priority=15,
        enabled=True,
    )


def create_benefit_details_playbook() -> Playbook:
    """Playbook for getting detailed benefit information."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-benefit-details",
        name="Get Detailed Benefit Information",
        description="Guide for retrieving detailed benefit information including diagnosis codes",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "show my benefit details",
                    "what are my benefits for",
                    "benefit details for",
                    "show benefit details",
                    "what are my benefits for knee injury and show the details",
                    "show my benefit details for emergency room in case of a knee injury",
                ],
                target="intent",
                threshold=0.7,
            ),
        ],
        markdown_content="""# Get Detailed Benefit Information

## Overview
Retrieve detailed benefit information including diagnosis codes and specific coverage details for a condition or procedure.

## Steps

### Step 1: Retrieve Active Coverage Information
1. Retrieve the member's active coverage information
2. Extract the contract identifier, coverage start date, and coverage end date

**Expected Outcome**: Coverage information with contract identifier and dates

### Step 2: Search Benefits
1. Search for benefits using:
   - The condition or procedure keyword (e.g., "knee injury", "mri")
   - The contract identifier from Step 1
   - The coverage start date from Step 1 (YYYY-MM-DD)
   - The coverage end date from Step 1 (YYYY-MM-DD)
2. Extract the benefit system identifier and document identifier from the response

**Expected Outcome**: Benefit search results with identifiers needed for detailed lookup

### Step 3: Get Detailed Benefit Information
1. Retrieve detailed benefit information using:
   - The contract identifier from Step 1
   - The document identifier from Step 2 (must match coverage start date)
   - The benefit system identifier from Step 2
   - The coverage start date from Step 1 (YYYY-MM-DD)
   - The coverage end date from Step 1 (YYYY-MM-DD)
2. Extract detailed information including:
   - Diagnosis codes
   - In-Network vs Out-of-Network details
   - Specific copays and coinsurance

**Expected Outcome**: Detailed benefit information with diagnosis codes

### Step 4: Format Response
1. Present benefit details clearly showing:
   - Benefit name and type
   - In-Network details (deductible, copay, coinsurance, precertification)
   - Out-of-Network details
   - Diagnosis codes covered

**Expected Outcome**: Formatted benefit details response
""",
        priority=10,
        enabled=True,
    )


def create_coverage_and_providers_playbook() -> Playbook:
    """Playbook for queries asking about coverage and providers together."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-coverage-and-providers",
        name="Coverage and Providers",
        description="Guide for retrieving coverage details and finding providers who can perform a procedure near a specific location",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "coverage and who can perform near New York",
                    "coverage and who can perform nearby",
                    "MRI coverage and who can perform it in Boston",
                    "what's my MRI coverage and who can perform it",
                    "coverage and providers in a specific city",
                    "coverage and who can perform it in a specific location",
                ],
                target="intent",
                threshold=0.7,
            ),
        ],
        markdown_content="""# Coverage and Providers

## Overview
Retrieve coverage details (benefit information) for a procedure and find providers who can perform it nearby or in a specific location. The primary focus is on coverage details, with provider search as secondary information. Handles queries asking about coverage and providers together, including "nearby" or location-specific requests (e.g., "in Boston, MA", "near New York, NY"). When a specific location is mentioned in the query (like "Boston, MA"), extract and use that location for provider search. If no location is specified, use the member's default location from their profile.

## Steps

### Step 1: Retrieve Active Coverage Information
1. Retrieve the member's active coverage information
2. Extract the contract identifier, coverage start date, coverage end date, and brand code

**Expected Outcome**: Coverage information with contract identifier, dates, and brand code

### Step 2: Search Benefits for Coverage Details
1. Search for benefits using:
   - The procedure keyword (e.g., "mri", "knee surgery")
   - The contract identifier from Step 1
   - The coverage start date from Step 1 (YYYY-MM-DD)
   - The coverage end date from Step 1 (YYYY-MM-DD)
2. Extract benefit information including:
   - In-Network vs Out-of-Network details
   - Coinsurance percentages
   - Copays
   - Deductible requirements
   - Precertification requirements
3. If detailed benefit information is needed, use `get_benefit_details` with:
   - Contract identifier from Step 1
   - Document identifier from benefit search
   - Benefit system identifier from benefit search
   - Coverage dates from Step 1

**Expected Outcome**: Coverage details with coinsurance, copays, and other benefit information

### Step 3: Get Care Suggestions (MANDATORY - Do NOT Skip)
1. **ALWAYS** call `find_care_suggestions` first before calling `find_care_specialty`
2. **Location Handling**:
   - If the query specifies a location (e.g., "in Boston, MA", "near Boston", "in [city], [state]"), extract and use that location
   - Convert city/state names to the appropriate stateCode (US state abbreviation) + zipCode. Examples:
     - "Boston, MA" → `{"stateCode": "MA", "zipCode": "02108"}`
     - "New York, NY / Brooklyn" → `{"stateCode": "NY", "zipCode": "11211"}`
     - "Chicago, IL" → `{"stateCode": "IL", "zipCode": "60601"}`
     - "Los Angeles, CA" → `{"stateCode": "CA", "zipCode": "90012"}`
   - If no specific location is mentioned, use the member's default location from their user context (stateCode + zipCode provided there)
   - Always substitute real values from user context or query — do NOT copy the examples literally
3. Search for care suggestions using (all as kwargs):
   - `search_text`: the search query text (e.g., "mri", "knee surgery")
   - `brand_code`: from Step 1
   - `stateCode`: the resolved state code (e.g., `"MA"`, `"NY"`) — pass as a direct kwarg
   - `zipCode`: the resolved zip code (e.g., `"02108"`, `"11211"`) — pass as a direct kwarg
   - `memberId`: the member's ID
4. Extract specialty category codes from `suggestionList[].criteria.specialtyCategoryList[].identifier`
   - **For MRI queries**: Extract code `"75"` (Imaging Centers)
   - **For surgery queries**: Extract code `"220"` (Surgery/Orthopedics)
   - **For primary care queries**: Extract code `"25"` (Family/General Practice)
5. Extract taxonomy codes from `suggestionList[].criteria.taxonomyList[].code` (optional)
   - **IMPORTANT**: If no taxonomy codes extracted, use `None` (not empty list `[]`) when calling `find_care_specialty`

**Expected Outcome**: Specialty category codes ready for provider search

### Step 4: Find Providers by Specialty
1. **Use the same location from Step 3** (either specified in query like "Boston, MA" or member's default location)
2. Search for providers by specialty using:
   - The contract identifier from Step 1
   - The brand code from Step 1
   - The specialty category codes from Step 3
   - The taxonomy codes from Step 3 (optional)
   - `distance` (default "20"; providers in same state are always ≤ 15 miles, so "20" includes all of them; different-state providers are always 999 miles and excluded)
   - `stateCode` and `zipCode`: same resolved values from Step 3 — pass as direct kwargs
   - `memberId`: the member's ID
3. **CRITICAL - Pagination**: The API returns providers in pages (max 5 per page). To get ALL matching providers:
   - Start with `page_index=0` and `size=5`
   - Continue checking additional pages (`page_index=1`, `page_index=2`, etc.) until:
     - No more providers are returned, OR
     - Fewer than `size` providers are returned (indicating last page)
4. Filter results to only include in-network providers:
   - Check `providers[].network.status == "TP_INNETWORK"` (NOT "INN")

**Expected Outcome**: List of matching in-network providers (may be empty if none found)

### Step 5: Format Response
1. **Primary focus**: Present coverage details clearly showing:
   - In-Network details (deductible, copay, coinsurance, precertification)
   - Out-of-Network details (deductible, copay, coinsurance, precertification)
   - Format coinsurance as percentages (e.g., "20% coinsurance")
2. **Secondary information**: Present provider information:
   - If providers found: List provider names, addresses, and contact details
   - If no providers found: Clearly state the location in the message:
     - If location was specified in query (e.g., "Boston, MA"): "No clinics found near Boston."
     - If using member's default location: "No clinics found near you." or "No clinics found near [member's location]"
3. **Location in response**: When mentioning location in the response:
   - Use the city/state name if specified in query (e.g., "near Boston" if query said "in Boston, MA")
   - Be consistent with how the location was mentioned in the original query
4. Structure the response with coverage details first, then provider information

**Expected Outcome**: Response with coverage details prominently displayed, followed by provider information (or "no providers found" message with appropriate location reference)
""",
        priority=12,
        enabled=True,
    )


def create_search_benefits_playbook() -> Playbook:
    """Playbook for searching specific benefits like coinsurance."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-search-benefits",
        name="Search Benefits",
        description="Guide for searching specific benefit information like coinsurance for procedures",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "what is my OON Coinsurance for an MRI",
                    "what is my out of network coinsurance for an MRI",
                    "what is my coinsurance for",
                    "what are my benefits for",
                    "search benefits for",
                ],
                target="intent",
                threshold=0.7,
            ),
        ],
        markdown_content="""# Search Benefits

## Overview
Search for specific benefit information such as coinsurance, copays, or deductibles for a particular procedure or service. This is useful when you need to know the cost-sharing details for a specific service.

## Steps

### Step 1: Retrieve Active Coverage Information
1. Retrieve the member's active coverage information
2. Extract the contract identifier from the eligibility entry
3. Extract the coverage start date from the active coverage entry (format: YYYY-MM-DD)
4. Extract the coverage end date from the active coverage entry (format: YYYY-MM-DD)

**Expected Outcome**: Contract identifier and coverage dates needed for benefit search

### Step 2: Search Benefits
1. Search for benefits using:
   - The procedure or service keyword (e.g., "mri", "knee surgery", "knee injury")
   - The contract identifier from Step 1
   - The coverage start date from Step 1 (format: YYYY-MM-DD)
   - The coverage end date from Step 1 (format: YYYY-MM-DD)
2. Extract benefit information from the response:
   - For each benefit result, check the networks array
   - Find the network with code "OON" (Out-of-Network) if asking about out-of-network benefits
   - Find the network with code "INN" (In-Network) if asking about in-network benefits
   - Extract the coinsurance percentage, copay, or deductible as requested

**Expected Outcome**: Benefit information with coinsurance, copays, and deductibles for the requested network type

### Step 3: Format Response
1. Present the specific benefit information requested
2. Clearly indicate whether it's In-Network or Out-of-Network
3. Include the coinsurance percentage, copay, or deductible as applicable

**Expected Outcome**: Formatted response with the requested benefit information
""",
        priority=10,
        enabled=True,
    )


def create_payment_playbook() -> Playbook:
    """Playbook for processing bill payments."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-payment-process",
        name="Process Bill Payment",
        description="Guide for processing bill payments for claims",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "pay the due payment",
                    "pay my bill",
                    "pay for claim",
                    "make a payment",
                    "pay the due payment for claim",
                ],
                target="intent",
                threshold=0.9,
            ),
        ],
        markdown_content="""# Process Bill Payment

## Overview
Complete the payment process for claim bills. This involves retrieving billing information, creating a payment intent, and confirming the payment.

## Steps

### Step 1: Retrieve Billing Information
1. Retrieve all billing items for the member
   - **CRITICAL - Pagination**: The API paginates results (max 50 items per page). To ensure you retrieve ALL items:
     - Start with the first page and continue fetching subsequent pages
     - Continue until you receive an empty response or fewer items than the page size
     - **IMPORTANT**: If a page returns exactly 50 items, you MUST check the next page - only stop when you receive 0 items or fewer than 50 items
     - Collect items from all pages before filtering or processing
2. If a specific claim ID is mentioned, find the corresponding billing item
3. Extract `items[].identifiers.uniqueId` (claim UID) and `items[].amountDue` for the claim to be paid

**Expected Outcome**: Complete list of all billing items with claim identifiers and amounts due

### Step 2: Create Payment Intent
1. Create a payment intent with:
   - The amount to pay (from Step 1 or specified by user)
   - The claim UID (`items[].identifiers.uniqueId`, optional but recommended to link payment to claim)
2. Extract the `transactionId` from the response

**Expected Outcome**: Payment intent identifier needed for confirmation

### Step 3: Confirm Payment
1. Confirm the payment intent using the `transactionId` from Step 2
2. Extract the `receiptUrl` from the response

**Expected Outcome**: Payment confirmation with receipt URL

### Step 4: Format Response
1. Confirm successful payment
2. Provide receipt URL
3. Include claim ID and amount paid

**Expected Outcome**: Payment confirmation message with receipt
""",
        priority=10,
        enabled=True,
    )


def create_family_member_claims_playbook() -> Playbook:
    """Playbook for querying claims for family members."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-family-member-claims",
        name="Query Family Member Claims",
        description="Guide for retrieving claims information for family members",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "my daughter's claim",
                    "my son's claim",
                    "family member claim",
                    "dependent's claim",
                    "was my daughter Sara's latest claim approved",
                    "show my dependents and how many claims are under their names",
                ],
                target="intent",
                threshold=0.7,
            ),
        ],
        markdown_content="""# Query Family Member Claims

## Overview
Retrieve claims information for family members or dependents. You MUST first get coverage information to identify the family member's member ID, then use that ID to get their specific claims.

## Steps

### Step 1: Retrieve Coverage Information
1. Retrieve the subscriber's coverage information
2. Filter for active coverage by checking the status code is "A" (Active)
3. Extract the list of covered members from the active coverage period: `eligibility[].periods[].enrollees[]`
4. Identify the target family member by:
   - Matching the name mentioned in the request with `enrollees[].name.given` and `enrollees[].name.family`
   - Matching the relationship mentioned (e.g., "daughter", "son") with `enrollees[].relationship.identifier` ("CHILD" for children)
5. **CRITICAL**: Extract the family member's `personId` from the matched enrollee object

**Expected Outcome**: Family member's `personId` (member ID)

### Step 2: Retrieve Claims for Family Member
1. Retrieve claims using the family member's `personId` (from Step 1)
   - Use the `personId` extracted from coverage enrollees, NOT the subscriber's member ID
2. The response will contain claims specific to that family member
3. Sort by start date (descending) to get the most recent claims first

**Expected Outcome**: Claims list for the specific family member

### Step 3: Format Response
1. Present claims specific to the requested family member
2. Include claim status, dates, and amounts
3. For questions about claim approval status, check `classification.status.identifier`:
   - "APRVD" = Approved
   - "PEND" = Pending
   - "DND" = Denied
   - "PROC" = Processing

**Expected Outcome**: Formatted response with family member's claims and status

## Important Notes
- **ALWAYS** get coverage information first to obtain the family member's `personId`
- Do NOT use the subscriber's member ID to get family member claims
- The coverage information contains all covered family members in `periods[].enrollees[]` with their unique `personId` values
- Each family member has their own `personId` that must be used for their claims
""",
        priority=10,
        enabled=True,
    )


def create_plan_information_playbook() -> Playbook:
    """Playbook for retrieving plan information including deductibles and copays."""
    return Playbook(
        type=PolicyType.PLAYBOOK,
        id="oak-plan-information",
        name="Get Plan Information",
        description="Guide for retrieving plan details including deductibles, OOP, and copays",
        triggers=[
            NaturalLanguageTrigger(
                type="natural_language",
                value=[
                    "what's my plan deductibles",
                    "what are my copays",
                    "my deductibles and out of pocket",
                    "what's my plan deductibles OOP and Coinsurance",
                    "what's my plan deductibles OOP and Copays",
                    "what is my in-network specialist copay",
                    "summarize my current plan cost sharing",
                ],
                target="intent",
                threshold=0.85,
            ),
        ],
        markdown_content="""# Get Plan Information

## Overview
Retrieve plan information including deductibles, out-of-pocket limits, and copays. This provides comprehensive cost-sharing details for the member's plan.

## Steps

### Step 1: Retrieve Active Coverage Information
1. Retrieve the member's active coverage information
2. Extract the `periodKey` from the active period entry (`eligibility[].periods[].periodKey`)
3. Verify the coverage is active (`status.identifier == "A"`)

**Expected Outcome**: `periodKey` (coverage key) needed for plan information lookup

### Step 2: Retrieve Plan Information
1. Retrieve plan information using:
   - The `periodKey` from Step 1 (use as `coverage_key` parameter)
   - The plan type (usually "MED" for Medical, which is the default)
2. Extract cost-sharing information:
   - Deductibles (Individual and Family, In-Network and Out-of-Network)
   - Out-of-Pocket limits
   - Copays for different service types
   - Coinsurance percentages

**Expected Outcome**: Complete plan information with cost-sharing details

### Step 3: Format Response
1. Present plan information clearly organized by:
   - Coverage level (Individual vs Family)
   - Network type (In-Network vs Out-of-Network)
   - Service type (Specialist, Urgent Care, etc.)

**Expected Outcome**: Formatted plan information response
""",
        priority=10,
        enabled=True,
    )


# ===== TOOL ENRICHMENTS =====


def create_coverage_period_enrichment() -> ToolGuide:
    """Enrichment for get_coverage_period tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-coverage-period",
        name="Coverage Period Tool Enrichment",
        description="Provides additional context for using get_coverage_period",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_coverage_period"],
        guide_content="""
## Data Values & Patterns

**Coverage Status Codes:**
- `"A"` = Active coverage (use for current queries)
- `"I"` = Inactive/terminated coverage (historical only)

**Relationship Codes (in `enrollees[].relationship.identifier`):**
- `"SUBSCR"` = Subscriber (primary member)
- `"CHILD"` = Dependent child
- `"SPOU"` = Spouse

**Gender Codes (in `enrollees[].gender.identifier`):**
- `"M"` = Male
- `"F"` = Female

**Brand Codes (in `eligibility[].brand.identifier`):**
- `"ACME"` = ACME HEALTH
- `"VSTA"` = VISTA HEALTH

**Contract Codes (derived from contractUniqueId):**
- `"1J1U"` = John's contract (Acme)
- `"9Z9X"` = Jane's contract (Vista)

**Coverage Key Format:**
- Pattern: `{contractCd}-{startDate}-{endDate}-{type}-{planId}`
- Example: `"1J1U-20250101-20251231-MED-57AMFC"`
- Use `periodKey` (from `periods[].periodKey`) for `get_plan_information` and `get_benefit_accumulators`

**Key Fields (CRITICAL - Extract these for other tools):**
- `eligibility[].periods[].status.identifier == "A"` → Active coverage to use (filter for this)
- `eligibility[].periods[].periodKey` → **Extract this** for `get_plan_information` and `get_benefit_accumulators`
  - Example: `"1J1U-20250101-20251231-MED-57AMFC"`
- `eligibility[].periods[].dates.start` → **Extract this** for `search_benefits` (format: YYYY-MM-DD)
- `eligibility[].periods[].dates.end` → **Extract this** for `search_benefits` (format: YYYY-MM-DD)
- `eligibility[].identifiers.contractUniqueId` → **Extract this** for `search_benefits` and `find_care_specialty`
- `eligibility[].brand.identifier` → **Extract this** for `find_care_suggestions` (e.g., "ACME", "VSTA")
- `eligibility[].periods[].enrollees[]` → List includes subscriber and dependents

**Workflow:**
1. Call `get_coverage_period` first
2. Filter for active coverage by iterating through `eligibility[]` and then `periods[]` arrays:
   ```python
   for elig in response.get("eligibility", []):
       for period in elig.get("periods", []):
           if period.get("status", {}).get("identifier") == "A":
               # This is active coverage - extract values from period and elig
               active_period = period
               active_elig = elig
               break
   ```
   **CRITICAL**: Check `periods[].status.identifier == "A"`, NOT `eligibility[].statusCd.code`
   - Status code is `"A"` (single letter), NOT `"ACTIVE"` (full word)
   - An eligibility entry can have multiple period entries (active and inactive), so you must check each period entry
3. Extract `periodKey`, `dates.start`, `dates.end` from the active `periods` entry
4. Extract `identifiers.contractUniqueId` and `brand.identifier` from the parent `eligibility` entry
5. Use these extracted values in subsequent tool calls
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_search_benefits_enrichment() -> ToolGuide:
    """Enrichment for search_benefits tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-search-benefits",
        name="Search Benefits Tool Enrichment",
        description="Provides additional context for using search_benefits",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_search_benefits"],
        guide_content="""
## Supported Inquiry Keywords

**Valid `inquiry_keyword` values (case-insensitive matching):**
- `"knee injury"` → Maps to emergency room benefits for knee injuries
- `"knee surgery"` → Maps to knee surgery/arthroscopy benefits
- `"mri"` → Maps to MRI imaging benefits
- `"office visit"` → Maps to office visit benefits (PCP and specialist)

**Network Codes (in `search_benefits` response `networks[].networkCode`):**
- `"INN"` = In-Network
- `"OON"` = Out-of-Network
- Note: field is `networkCode` (NOT `code`) in `search_benefits` response
- Also: cost components are in `networks[].costComponents[]` (NOT `costshares[]`)

**Benefit System IDs (from response, use with `get_benefit_details`):**
- `"82da10ab-c05d-46e1-bf48-ad61ea70eb3d"` = Emergency Room
- `"pcp-ov-11"` = Primary Care Office Visit
- `"spec-ov-11"` = Specialist Office Visit
- `"mri-IMG-OP"` = MRI Outpatient
- `"knee-surg-op"` = Knee Surgery Outpatient

**Associated Treatment Codes:**
- `"CPT:29881"` = Knee arthroscopy
- `"CPT:70551"` = MRI brain without contrast

**Cost Extraction Path (for reading coverage details from search_benefits):**
- `benefitResults[].categories[].categories[].services[].benefits[].scenarios[].networks[]`
  - `networks[].networkCode` → "INN" or "OON" (filter by this)
  - `networks[].deductibleRequired` → "Yes"/"No"
  - `networks[].priorAuthRequired` → "Y"/"N"
  - `networks[].costComponents[].type` → e.g., "Coinsurance", "Copayment"
  - `networks[].costComponents[].value` → e.g., "20%", "$0"

**Response Fields (CRITICAL - Extract these for get_benefit_details):**
- `benefitResults[].context.documentId` → Document identifier (e.g., "281019533353-01012025")
  - **Extract this value** and use as `doc_id` parameter in `get_benefit_details`
  - Deterministically generated from contractCd + coverage_start_dt
  - **DO NOT generate manually** - always extract from this response
- `benefitResults[].categories[].categories[].services[].benefits[].systemIdentifier` → Benefit system identifier (e.g., "knee-surg-op", "mri-IMG-OP")
  - **Extract this value** and use as `benefit_sys_id` parameter in `get_benefit_details`
- `benefitResults[].relatedProcedures[]` → Related CPT codes and names

**Workflow for get_benefit_details:**
1. Call `search_benefits` first
2. Extract `benefitResults[].context.documentId` and the `systemIdentifier` from within the categories hierarchy
3. Use those exact values in `get_benefit_details` call
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_find_care_specialty_enrichment() -> ToolGuide:
    """Enrichment for find_care_specialty tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-find-care-specialty",
        name="Find Care Specialty Tool Enrichment",
        description="Provides additional context for using find_care_specialty",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_find_care_specialty"],
        guide_content="""
## CRITICAL: Use find_care_suggestions First - DO NOT Skip This Step!

**MANDATORY Workflow for ALL specialty searches:**
1. **ALWAYS** call `find_care_suggestions` first with search text (e.g., "mri", "knee surgery", "primary care")
2. Extract `specialty_category_codes` from `suggestionList[].criteria.specialtyCategoryList[].identifier`
   - Example for MRI: Extract identifier `"75"` from `suggestionList[0].criteria.specialtyCategoryList[0].identifier`
3. Extract `taxonomy_codes` from `suggestionList[].criteria.taxonomyList[].code` (optional)
4. **CRITICAL**: If extraction returns empty list or no codes found, use fallback codes (see Fallback Codes section below)
5. **IMPORTANT**: For `taxonomy_codes` parameter:
   - If taxonomy codes were extracted, use them: `taxonomy_codes=taxonomy_codes`
   - If no taxonomy codes were extracted, pass `None` or omit the parameter: `taxonomy_codes=None` (do NOT pass empty list `[]`)
6. Use those extracted codes (or fallback codes) in `find_care_specialty`

**DO NOT** search with text like "orthopedic surgery" - you MUST use numeric category codes!
**DO NOT** use hardcoded codes without first calling `find_care_suggestions`!
**DO NOT** call `find_care_specialty` with empty `specialty_category_codes` list - always use fallback if extraction fails!

## Specialty Category Codes

**Common codes:**
- `"25"` = Family/General Practice (Primary Care)
- `"231"` = Clinics / Radiology
- `"75"` = Imaging Centers
- `"220"` = Surgery / Orthopedics (for knee surgeons)

**Taxonomy Codes (optional filter):**
- `"261QP2300X"` = Primary Care Clinic
- `"207Q00000X"` = Family Medicine
- `"261QR0200X"` = Radiology Clinic/Center
- `"2085R0202X"` = Radiology, Diagnostic
- `"207X00000X"` = Orthopedic Surgery (for knee surgeons)

**For "knee surgery" queries:**
- Use `specialty_category_codes: ["220"]`
- Use `taxonomy_codes: ["207X00000X"]` (optional but recommended)

**For "MRI" queries:**
- Use `specialty_category_codes: ["75"]` (Imaging Centers)
- Alternative: `["231", "75"]` (Clinics/Radiology and Imaging Centers) if both codes are returned
- Use `taxonomy_codes: ["261QR0200X"]` (optional, Radiology Clinic/Center)
- **IMPORTANT**: If no taxonomy codes are extracted, pass `None` or omit the parameter entirely - do NOT pass an empty list `[]`

**Fallback Codes (REQUIRED if suggestions don't return codes or extraction returns empty list):**
- **CRITICAL**: Always check if `specialty_category_codes` list is empty after extraction
- **If empty, you MUST use these fallback codes before calling `find_care_specialty`:**
  - **MRI**: Use `["75"]` (Imaging Centers) - **NOT "23" which is INVALID**
  - **Primary Care**: Use `["25"]` (Family/General Practice)
  - **Knee Surgery**: Use `["220"]` (Surgery/Orthopedics)
  - **Radiology**: Use `["231", "75"]` (Clinics/Radiology and Imaging Centers)
- **Example check**: `if not specialty_codes: specialty_codes = ["75"]  # for MRI`

**IMPORTANT**: Code `"23"` is NOT a valid specialty category code. Valid codes are: "25", "231", "75", "220"

**Network Status Values:**
- `"TP_INNETWORK"` = In-network provider
- `accept_new_patients`: Boolean indicating if accepting new patients

**Constraints:**
- `size` parameter: max 5, default 5 (API returns max 5 providers per page)
- `page_index`: Zero-based page index (0 = first page, 1 = second page, etc.)
- `distance`: String value in miles (default "20") — pass as a kwarg
- `stateCode` and `zipCode`: pass as **direct kwargs** (e.g., `stateCode="NY"`, `zipCode="11211"`)
  - Extract these from the member's user context
  - `stateCode` = US state abbreviation (e.g., "NY"); `zipCode` = ZIP code (e.g., "11211")
  - **This API does NOT use latitude/longitude.** Location is determined by `stateCode` + `zipCode` only.

**Correct calling convention:**
```python
await oak_health_insurance_find_care_specialty(
    contract_uid="CONTRACT-UID-JOHN-1001",
    brand_code="ACME",
    specialty_category_codes=["75"],
    taxonomy_codes=["261QR0200X"],  # omit if None
    distance="30",
    page_index=0,
    size=5,
    stateCode="NY",
    zipCode="11211",
    memberId="121231234",
)
```

**Distance Semantics (state/zip based):**
- Same state + same zip → 0 miles
- Same state + different zip → 15 miles (these providers are considered "nearby")
- Different state → 999 miles (excluded)
- The default distance of "20" includes all same-state providers (both same-zip and different-zip)
- Providers in a **different state** are always excluded regardless of distance setting

**CRITICAL - Pagination for Complete Results:**
- The API paginates results: max 5 providers per page
- **To get ALL matching providers, you MUST check multiple pages:**
  - Start with `page_index=0`, `size=5`
  - Continue with `page_index=1`, `page_index=2`, etc. until:
    - Response returns empty `providers[]` array, OR
    - Response returns fewer than `size` providers (indicating last page)
  - **Example workflow:**
    ```python
    all_providers = []
    page_index = 0
    while page_index < 3:  # Check up to 3 pages
        resp = await find_care_specialty(..., page_index=page_index, size=5, ...)
        providers = resp.get("providers", [])
        if not providers:
            break
        all_providers.extend(providers)
        if len(providers) < 5:
            break  # Last page
        page_index += 1
    ```
  - **Why this matters**: If you only check page 0, you may miss providers that appear on later pages, especially when filtering by additional criteria (e.g., "accept new patients")

**Response:**
- `providers[].address.coordinates.distanceMiles` → Distance in miles from member location (calculated)
- `providers[].address.contact.phone` → Phone number (e.g., "+1-212-555-0303")
- `providers[].network.status` → Network status (check for `"TP_INNETWORK"` to filter in-network providers)
- `providers[].network.accept_new_patients` → Availability (boolean)
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_find_care_suggestions_enrichment() -> ToolGuide:
    """Enrichment for find_care_suggestions tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-find-care-suggestions",
        name="Find Care Suggestions Tool Enrichment",
        description="Provides additional context for using find_care_suggestions",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_find_care_suggestions"],
        guide_content="""
## Search Intent Types

**`primarySearchIntent` values:**
- `"SPECIALTY"` → Specialty-based search (e.g., primary care, radiology)
- `"PROCEDURE"` → Procedure-based search (e.g., MRI, knee surgery)

**Search Text Mapping (case-insensitive):**
- "primary care", "pcp", "family doctor", "general practitioner" → Maps to "primary care" specialty
- "radiology", "imaging" → Maps to "radiology" specialty
- "knee surgery", "knee surg" → Maps to "knee surgery" procedure
- "mri" → Maps to "mri" procedure
- Default fallback → "primary care" specialty

**Suggestion Keys in Database:**
- `"primary care"` → Primary care providers (category: "25")
- `"radiology"` → Radiology/imaging centers (categories: "231", "75")
- `"mri"` → MRI-specific providers (category: "75")
- `"knee surgery"` → Orthopedic surgeons (category: "220", taxonomy: "207X00000X")

**Response Fields (CRITICAL - Use these in find_care_specialty):**
- `suggestionList[].criteria.specialtyCategoryList[].identifier` → Category codes (e.g., "25", "220", "231", "75")
  - **For "mri": returns "75"** (Imaging Centers)
  - **For "knee surgery": returns "220"**
  - **For "primary care": returns "25"**
- `suggestionList[].criteria.taxonomyList[].code` → Taxonomy codes (e.g., "207X00000X", "261QR0200X")
  - **For "mri": returns "261QR0200X"** (Radiology Clinic/Center)
  - **For "knee surgery": returns "207X00000X"**
- `suggestionList[].dplQueryParams` → Suggested parameters for `find_care_specialty`:
  - `specialty_category_codes`, `taxonomy_codes`, `distance` → use as kwargs
- `locationDetails` → Confirmed location echoed back in the response

**Location Format (CRITICAL):**
- Pass `stateCode` and `zipCode` as **direct kwargs**: `stateCode="NY"`, `zipCode="11211"`
- Extract these from the user's context (e.g., `stateCode:NY`, `zipCode:11211`)
- `stateCode` = US state abbreviation (e.g., "NY" for New York, "MA" for Massachusetts)
- **This API does NOT use latitude/longitude.** Location is determined by `stateCode` + `zipCode` only. Provider responses include `address.coordinates.distanceMiles` (a calculated value) but no coordinate fields. Do not ask the user for coordinates.

**Correct calling convention:**
```python
await oak_health_insurance_find_care_suggestions(
    search_text="mri",
    brand_code="ACME",
    stateCode="NY",
    zipCode="11211",
    memberId="121231234",
)
```

**Distance Semantics (NEW - state/zip based):**
- Same state + same zip → 0 miles (exact area match)
- Same state + different zip → 15 miles (within the state)
- Different state → 999 miles (out of range)
- **Use distance ≥ 16** to include all providers in the same state but different zip codes
- **Use distance ≤ 14** to restrict results to providers sharing the exact same zip code

**Workflow (MANDATORY for all provider searches):**
1. **ALWAYS** call this tool first with search text (e.g., "mri", "knee surgery", "primary care")
2. Extract `specialtyCategoryList[].identifier` values → Use as `specialty_category_codes` in `find_care_specialty`
   - Example for MRI: `suggestionList[0].criteria.specialtyCategoryList[0].identifier` → `"75"`
3. Extract `taxonomyList[].code` values → Use as `taxonomy_codes` in `find_care_specialty` (optional)
4. Use `distance` from `dplQueryParams` as the query param for `find_care_specialty` (default "20" covers all same-state providers)
5. **DO NOT** proceed to `find_care_specialty` without first calling this tool and extracting codes
6. **IMPORTANT**: When calling `find_care_specialty`, remember to check multiple pages (see `find_care_specialty` enrichment for pagination details) to get ALL matching providers
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_get_benefit_details_enrichment() -> ToolGuide:
    """Enrichment for get_benefit_details tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-benefit-details",
        name="Get Benefit Details Tool Enrichment",
        description="Provides additional context for using get_benefit_details",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_benefit_details"],
        guide_content="""
## Important Data Patterns

**`doc_id` Generation:**
- Deterministically generated from `contract_cd` + `coverage_start_dt`
- Format: `{12-digit-hash}-{MMDDYYYY}` (e.g., "281019533353-01012025")
- Must match exactly or API call fails with 400 error
- Always get from `search_benefits` response, don't generate manually

**Diagnosis Codes (in response `scenarios[].diagnosisCd[]`):**
- Emergency/Knee Injury: `"S86.911A"`, `"T14.90XA"`
- Office Visits: `"Z00.00"`, `"J01.90"`, `"M25.50"`
- MRI: `"R51"`, `"G44.209"`
- Knee Surgery: `"M23.91"`, `"S83.241A"`

**Service Definition IDs:**
- `"ER-INST-001"` = Emergency Room Institutional
- `"PCP-11-OV"` = Primary Care Office Visit
- `"SPEC-11-OV"` = Specialist Office Visit
- `"IMG-MRI-OP"` = MRI Outpatient
- `"SURG-KNEE-OP"` = Knee Surgery Outpatient

**Response Navigation (CRITICAL field names):**
- `benefitResults[].serviceCategory[].services[].service[].situations[].networks[]`
  - `networks[].code` → "INN" or "OON" (filter by this — note: `code` NOT `networkCode` in this response)
  - `networks[].type` → "In Network" or "Out of Network"
  - `networks[].deductibleApplies` → "Yes"/"No"/"Covered - At the INN benefit level"
  - `networks[].precertRequired` → "Y"/"N"
  - `networks[].costshares[].type` → e.g., "Copayment", "Coinsurance"
  - `networks[].costshares[].value` → e.g., "$400 Per Visit", "0%"
- `benefitResults[].serviceCategory[].services[].service[].situations[].diagnosisCd[]` → diagnosis codes
- `benefitResults[].serviceCategory[].services[].service[].benefitNm` → benefit name
- `benefitResults[].serviceCategory[].services[].service[].benefitType` → benefit type
- `benefitResults[].serviceCategory[].services[].service[].specialtyType[]` → applicable settings

**Response Contains:**
- Detailed benefit structure not in `search_benefits`
- Service category details with diagnosis codes
- Plan level benefits summary
- Both `serviceCategory` and `planLevel` sections

**Use When:**
- User asks for "benefit details" or "show details"
- Diagnosis codes are needed
- More specific coverage info required beyond `search_benefits`
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_get_plan_information_enrichment() -> ToolGuide:
    """Enrichment for get_plan_information tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-plan-information",
        name="Get Plan Information Tool Enrichment",
        description="Provides additional context for using get_plan_information",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_plan_information"],
        guide_content="""
## IMPORTANT: Get coverage_key from get_coverage_period First

**Workflow:**
1. Call `get_coverage_period` first
2. Filter for active coverage (`eligibility[].periods[].status.identifier == "A"`)
3. Extract `periodKey` from `eligibility[].periods[].periodKey`
4. Use that exact `periodKey` value as the `coverage_key` parameter

**DO NOT** generate or guess the coverage_key - it must be extracted from get_coverage_period response!

## Plan Type & Cost Sharing

**`opted_plan_type` values:**
- `"MED"` = Medical (default, only option in data)

**`benefitPeriod` values:**
- `"Calendar Year"` = Benefits reset annually on Jan 1 (cd: "CalendarYear")

**Network Codes (in `network[].cd`):**
- `"ALL"` = All networks
- `"HMO"` = In Network (HMO plans)
- `"PAR"` = Participating
- `"INN"` = In-Network

**Coverage Level Codes:**
- `"IND"` = Individual
- `"FAM"` = Family

**Cost Share Option Names (examples from data):**
- `"CFAMDEDDOL"` = Family Deductible
- `"CINDDEDDOL"` = Individual Deductible
- `"CFAMCOPCYMX"` = Family Copay Max
- `"CSNGLCOPCYMX"` = Single Party Copay Max
- `"SPEC_COPAY"` = Specialist Copay
- `"URG_COPAY"` = Urgent Care Copay
- `"PCP_COPAY"` = Primary Care Copay
- `"RX_GEN_COPAY"` = Generic Prescription Copay
- `"IMG_COINS"` = Advanced Imaging Coinsurance
- `"OPS_COINS"` = Outpatient Surgery Coinsurance

**Cost Share Organization:**
- `network[].costShare[]` organized by:
  - Coverage level: Individual vs Family (`coverageCd`: "IND" vs "FAM")
  - Network: In-Network vs Out-of-Network
  - Service type: Specialist, Urgent Care, PCP, etc.
  - Time period: "Per Calendar Year", "Per Visit", "Per Fill"

**Key Fields:**
- `costShare[].benefit.cd` → Type: "Deductible", "OutOfPocketMax", "Copay", "Coinsurance"
- `costShare[].benefit.value` → Amount or percentage
- `costShare[].benefit.unit` → "Dollar(S)", "PCT", "Month(s)"
- `costShare[].timePeriod` → When it applies (e.g., "Per Calendar Year", "Per Visit")
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_payment_tools_enrichment() -> ToolGuide:
    """Enrichment for payment-related tools."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-payment-tools",
        name="Payment Tools Enrichment",
        description="Provides additional context for payment processing tools",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=[
            "oak_health_insurance_get_member_billing",
            "oak_health_insurance_create_payment_intent",
            "oak_health_insurance_confirm_payment_intent",
        ],
        guide_content="""
## Billing Status Values

**`status` values (in `get_member_billing` response):**
- `"DUE"` = Payment due
- `"PAID"` = Payment completed
- `"PARTIAL"` = Partial payment made
- `"IN_COLLECTIONS"` = Sent to collections

**Payment Intent State:**
- `"REQUIRES_CONFIRMATION"` → After `create_payment_intent` (initial state, field: `state`)
- `"SUCCEEDED"` → After `confirm_payment_intent` (final state, field: `state`)

**Transaction ID Format:**
- Pattern: `"pi_{24-char-hex}"` (e.g., "pi_abc123def456...", field: `transactionId`)
- Auth token format: `"{transactionId}_secret_{12-char-hex}"` (field: `authToken`)

**CRITICAL - Pagination for get_member_billing:**
- The API returns billing items in pages (max 50 items per page)
- **To retrieve ALL billing items, you MUST paginate through all pages:**
  - Start with the first page (`page_index=0`) and continue to subsequent pages
  - Continue fetching pages until you receive an empty response or fewer items than the page size
  - **IMPORTANT**: If a page returns exactly 50 items, you MUST check the next page - only stop when you receive 0 items or fewer than 50 items
  - Collect items from all pages before filtering or processing
- **Why this matters**: Stopping after the first page when it contains exactly 50 items will cause you to miss billing items on subsequent pages, leading to incomplete results

**Billing Item Fields (in `get_member_billing` response):**
- `items[].identifiers.uniqueId` → Claim UID — **only use this as `clm_uid` in payment API calls**; never show this to the user
- `items[].identifiers.displayId` → Human-readable claim ID (e.g., "2025034AA2251") — **always use this when presenting billing items to the user**
- `items[].amountDue` → Amount due (was: `dueAmt`)
- `items[].dueDate` → Due date (was: `dueDt`)
- `items[].paymentStatus` → Status: DUE, PAID, PARTIAL, IN_COLLECTIONS (was: `status`)
- `items[].onlinePaymentEnabled` → Whether online payment is allowed (was: `canPayOnline`)

**Payment Response Fields:**
- `transactionId` → Payment intent ID (was: `paymentIntentId`)
- `state` → Current state: REQUIRES_CONFIRMATION or SUCCEEDED (was: `status`)
- `authToken` → Auth token for confirmation (was: `clientSecret`)
- `totalAmount` → Amount (was: `amount`)
- `receiptUrl` → Receipt URL (in confirm response, unchanged)
- `linkedClaim` → Linked claim UID (was: `clmUid`)

**Workflow:**
1. `get_member_billing` → Get `items[].identifiers.uniqueId` and `items[].amountDue` (filtered to DUE/PARTIAL/IN_COLLECTIONS)
   - **Remember to paginate** to get all items (see pagination section above)
2. `create_payment_intent` → Get `transactionId` and `authToken`
   - Optional: link to `clm_uid` for automatic billing update
3. `confirm_payment_intent` → Get `receiptUrl` and `state` becomes "SUCCEEDED"

**Automatic Updates:**
- If `clm_uid` provided in `create_payment_intent`, billing ledger automatically updates to "PAID" when `confirm_payment_intent` succeeds
- `totals.dueCount` = count of items with paymentStatus != "PAID" and amountDue > 0
- `totals.totalDueAmt` = sum of all due amounts
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_get_member_claims_enrichment() -> ToolGuide:
    """Enrichment for get_member_claims tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-member-claims",
        name="Get Member Claims Tool Enrichment",
        description="Provides additional context for using get_member_claims",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_member_claims"],
        guide_content="""
## Claim Status Codes

**`classification.status.identifier` values:**
- `"APRVD"` = Approved (claim approved and processed)
- `"DND"` = Denied (claim denied, not covered)
- `"PEND"` = Pending (claim in review)
- `"PROC"` = Processing (claim being processed)

**Status Descriptions:**
- Approved: "We finished reviewing this claim and approved the claim under your plan."
- Denied: "Common reasons are that we received the same claim twice, or the service performed is not covered under your plan."
- Pending: "This claim is in review. We'll update once processing is complete."
- Processing: "We are currently processing this claim."

**Claim Class & Type:**
- `classification.category.identifier`: `"M"` = Medical Claim
- `classification.type.identifier`: `"PR"` = Professional Claim
- `classification.source.identifier`: `"808"` = WGS20

**Sort Options (`sort_by` parameter):**
- `"start_date"` = Sort by claim start date (default)
- `"end_date"` = Sort by claim end date
- `"process_date"` = Sort by processing date
- `"receive_date"` = Sort by receive date

**Constraints:**
- `size`: max 5, default 5
- Default sort: `start_date` descending (most recent first)

**Key Fields:**
- `identifiers.uniqueId` → Use for `get_claim_details` and `get_claim_eob_pdf` (NOT `identifiers.displayId`)
- `identifiers.displayId` → Human-readable claim ID (e.g., "2025034AA1251")
- `parties.subject.identity.primaryId` / `parties.subject.identity.secondaryId` → Member identifiers
- `parties.subject.givenName` / `parties.subject.familyName` / `parties.subject.birthDate` → Filter by family member
- Returns claims for ALL covered family members (subscriber + dependents)
- `financial.payment.disbursed` → Amount paid by insurance
- `financial.allocation.patientShare` → Member's responsibility
- `financial.allocation.excluded` → Amount not covered
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_get_claim_details_enrichment() -> ToolGuide:
    """Enrichment for get_claim_details tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-claim-details",
        name="Get Claim Details Tool Enrichment",
        description="Provides additional context for using get_claim_details",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_claim_details"],
        guide_content="""
## Claim Details Data

**Service Line Procedure Codes:**
- `"99213"` = Office visit, established patient
- `"99214"` = Office visit, established patient (more complex)
- `"97110"` = Therapeutic exercise
- `"93000"` = EKG
- `"80050"` = General health panel
- `"97140"` = Manual therapy

**Diagnosis Codes (in `lineItems[].diagnosisSets[].codes[].code`):**
- `"Z00.00"` = General health check
- `"M25.50"` = Joint pain
- `"R51"` = Headache
- `"J06.9"` = Upper respiratory infection
- `"I10"` = Hypertension
- `"M54.5"` = Low back pain

**EOB Availability:**
- EOBs only exist for claims with status "APRVD" or "PROC"
- EOB UID format: `"EOB-{first-8-chars-of-clmUid}"`
- Check number: `"100200300"` (only if financial.payment.disbursed > 0)

**Key Fields:**
- `lineItems[]` → Detailed service line items with procedure codes (was: `serviceLines[]`)
- `explanations[]` → EOB documents (only for approved/processing claims, was: `eobs[]`)
- `identifiers.uniqueId` → Required parameter value (NOT `identifiers.displayId`)
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_get_claim_eob_pdf_enrichment() -> ToolGuide:
    """Enrichment for get_claim_eob_pdf tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-claim-eob-pdf",
        name="Get Claim EOB PDF Tool Enrichment",
        description="Provides additional context for using get_claim_eob_pdf",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_claim_eob_pdf"],
        guide_content="""
## EOB PDF Data

**EOB PDF URL Format:**
- Pattern: `"https://example.health/eob/{documentId}.pdf"`
- Example: `"https://example.health/eob/EOB-451F6F37.pdf"`

**EOB Properties:**
- `contentType`: Always `"application/pdf"`
- `fileSize`: Typically `224000` (224 KB)
- `documentId`: Format `"EOB-{first-8-chars-of-clmUid}"`

**Availability:**
- Only available for claims with status "APRVD" or "PROC"
- If claim is "DND" or "PEND", EOB array will be empty
- Each approved claim can have multiple EOBs (sequence numbers)

**Key Fields:**
- `clm_uid` → Required parameter (NOT clmId)
- `explanations[].documentUrl` → Direct PDF download URL
- `explanations[].documentId` → EOB unique identifier
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_get_benefit_accumulators_enrichment() -> ToolGuide:
    """Enrichment for get_benefit_accumulators tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-benefit-accumulators",
        name="Get Benefit Accumulators Tool Enrichment",
        description="Provides additional context for using get_benefit_accumulators",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_benefit_accumulators"],
        guide_content="""
## Accumulator Types & Levels

**Accumulator Types (`category`):**
- `"DED"` = Deductible
- `"OOP"` = Out-of-Pocket Maximum

**Coverage Levels (`scope`):**
- `"INDV"` = Individual
- `"FAM"` = Family

**Network Codes (`tier`):**
- `"INN"` = In-Network
- `"OON"` = Out-of-Network

**Accumulator Fields:**
- `accumulated` → Amount already met/toward limit
- `maximum` → Maximum limit for the period
- `planYear` → Benefit year (extracted from coverage effective date)

**Example Values (from data):**
- Individual INN Deductible: accumulated="250.00", maximum="1000.00"
- Individual INN OOP: accumulated="400.00", maximum="3000.00"
- Family INN Deductible: accumulated="700.00", maximum="3000.00"
- Family INN OOP: accumulated="1200.00", maximum="6000.00"
- HMO plans may have: accumulated="0.00", maximum="0.00" (no deductible)

**Key Fields:**
- `coverage_key` → Required parameter (use `periodKey` from `get_coverage_period` response)
- `tracking[]` → Array of all accumulator entries
- `planYear` → Calendar year (e.g., "2025")
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_get_member_profile_enrichment() -> ToolGuide:
    """Enrichment for get_member_profile tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-member-profile",
        name="Get Member Profile Tool Enrichment",
        description="Provides additional context for using get_member_profile",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_member_profile"],
        guide_content="""
## Member Profile Data

**Relationship Codes (`member.relationship.identifier`):**
- `"SUBSCR"` = Subscriber (primary member)
- `"CHILD"` = Dependent child
- `"SPOU"` = Spouse

**Member Preferences:**
- `language`: `"en-us"` (default)
- `emailOptIn`: Boolean
- `smsOptIn`: Boolean
- `accessibility`: `"True"`, `"large_text"`, or `None`

**PCP Provider ID:**
- Default: `"PRV-0106"` (Park Slope Primary Care)
- Can be overridden with `pcp_provider_id` parameter

**Active Coverage Filter:**
- `active_only=True` (default): Returns only active coverage household members
- `active_only=False`: Returns all members including inactive coverage

**Key Fields:**
- `member.identity.primaryId` → Member unique identifier (was: `member.mbrUid`)
- `member.identifiers.accountId` → Healthcare/subscriber ID (was: `member.hcId`)
- `member.givenName` / `member.familyName` → Member name (was: `member.firstNm` / `member.lastNm`)
- `member.birthDate` → Date of birth (was: `member.dob`)
- `preferences` → Member preferences object
- `pcpProviderId` → Primary Care Provider ID
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_set_member_preferences_enrichment() -> ToolGuide:
    """Enrichment for set_member_preferences tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-set-preferences",
        name="Set Member Preferences Tool Enrichment",
        description="Provides additional context for using set_member_preferences",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_set_member_preferences"],
        guide_content="""
## Required Parameters

- `memberId`: Required — extract from user context (the member's ID provided at session start)

## Member Preferences

**Language Values:**
- `"en-us"` = English (US) - default
- Other locale codes supported

**Preference Fields:**
- `language`: Optional string (e.g., "en-us")
- `emailOptIn`: Optional boolean
- `smsOptIn`: Optional boolean
- `accessibility`: Not settable via API (preserved from existing)

**Behavior:**
- Only provided parameters are updated
- Unspecified parameters retain current values
- If member doesn't exist in preferences DB, creates new entry with defaults
- Maps accountId to personId automatically if needed

**Default Values (if no existing preferences):**
- `language`: "en-us"
- `emailOptIn`: False
- `smsOptIn`: False
- `accessibility`: None
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


def create_get_medical_information_enrichment() -> ToolGuide:
    """Enrichment for get_medical_information tool."""
    return ToolGuide(
        type=PolicyType.TOOL_GUIDE,
        id="oak-enrich-medical-information",
        name="Get Medical Information Tool Enrichment",
        description="Provides additional context for using get_medical_information",
        triggers=[
            AlwaysTrigger(type="always"),
        ],
        target_tools=["oak_health_insurance_get_medical_information"],
        guide_content="""
## Medical Information Topics

**Supported Query Topics (case-insensitive):**
- `"high blood pressure"` → 8 articles on hypertension
- `"diabetes"` → 6 articles on diabetes
- `"knee surgery"` → 4 articles on knee surgery

**Fuzzy Matching:**
- If exact match not found, searches for topics where query is contained in topic name
- Example: "blood pressure" matches "high blood pressure"

**Article Structure:**
- `id`: Article identifier (e.g., "htn-001", "dm-002")
- `url`: Full article URL
- `title`: Multi-language title (en-us, en-ca, es-us)
- `abstract`: Multi-language abstract

**Pagination:**
- `page_index`: Zero-based (default 0)
- `size`: Page size (default 5)
- `status`: "OK", "NO_RESULTS", or "PAGE_OUT_OF_RANGE"

**Fallback Behavior:**
- If no seeded articles found, generates 6 generic articles
- Generic articles cover: Overview, Symptoms, Causes, Diagnosis, Treatment, Self-care

**Key Fields:**
- `items[]` → Array of MedicalArticle objects
- `status` → Response status indicating result state
""",
        prepend=False,
        priority=5,
        enabled=True,
    )


# ===== EXPORT ALL POLICIES =====


def get_all_oak_policies() -> List:
    """Get all Oak Health Insurance policies."""
    return [
        # Playbooks
        create_claims_eob_pdf_playbook(),
        create_find_care_providers_playbook(),
        create_benefits_with_providers_playbook(),
        create_benefit_details_playbook(),
        create_coverage_and_providers_playbook(),
        create_search_benefits_playbook(),
        create_payment_playbook(),
        create_family_member_claims_playbook(),
        create_plan_information_playbook(),
        # Tool Enrichments
        create_coverage_period_enrichment(),
        create_search_benefits_enrichment(),
        create_find_care_specialty_enrichment(),
        create_find_care_suggestions_enrichment(),
        create_get_benefit_details_enrichment(),
        create_get_plan_information_enrichment(),
        create_payment_tools_enrichment(),
        create_get_member_claims_enrichment(),
        create_get_claim_details_enrichment(),
        create_get_claim_eob_pdf_enrichment(),
        create_get_benefit_accumulators_enrichment(),
        create_get_member_profile_enrichment(),
        create_set_member_preferences_enrichment(),
        create_get_medical_information_enrichment(),
    ]
