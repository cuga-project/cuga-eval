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
                    "get approved claims with EOB",
                    "download EOB PDF for approved claims",
                    "show my last 3 approved claims and share the URL of any EOB PDF",
                    "approved claims with EOB PDF",
                    "get EOB PDF for approved claims",
                ],
                target="intent",
                threshold=0.9,
            ),
        ],
        markdown_content="""# Get Approved Claims with EOB PDFs

## Overview
Retrieve the member's approved claims and obtain the EOB (Explanation of Benefits) PDF documents for each approved claim.

## Steps

### Step 1: Retrieve and Filter Claims
1. Retrieve all claims for the member
2. Filter the results to only include claims with status "Approved"
3. Sort by start date (descending) to get the most recent first
4. Limit to the requested number (typically 3)

**Expected Outcome**: List of approved claims with claim IDs and unique identifiers

### Step 2: Obtain EOB PDFs
1. For each approved claim from Step 1, use the claim's unique identifier
2. Retrieve the EOB PDF document for each approved claim
3. Extract the EOB PDF URLs from the response

**Expected Outcome**: EOB PDF URLs for each approved claim

### Step 3: Format Response
1. Combine claim information with EOB PDF URLs
2. Present in a clear format showing:
   - Claim ID
   - EOB PDF URL (if available)

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
Find in-network care providers based on specialty, location, and other criteria. The member must have location information (latitude and longitude) and active coverage.

## Steps

### Step 1: Retrieve Active Coverage Information
1. Retrieve the member's active coverage information
2. Extract the contract identifier and brand code from the coverage response
3. Verify the coverage is active

**Expected Outcome**: Contract identifier and brand code needed for provider search

### Step 2: Get Care Suggestions (MANDATORY - Do NOT Skip)
1. **ALWAYS** call `find_care_suggestions` first before calling `find_care_specialty`
2. Search for care suggestions using:
   - The search query text (e.g., "primary care doctor", "mri", "knee surgery")
   - The brand code from Step 1
   - The member's location (must include latitude and longitude)
3. Extract specialty category codes from `suggestionList[].criteria.specialtyCategoryList[].code`
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
   - The specialty category codes from Step 2
   - The requested distance in miles (default 20)
   - The member's location (must include latitude and longitude)
2. **CRITICAL - Pagination**: The API returns providers in pages (max 5 per page). To get ALL matching providers:
   - Start with `page_index=0` and `size=5`
   - Continue checking additional pages (`page_index=1`, `page_index=2`, etc.) until:
     - No more providers are returned, OR
     - Fewer than `size` providers are returned (indicating last page)
   - Collect providers from all pages before filtering
   - **Example**: If you need 5+ providers, check at least 2-3 pages to ensure you get all matches
3. Filter results to only include in-network providers:
   - Check `providers[].networkStatus.status == "TP_INNETWORK"` (NOT "INN")
   - Filter based on any additional criteria (e.g., accepting new patients, language)

**Expected Outcome**: Complete list of all matching in-network providers with contact information (from all pages)

### Step 4: Format Response
1. Present providers with:
   - Provider name
   - Practice name and address
   - Phone number (if available)
   - Distance from member location

**Expected Outcome**: Formatted list of providers
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
   - The member's location (must include latitude and longitude)
3. Extract specialty category codes from `suggestionList[].criteria.specialtyCategoryList[].code`
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
   - The requested distance in miles (default 20)
   - The member's location (must include latitude and longitude)
2. **CRITICAL - Pagination**: The API returns providers in pages (max 5 per page). To get ALL matching providers:
   - Start with `page_index=0` and `size=5`
   - Continue checking additional pages (`page_index=1`, `page_index=2`, etc.) until:
     - No more providers are returned, OR
     - Fewer than `size` providers are returned (indicating last page)
   - Collect providers from all pages before filtering
3. Filter results to only include in-network providers:
   - Check `providers[].networkStatus.status == "TP_INNETWORK"` (NOT "INN")
4. Extract provider information including names, addresses, and contact details

**Expected Outcome**: Complete list of all matching in-network providers with contact information (from all pages)

### Step 4: Search Benefits
1. Search for benefits using:
   - The procedure or service keyword (e.g., "knee surgery", "mri", "knee injury", "office visit")
   - The contract identifier from Step 1
   - The coverage start date from Step 1 (extract from `eligibility[].coverage[].effectiveDt`, format: YYYY-MM-DD)
   - The coverage end date from Step 1 (extract from `eligibility[].coverage[].terminationDt`, format: YYYY-MM-DD)
2. Extract benefit information from response:
   - `benefitResults[].benefitSysId` → Benefit system identifier (save for get_benefit_details if needed)
   - `benefitResults[].docId` → Document identifier (save for get_benefit_details if needed)
   - `benefitResults[].networks[].code` → "INN" (In-Network) or "OON" (Out-of-Network)
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
   - Convert city/state names to latitude and longitude coordinates if needed (e.g., "Boston, MA" → coordinates)
   - If no specific location is mentioned, use the member's default location from their profile
   - Location examples: "Boston, MA", "New York, NY", "near Boston", "in San Francisco, CA"
3. Search for care suggestions using:
   - The search query text (e.g., "mri", "knee surgery")
   - The brand code from Step 1
   - The location (latitude and longitude) - either from query or member's default location
4. Extract specialty category codes from `suggestionList[].criteria.specialtyCategoryList[].code`
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
   - The requested distance in miles (default 20, adjust if query specifies distance)
   - The location (latitude and longitude) - same as used in Step 3
3. **CRITICAL - Pagination**: The API returns providers in pages (max 5 per page). To get ALL matching providers:
   - Start with `page_index=0` and `size=5`
   - Continue checking additional pages (`page_index=1`, `page_index=2`, etc.) until:
     - No more providers are returned, OR
     - Fewer than `size` providers are returned (indicating last page)
4. Filter results to only include in-network providers:
   - Check `providers[].networkStatus.status == "TP_INNETWORK"` (NOT "INN")

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
3. Extract the claim unique identifier and amount due for the claim to be paid

**Expected Outcome**: Complete list of all billing items with claim identifiers and amounts due

### Step 2: Create Payment Intent
1. Create a payment intent with:
   - The amount to pay (from Step 1 or specified by user)
   - The claim unique identifier (optional, but recommended to link payment to claim)
2. Extract the payment intent identifier from the response

**Expected Outcome**: Payment intent identifier needed for confirmation

### Step 3: Confirm Payment
1. Confirm the payment intent using the payment intent identifier from Step 2
2. Extract the receipt URL from the response

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
3. Extract the list of covered members from the active coverage entry
4. Identify the target family member by:
   - Matching the name mentioned in the request with the member's first and last name
   - Matching the relationship mentioned (e.g., "daughter", "son") with the member's relationship code ("CHILD" for children)
5. **CRITICAL**: Extract the family member's member ID from the matched member object

**Expected Outcome**: Family member's member ID

### Step 2: Retrieve Claims for Family Member
1. Retrieve claims using the family member's member ID (from Step 1)
   - Use the member ID extracted from coverage, NOT the subscriber's member ID
2. The response will contain claims specific to that family member
3. Sort by start date (descending) to get the most recent claims first

**Expected Outcome**: Claims list for the specific family member

### Step 3: Format Response
1. Present claims specific to the requested family member
2. Include claim status, dates, and amounts
3. For questions about claim approval status, check the claim status code:
   - "APRVD" = Approved
   - "PEND" = Pending
   - "DND" = Denied
   - "PROC" = Processing

**Expected Outcome**: Formatted response with family member's claims and status

## Important Notes
- **ALWAYS** get coverage information first to obtain the family member's member ID
- Do NOT use the subscriber's member ID to get family member claims
- The coverage information contains all covered family members with their unique member IDs
- Each family member has their own member ID that must be used for their claims
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
                    "plan information",
                    "deductibles and out of pocket",
                    "what's my plan deductibles OOP and Coinsurance",
                    "what's my plan deductibles OOP and Copays",
                    "summarize my plan co-payment for In-Network Specialist",
                ],
                target="intent",
                threshold=0.7,
            ),
        ],
        markdown_content="""# Get Plan Information

## Overview
Retrieve plan information including deductibles, out-of-pocket limits, and copays. This provides comprehensive cost-sharing details for the member's plan.

## Steps

### Step 1: Retrieve Active Coverage Information
1. Retrieve the member's active coverage information
2. Extract the coverage key from the active coverage entry
3. Verify the coverage is active

**Expected Outcome**: Coverage key needed for plan information lookup

### Step 2: Retrieve Plan Information
1. Retrieve plan information using:
   - The coverage key from Step 1
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

**Relationship Codes (in `member[].relationshipCd.code`):**
- `"SUBSCR"` = Subscriber (primary member)
- `"CHILD"` = Dependent child
- `"SPOU"` = Spouse

**Gender Codes (in `member[].genderCd.code`):**
- `"M"` = Male
- `"F"` = Female

**Brand Codes (in `eligibility[].brandCd.code`):**
- `"ACME"` = ACME HEALTH
- `"VSTA"` = VISTA HEALTH

**Contract Codes (derived from contractUid):**
- `"1J1U"` = John's contract (Acme)
- `"9Z9X"` = Jane's contract (Vista)

**Coverage Key Format:**
- Pattern: `{contractCd}-{startDate}-{endDate}-{type}-{planId}`
- Example: `"1J1U-20250101-20251231-MED-57AMFC"`
- Use `coverageKey` for `get_plan_information` and `get_benefit_accumulators`

**Key Fields (CRITICAL - Extract these for other tools):**
- `eligibility[].coverage[].statusCd.code == "A"` → Active coverage to use (filter for this)
- `eligibility[].coverage[].coverageKey` → **Extract this** for `get_plan_information` and `get_benefit_accumulators`
  - Example: `"1J1U-20250101-20251231-MED-57AMFC"`
- `eligibility[].coverage[].effectiveDt` → **Extract this** for `search_benefits` (format: YYYY-MM-DD)
- `eligibility[].coverage[].terminationDt` → **Extract this** for `search_benefits` (format: YYYY-MM-DD)
- `eligibility[].contractUid` → **Extract this** for `search_benefits` and `find_care_specialty`
- `eligibility[].brandCd.code` → **Extract this** for `find_care_suggestions` (e.g., "ACME", "VSTA")
- `eligibility[].coverage[].member[]` → List includes subscriber and dependents

**Workflow:**
1. Call `get_coverage_period` first
2. Filter for active coverage by iterating through `eligibility[]` and then `coverage[]` arrays:
   ```python
   for elig in response.get("eligibility", []):
       for cov in elig.get("coverage", []):
           if cov.get("statusCd", {}).get("code") == "A":
               # This is active coverage - extract values from cov and elig
               active_coverage = cov
               active_elig = elig
               break
   ```
   **CRITICAL**: Check `coverage[].statusCd.code == "A"`, NOT `eligibility[].statusCd.code`
   - Status code is `"A"` (single letter), NOT `"ACTIVE"` (full word)
   - An eligibility can have multiple coverage entries (active and inactive), so you must check each coverage entry
3. Extract `coverageKey`, `effectiveDt`, `terminationDt` from the active `coverage` entry
4. Extract `contractUid` and `brandCd.code` from the parent `eligibility` entry
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

**Network Codes (in response `networks[].code`):**
- `"INN"` = In-Network
- `"OON"` = Out-of-Network

**Benefit System IDs (from response, use with `get_benefit_details`):**
- `"82da10ab-c05d-46e1-bf48-ad61ea70eb3d"` = Emergency Room
- `"pcp-ov-11"` = Primary Care Office Visit
- `"spec-ov-11"` = Specialist Office Visit
- `"mri-IMG-OP"` = MRI Outpatient
- `"knee-surg-op"` = Knee Surgery Outpatient

**Associated Treatment Codes:**
- `"CPT:29881"` = Knee arthroscopy
- `"CPT:70551"` = MRI brain without contrast

**Response Fields (CRITICAL - Extract these for get_benefit_details):**
- `benefitResults[].benefitSysId` → Benefit system identifier (e.g., "knee-surg-op", "mri-IMG-OP")
  - **Extract this value** and use as `benefit_sys_id` parameter in `get_benefit_details`
- `benefitResults[].docId` → Document identifier (e.g., "281019533353-01012025")
  - **Extract this value** and use as `doc_id` parameter in `get_benefit_details`
  - Deterministically generated from contractCd + coverage_start_dt
  - **DO NOT generate manually** - always extract from this response
- `benefitResults[].networks[].code` → "INN" or "OON"
- `benefitResults[].associatedtreatments[]` → Related CPT codes and names

**Workflow for get_benefit_details:**
1. Call `search_benefits` first
2. Extract `benefitResults[].docId` and `benefitResults[].benefitSysId` from response
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
2. Extract `specialty_category_codes` from `suggestionList[].criteria.specialtyCategoryList[].code`
   - Example for MRI: Extract code `"75"` from `suggestionList[0].criteria.specialtyCategoryList[0].code`
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
- `distance`: String value in miles (default "20")
- `payload.location` must include `latitude` and `longitude` (required, as numeric strings)

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
- `providers[].location.address.distance` → Distance in miles from member location (calculated)
- `providers[].location.address.phone` → Phone number (e.g., "+1-212-555-0303")
- `providers[].networkStatus.status` → Network status (check for `"TP_INNETWORK"` to filter in-network providers)
- `providers[].networkStatus.accept_new_patients` → Availability (boolean)
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
- `suggestionList[].criteria.specialtyCategoryList[].code` → Category codes (e.g., "25", "220", "231", "75")
  - **For "mri": returns "75"** (Imaging Centers)
  - **For "knee surgery": returns "220"**
  - **For "primary care": returns "25"**
- `suggestionList[].criteria.taxonomyList[].code` → Taxonomy codes (e.g., "207X00000X", "261QR0200X")
  - **For "mri": returns "261QR0200X"** (Radiology Clinic/Center)
  - **For "knee surgery": returns "207X00000X"**
- `suggestionList[].dplQueryParams` → Pre-filled query params for `find_care_specialty`
  - Contains `specialty_category_codes` and `taxonomy_codes` ready to use
- `locationDetails` → Confirmed location (requires `latitude` and `longitude` in payload)

**Workflow (MANDATORY for all provider searches):**
1. **ALWAYS** call this tool first with search text (e.g., "mri", "knee surgery", "primary care")
2. Extract `specialtyCategoryList[].code` values → Use as `specialty_category_codes` in `find_care_specialty`
   - Example for MRI: `suggestionList[0].criteria.specialtyCategoryList[0].code` → `"75"`
3. Extract `taxonomyList[].code` values → Use as `taxonomy_codes` in `find_care_specialty` (optional)
4. **DO NOT** proceed to `find_care_specialty` without first calling this tool and extracting codes
5. **IMPORTANT**: When calling `find_care_specialty`, remember to check multiple pages (see `find_care_specialty` enrichment for pagination details) to get ALL matching providers
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

**Diagnosis Codes (in response `situations[].diagnosisCd[]`):**
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
2. Filter for active coverage (`eligibility[].coverage[].statusCd.code == "A"`)
3. Extract `coverageKey` from `eligibility[].coverage[].coverageKey`
4. Use that exact `coverageKey` value as the `coverage_key` parameter

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

**Payment Intent Status:**
- `"REQUIRES_CONFIRMATION"` → After `create_payment_intent` (initial state)
- `"SUCCEEDED"` → After `confirm_payment_intent` (final state)

**Payment Intent ID Format:**
- Pattern: `"pi_{24-char-hex}"` (e.g., "pi_abc123def456...")
- Client secret format: `"{payment_intent_id}_secret_{12-char-hex}"`

**CRITICAL - Pagination for get_member_billing:**
- The API returns billing items in pages (max 50 items per page)
- **To retrieve ALL billing items, you MUST paginate through all pages:**
  - Start with the first page (`page_index=0`) and continue to subsequent pages
  - Continue fetching pages until you receive an empty response or fewer items than the page size
  - **IMPORTANT**: If a page returns exactly 50 items, you MUST check the next page - only stop when you receive 0 items or fewer than 50 items
  - Collect items from all pages before filtering or processing
- **Why this matters**: Stopping after the first page when it contains exactly 50 items will cause you to miss billing items on subsequent pages, leading to incomplete results

**Workflow:**
1. `get_member_billing` → Get `clmUid` and `dueAmt` (filtered to DUE/PARTIAL/IN_COLLECTIONS)
   - **Remember to paginate** to get all items (see pagination section above)
2. `create_payment_intent` → Get `payment_intent_id` and `clientSecret`
   - Optional: link to `clm_uid` for automatic billing update
3. `confirm_payment_intent` → Get `receipt_url` and update status to "SUCCEEDED"

**Automatic Updates:**
- If `clm_uid` provided in `create_payment_intent`, billing ledger automatically updates to "PAID" when `confirm_payment_intent` succeeds
- `totals.dueCount` = count of items with status != "PAID" and dueAmt > 0
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

**`clmStatusCd.code` values:**
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
- `clmClassCd.code`: `"M"` = Medical Claim
- `clmTypeCd.code`: `"PR"` = Professional Claim
- `clmSourceCd.code`: `"808"` = WGS20

**Sort Options (`sort_by` parameter):**
- `"start_date"` = Sort by claim start date (default)
- `"end_date"` = Sort by claim end date
- `"process_date"` = Sort by processing date
- `"receive_date"` = Sort by receive date

**Constraints:**
- `size`: max 5, default 5
- Default sort: `start_date` descending (most recent first)

**Key Fields:**
- `clmUid` → Use for `get_claim_details` and `get_claim_eob_pdf` (NOT `clmId`)
- `clmId` → Human-readable claim ID (e.g., "2025034AA1251")
- `patient.mbrUid` / `patient.hcId` → Member identifiers
- `patient.name` / `patient.dob` → Filter by family member
- Returns claims for ALL covered family members (subscriber + dependents)
- `amount.paidAmt` → Amount paid by insurance
- `amount.mbrResponsibilityAmt` → Member's responsibility
- `amount.notCoveredAmt` → Amount not covered
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

**Diagnosis Codes (in `serviceLines[].diagnoses[].diagnosisCd[]`):**
- `"Z00.00"` = General health check
- `"M25.50"` = Joint pain
- `"R51"` = Headache
- `"J06.9"` = Upper respiratory infection
- `"I10"` = Hypertension
- `"M54.5"` = Low back pain

**EOB Availability:**
- EOBs only exist for claims with status "APRVD" or "PROC"
- EOB UID format: `"EOB-{first-8-chars-of-clmUid}"`
- Check number: `"100200300"` (only if paidAmt > 0)

**Key Fields:**
- `serviceLines[]` → Detailed service line items with procedure codes
- `eobs[]` → EOB documents (only for approved/processing claims)
- `clmUid` → Required parameter (NOT clmId)
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
- Pattern: `"https://example.health/eob/{eobUid}.pdf"`
- Example: `"https://example.health/eob/EOB-451F6F37.pdf"`

**EOB Properties:**
- `mimeType`: Always `"application/pdf"`
- `sizeBytes`: Typically `224000` (224 KB)
- `eobUid`: Format `"EOB-{first-8-chars-of-clmUid}"`

**Availability:**
- Only available for claims with status "APRVD" or "PROC"
- If claim is "DND" or "PEND", EOB array will be empty
- Each approved claim can have multiple EOBs (sequence numbers)

**Key Fields:**
- `clmUid` → Required parameter (NOT clmId)
- `eobs[].fileUrl` → Direct PDF download URL
- `eobs[].eobUid` → EOB unique identifier
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

**Accumulator Types (`type`):**
- `"DED"` = Deductible
- `"OOP"` = Out-of-Pocket Maximum

**Coverage Levels (`level`):**
- `"INDV"` = Individual
- `"FAM"` = Family

**Network Codes (`network`):**
- `"INN"` = In-Network
- `"OON"` = Out-of-Network

**Accumulator Fields:**
- `met` → Amount already met/toward limit
- `limit` → Maximum limit for the period
- `bnftYear` → Benefit year (extracted from coverage effective date)

**Example Values (from data):**
- Individual INN Deductible: met="250.00", limit="1000.00"
- Individual INN OOP: met="400.00", limit="3000.00"
- Family INN Deductible: met="700.00", limit="3000.00"
- Family INN OOP: met="1200.00", limit="6000.00"
- HMO plans may have: met="0.00", limit="0.00" (no deductible)

**Key Fields:**
- `coverageKey` → Required parameter (from get_coverage_period)
- `accumulators[]` → Array of all accumulator entries
- `bnftYear` → Calendar year (e.g., "2025")
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

**Relationship Codes (`relationshipCd`):**
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
- `member.mbrUid` → Member unique identifier
- `member.hcId` → Healthcare ID (subscriber ID)
- `member.firstNm` / `member.lastNm` → Member name
- `member.dob` → Date of birth
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
- Maps hcId to mbrUid automatically if needed

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


def export_policies_to_json(output_file: str = "oak_policies.json"):
    """Export all policies to a JSON file."""
    import json
    from pathlib import Path

    policies = get_all_oak_policies()

    # Convert to dict for JSON serialization
    policies_dict = []
    for p in policies:
        policy_dict = p.model_dump(mode="json")
        # Convert "type" to "policy_type" to match expected format
        if "type" in policy_dict:
            policy_dict["policy_type"] = policy_dict.pop("type")
        # For playbooks, ensure steps is always an array (frontend expects it)
        if policy_dict.get("policy_type") == "playbook":
            if "steps" not in policy_dict or policy_dict["steps"] is None:
                policy_dict["steps"] = []
        policies_dict.append(policy_dict)

    # Use frontend export format
    output = {"enablePolicies": True, "policies": policies_dict}

    output_path = Path(output_file)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Exported {len(policies)} policies to {output_file}")
    return output_path


if __name__ == "__main__":
    """Export policies to JSON file."""
    export_policies_to_json()
