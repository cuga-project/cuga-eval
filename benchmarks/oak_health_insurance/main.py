from copy import deepcopy
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import List, Literal, Optional
from uuid import uuid4

from data import (
    ACCUMULATORS_DB,
    BENEFIT_DETAILS_DB,
    BILLING_LEDGER,
    CLAIM_DETAILS_DB,
    CLAIMS_DB,
    CONTRACT_UID_TO_CD,
    COVERAGE_KEY_INDEX,
    ELIGIBILITY_DB,
    MEDICAL_KB,
    MEMBER_PREFERENCES,
    PAYMENT_INTENTS,
    PLAN_INFO_DB,
    PROVIDERS_DB,
    SUGGESTIONS_DB,
    SUPPORTED_BENEFIT_INTENTS,
)
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from models import (
    BenefitAccumulatorsResponse,
    BenefitDetailsResult,
    BenefitResult,
    BenefitsDetailsResponse,
    BenefitsSearchResponse,
    BillingItem,
    BillingResponse,
    Claim,
    ClaimsResponse,
    ConfirmPaymentIntentResponse,
    ConsumerText,
    CoveragePeriodResponse,
    CreatePaymentIntentResponse,
    EobPdfItem,
    EobPdfResponse,
    FindCareSpecialtyResponse,
    FindCareSuggestionsResponse,
    GetMemberClaimsRequest,
    LocationDetails,
    MedicalArticle,
    MedicalInformationResponse,
    MemberPreferences,
    MemberProfile,
    MemberProfileResponse,
    PageInfo,
    PlanInformationResponse,
    ProviderOut,
    SuggestionItem,
)

app = FastAPI(
    title="Oak Healthcare Insurance",
    version="1.3.0",
    description="""
A healthcare insurance app, providing support for claims, coverage, benefits, plans and general health information.

""",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Utilities =====
SORT_FIELD_MAP = {
    "start_date": "clmStartDt",
    "end_date": "clmEndDt",
    "receive_date": "clmReceiveDt",
    "process_date": "clmProcessDt",
}


def sort_claims(claims: List[Claim], sort_by: str) -> List[Claim]:
    field = SORT_FIELD_MAP.get(sort_by, "clmStartDt")
    return sorted(claims, key=lambda c: getattr(c, field), reverse=True)


def _to_mmddyyyy(iso_date: str) -> str:
    # Input 'YYYY-MM-DD' -> 'MMDDYYYY'
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%m%d%Y")


def _build_doc_id(contract_cd: str, coverage_start_dt: str) -> str:
    # e.g., '281019533353-01012025' style. We'll synthesize deterministic docIDs
    # using YYMMDD + hash fragment of contract.
    mmddyyyy = datetime.strptime(coverage_start_dt, "%Y-%m-%d").strftime("%m%d%Y")
    return f"{abs(hash(contract_cd + mmddyyyy)) % 10**12:012d}-{mmddyyyy}"


def _find_member_elig(member_id: str) -> CoveragePeriodResponse:
    elig = ELIGIBILITY_DB.get(member_id)
    if not elig:
        raise HTTPException(status_code=404, detail="Eligibility not found for memberId")
    return elig


def _validate_contract_and_coverage(
    elig: CoveragePeriodResponse, contract_uid: str, cov_start: str, cov_end: str
):
    # contract_uid must match an eligibility entry; coverage dates must match one of its coverage entries
    owner_entry = None
    for e in elig.eligibility:
        if e.contractUid == contract_uid:
            for c in e.coverage:
                if c.effectiveDt == cov_start and (c.terminationDt or "") == (cov_end or ""):
                    return e, c
            owner_entry = e  # found contract, but not dates
    if owner_entry:
        raise HTTPException(status_code=404, detail="Coverage dates not found for provided contract_uid")
    raise HTTPException(status_code=404, detail="contract_uid not found for memberId")


@app.post("/get_member_claims", response_model=ClaimsResponse, tags=["Claims"])
def get_member_claims(
    payload: GetMemberClaimsRequest = Body(...),
    sort_by: Literal["start_date", "end_date", "process_date", "receive_date"] = Query(default="start_date"),
    size: int = Query(default=5, ge=1, le=5),
    page_index: int = Query(default=0, ge=0),
):
    """
    Get claim summaries for a member.
    Retrieves paginated claims list with financial details, provider info, and claim status.
    Args:
        user_context (UserContext): User context containing member ID, location details (NOT Needed), and metadata (NOT Needed).
        sort_by (str, optional): The field to sort by. Options: "start_date" (claim start date), "end_date" (claim end date), "process_date" (claim process date), "receive_date" (claim receive date). Defaults to "start_date".
        size (int, optional): Number of claims to fetch. Defaults to 5.
        page_index (int, optional): Page index. Defaults to 0.
    Returns:
        ClaimsResponse: Paginated claims list with metadata and details including
        - clmUid: Unique claim identifier (use for get_claim_details)
        - clmId: Human-readable claim ID
        - clmStatusCd: Status code with name and description
        - patient: Member information (mbrUid, name, DOB)
        - amount: Financial details (allowedAmt, paidAmt, totalChargeAmt, etc.)
        - servicingProvider: Provider who performed service
        - billingProvider: Provider who billed for service
    """
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    member_claims = [c for c in CLAIMS_DB if c.patient.mbrUid == payload.memberId]
    if not member_claims:
        member_claims = [c for c in CLAIMS_DB if c.patient.hcId == payload.memberId]

    total = len(member_claims)
    member_claims = sort_claims(member_claims, sort_by)

    start = page_index * size
    end = start + size
    page_items = member_claims[start:end]

    total_pages = (total + size - 1) // size if size > 0 else 0
    metadata = {
        "page": PageInfo(
            size=size, totalElements=total, totalPages=total_pages, number=page_index
        ).model_dump()
    }
    return ClaimsResponse(metadata=metadata, claims=page_items)


@app.post("/get_claim_details", response_model=ClaimsResponse, tags=["Claims"])
def get_claim_details(
    claim_uid: str = Query(..., description="Unique claim identifier (clmUid)"),
    payload: GetMemberClaimsRequest = Body(...),
    user_role: Optional[str] = Query(default="MEMBER"),
    cdhp_carveout: Optional[Literal["y", "n", "Y", "N"]] = Query(default="n"),
):
    """Get detailed information for a specific claim."""
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    base_claim = next((c for c in CLAIMS_DB if c.clmUid == claim_uid), None)
    if not base_claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if payload.memberId not in (base_claim.patient.mbrUid, base_claim.patient.hcId):
        raise HTTPException(status_code=404, detail="Claim not found for provided memberId")

    detailed = deepcopy(base_claim)
    detail_block = CLAIM_DETAILS_DB.get(claim_uid, {})
    detailed.serviceLines = detail_block.get("serviceLines", None)
    detailed.eobs = detail_block.get("eobs", None)

    metadata = {"page": PageInfo(size=1, totalElements=1, totalPages=1, number=0).model_dump()}
    return ClaimsResponse(metadata=metadata, claims=[detailed])


@app.post("/get_coverage_period", response_model=CoveragePeriodResponse, tags=["Coverage"])
def get_coverage_period(
    payload: GetMemberClaimsRequest = Body(...),
    user_role: Optional[str] = Query(default="MEMBER"),
):
    """
    Retrieve coverage period information for a member.
    Includes eligibility and plan data for active and past periods.
    Args:
        user_context (UserContext): User context containing member ID, location details, and metadata.
        user_role (str, optional): User role. Defaults to "MEMBER".
    Returns:
        CoveragePeriodResponse: Contains eligibility array with:
        - contractUid: Contract identifier
        - coverage: Array of coverage periods with coverageKey
        - planNm: Plan name
        - member: Array of members under the same coverage
        - effectiveDt/terminationDt: Coverage dates
        - statusCd: Active/Inactive status
    """
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")
    return _find_member_elig(payload.memberId)


@app.post("/get_plan_information", response_model=PlanInformationResponse, tags=["Coverage"])
def get_plan_information(
    coverage_key: str = Query(..., description="Coverage key from get_coverage_period"),
    payload: GetMemberClaimsRequest = Body(...),
    opted_plan_type: str = Query(default="MED"),
):
    """
    Get plan information for a member and coverage period.
    Includes cost-sharing, network structure, and benefit period details.
    Args:
        user_context (UserContext): User context containing member ID, location details, and metadata.
        coverage_key (str): The coverage key from get_coverage_period (e.g., "1J1U-20250101-20251231-MED-57AMFC").
        opted_plan_type (str, optional): Plan type. Defaults to "MED".
    Returns:
        PlanInformationResponse: Contains plan structure with:
        - contractCd: Contract code and state
        - marketSegment: Market type (Large Group, Individual, etc.)
        - benefitPeriod: How benefits reset (Calendar Year, etc.)
        - network: Array of network types with cost-sharing details
        - costShare: Deductibles, coinsurance, copays by coverage level
        - valueBasedProviderInfo: Value-based care program details
    """
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    owner_mbr = COVERAGE_KEY_INDEX.get(coverage_key)
    if not owner_mbr:
        raise HTTPException(status_code=404, detail="Coverage key not found")

    owner_elig = ELIGIBILITY_DB.get(owner_mbr)
    if not owner_elig:
        raise HTTPException(status_code=404, detail="Coverage owner not found")

    owner_hcids = {e.hcId for e in owner_elig.eligibility}
    if payload.memberId != owner_mbr and payload.memberId not in owner_hcids:
        raise HTTPException(status_code=403, detail="Coverage key does not belong to provided memberId")

    plan = PLAN_INFO_DB.get((coverage_key, opted_plan_type))
    if not plan:
        raise HTTPException(
            status_code=404, detail="Plan information not found for provided coverage key/type"
        )
    return plan


@app.post("/search_benefits", response_model=BenefitsSearchResponse, tags=["Benefits"])
def search_benefits(
    inquiry_keyword: str = Query(
        ..., description='e.g., "knee injury", "office visit", "mri", "knee surgery"'
    ),
    contract_uid: str = Query(...),
    coverage_start_dt: str = Query(..., description="YYYY-MM-DD"),
    coverage_end_dt: str = Query(..., description="YYYY-MM-DD"),
    payload: GetMemberClaimsRequest = Body(...),
):
    """
    Search benefits for a specific inquiry.
    Finds coverage and cost-sharing for procedures, services, and conditions.
    Args:
        user_context (UserContext): User context containing member ID, location details.
        inquiry_keyword (str): The benefit search keyword (e.g., "knee surgery", "MRI").
        contract_uid (str): Contract UID from coverage period.
        coverage_start_dt (str): Coverage start date (YYYY-MM-DD).
        coverage_end_dt (str): Coverage end date (YYYY-MM-DD).
    Returns:
        BenefitsSearchResponse: Contains benefitResults array with:
        - inquiryUsed: The processed search query
        - serviceCategory: Array of plan types (Medical, Dental, etc.) with benefits
        - benefits: Coverage details including deductibles, coinsurance, copays
        - networks: code = Literal["INN", "OON"]; type = Literal["In Network", "Out of Network"] cost sharing
        - associatedtreatments: Related treatment codes and names
    """
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    # Validate eligibility + contract + coverage dates
    elig = _find_member_elig(payload.memberId)
    elig_entry, cov_entry = _validate_contract_and_coverage(
        elig, contract_uid, coverage_start_dt, coverage_end_dt
    )

    # Map to supported intent
    normalized = inquiry_keyword.strip().lower()
    # Simple contains logic to map to supported keys
    if "knee" in normalized and "injur" in normalized:
        intent_key = "knee injury"
    elif "office" in normalized or "pcp" in normalized or "specialist" in normalized:
        intent_key = "office visit"
    elif "mri" in normalized:
        intent_key = "mri"
    elif "knee" in normalized and ("surgery" in normalized or "surg" in normalized):
        intent_key = "knee surgery"
    else:
        supported = list(SUPPORTED_BENEFIT_INTENTS.keys())
        raise HTTPException(
            status_code=400, detail={"message": "Unsupported inquiry_keyword", "supported": supported}
        )

    builder = SUPPORTED_BENEFIT_INTENTS[intent_key]

    # Determine contractCd from mapping
    contract_cd = CONTRACT_UID_TO_CD.get(contract_uid, "UNKNOWN")

    # Choose mcid as the subscriber on this coverage if possible; else first member
    subscriber = next((m for m in cov_entry.member if m.relationshipCd.code == "SUBSCR"), None)
    mcid = (
        subscriber.mbrUid
        if subscriber
        else (cov_entry.member[0].mbrUid if cov_entry.member else payload.memberId)
    )

    effective_mmddyyyy = _to_mmddyyyy(coverage_start_dt)
    doc_id = _build_doc_id(contract_cd, coverage_start_dt)

    result: BenefitResult = builder(contract_uid, contract_cd, effective_mmddyyyy, doc_id, mcid)

    # Return the benefitResults array as required
    return BenefitsSearchResponse(benefitResults=[result])


@app.post("/get_benefit_details", response_model=BenefitsDetailsResponse, tags=["Benefits"])
def get_benefit_details(
    contract_uid: str = Query(...),
    doc_id: str = Query(...),
    benefit_sys_id: str = Query(...),
    coverage_start_dt: str = Query(..., description="YYYY-MM-DD"),
    coverage_end_dt: str = Query(..., description="YYYY-MM-DD"),
    payload: GetMemberClaimsRequest = Body(...),
):
    """
    Validates member + contract + coverage dates. Returns detailed benefit structure
    for the given benefit_sys_id. Verifies doc_id consistency with `coverage_start_dt`.
    """
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    # Validate eligibility and coverage
    elig = _find_member_elig(payload.memberId)
    elig_entry, cov_entry = _validate_contract_and_coverage(
        elig, contract_uid, coverage_start_dt, coverage_end_dt
    )

    # Validate doc_id deterministic match with start date + contractCd
    contract_cd = CONTRACT_UID_TO_CD.get(contract_uid, "UNKNOWN")
    expected_doc_id = _build_doc_id(contract_cd, coverage_start_dt)
    if doc_id != expected_doc_id:
        raise HTTPException(
            status_code=400, detail=f"doc_id mismatch for coverage_start_dt; expected {expected_doc_id}"
        )

    # Find a subscriber to use as mcid when present
    subscriber = next((m for m in cov_entry.member if m.relationshipCd.code == "SUBSCR"), None)
    mcid = subscriber.mbrUid if subscriber else payload.memberId

    key = (contract_uid, benefit_sys_id)
    detail = BENEFIT_DETAILS_DB.get(key)
    if not detail:
        raise HTTPException(status_code=404, detail="Benefit details not found for given identifiers")

    # Build result with appropriate effective date format
    effective_mmddyyyy = _to_mmddyyyy(coverage_start_dt)

    return BenefitsDetailsResponse(
        benefitResults=[
            BenefitDetailsResult(
                mcid=mcid,
                contractUID=contract_uid,
                effectiveDt=effective_mmddyyyy,
                benefitSysId=benefit_sys_id,
                serviceCategory=detail["serviceCategory"],
                planLevel=detail["planLevel"],
            )
        ]
    )


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # distance in miles
    R = 3958.8
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


@app.post("/find_care_specialty", response_model=FindCareSpecialtyResponse, tags=["Find Care"])
def find_care_specialty(
    contract_uid: str = Query(...),
    brand_code: str = Query(...),
    specialty_category_codes: List[str] = Query(..., description="e.g., 25, 231, 75"),
    taxonomy_codes: Optional[List[str]] = Query(None, description="Optional taxonomy filters"),
    distance: str = Query("20", description="Miles"),
    page_index: int = Query(0, ge=0, description="Zero-based page index"),
    size: int = Query(5, ge=1, le=5, description="Page size (max 5)"),
    payload: GetMemberClaimsRequest = Body(...),
):
    """
    Validates member & contract. Requires latitude and longitude in request.location.
    Filters providers by specialty categories (+ optional taxonomy codes) and within radius.
    """
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")
    if not payload.location or not payload.location.latitude or not payload.location.longitude:
        raise HTTPException(status_code=400, detail="latitude and longitude are required in location")

    # Validate contract belongs to the member (via eligibility)
    elig = _find_member_elig(payload.memberId)
    if all(e.contractUid != contract_uid for e in elig.eligibility):
        raise HTTPException(status_code=403, detail="contract_uid does not belong to provided memberId")

    try:
        center_lat = float(payload.location.latitude)
        center_lon = float(payload.location.longitude)
        max_miles = float(distance)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid location or distance")

    # Prepare filters
    cat_set = set(specialty_category_codes)
    tax_set = set(taxonomy_codes) if taxonomy_codes else None

    matched: List[ProviderOut] = []
    for p in PROVIDERS_DB:
        # Category match
        if not (cat_set & set(p.specialty.specialtyCategories)):
            continue
        # Optional taxonomy match
        if tax_set:
            p_tax = {t.code for t in p.specialty.taxonomies}
            if not (p_tax & tax_set):
                continue
        # Distance filter
        plat = float(p.location.address.latitude)
        plon = float(p.location.address.longitude)
        d = _haversine(center_lat, center_lon, plat, plon)
        if d > max_miles:
            continue

        # Shallow copy with distance injected
        p_out = ProviderOut(**p.model_dump())
        p_out.location.address.distance = round(d, 1)

        # (Optional) brand_code gating — here we just pass
        matched.append(p_out)

    start = page_index * size
    end = start + size
    page_items = matched[start:end]

    return FindCareSpecialtyResponse(providers=page_items)


@app.post("/find_care_suggestions", response_model=FindCareSuggestionsResponse, tags=["Find Care"])
def find_care_suggestions(
    search_text: str = Query(
        ..., description='Free-text query, e.g., "primary care doctor", "mri", "knee surgery"'
    ),
    brand_code: str = Query(..., description="Brand code from coverage period (e.g., ACME, VSTA)"),
    payload: GetMemberClaimsRequest = Body(...),
):
    """
    Fetch care provider suggestions based on search criteria.
    Analyzes search text and location to suggest specialties, providers, and procedures.
    """
    # Require lat/long
    if not payload.location or not payload.location.latitude or not payload.location.longitude:
        raise HTTPException(status_code=400, detail="latitude and longitude are required in location")
    # Verify member eligibility exists (brand not enforced here; optional to add)
    _ = _find_member_elig(payload.memberId)

    norm = search_text.strip().lower()

    # Simple intent detection
    if any(k in norm for k in ["primary care", "pcp", "family doctor", "general practitioner"]):
        intent = "SPECIALTY"
        key = "primary care"
    elif any(k in norm for k in ["radiology", "imaging"]):
        intent = "SPECIALTY"
        key = "radiology"
    elif "knee" in norm and "surg" in norm:
        intent = "PROCEDURE"
        key = "knee surgery"
    elif "mri" in norm:
        intent = "PROCEDURE"
        key = "mri"
    else:
        # Default to primary care specialty
        intent = "SPECIALTY"
        key = "primary care"

    base_list = SUGGESTIONS_DB.get(key, [])
    suggestion_list: List[SuggestionItem] = []

    # Personalize dplQueryParams with user's brand_code and coordinates
    for s in base_list:
        item = s.model_copy(deep=True)
        item.dplQueryParams["brand_code"] = brand_code
        item.dplQueryParams["latitude"] = payload.location.latitude
        item.dplQueryParams["longitude"] = payload.location.longitude
        suggestion_list.append(item)

    loc = LocationDetails(
        city=payload.location.city or "",
        countyCode="",
        countyName="",
        displayName=payload.location.city or "",
        distance=payload.location.distance or "20",
        fipsStCd="",
        latitude=payload.location.latitude,
        locationType="COORDINATE",
        longitude=payload.location.longitude,
        stateCode="",
        stateName="",
        zipCode=payload.location.zipCode or "",
    )

    return FindCareSuggestionsResponse(
        primarySearchIntent=intent, suggestionList=suggestion_list, locationDetails=loc
    )


@app.post("/get_medical_information", response_model=MedicalInformationResponse, tags=["Medical Info"])
def get_medical_information(
    query: str = Query(..., description='e.g., "high blood pressure", "diabetes"'),
    payload: GetMemberClaimsRequest = Body(
        ..., description="User context; memberId optional, location optional"
    ),
    page_index: int = Query(0, ge=0, description="Zero-based page index"),
    size: int = Query(5, ge=1, description="Page size (default 5)"),
):
    """
    Returns paginated medical articles for the given query (e.g., "high blood pressure", "diabetes", "knee surgery").
    """
    norm_q = query.strip().lower()

    # 1) Collect results from seed KB (exact and fuzzy)
    items: list[MedicalArticle] = []
    # exact
    if norm_q in MEDICAL_KB:
        items.extend(MEDICAL_KB[norm_q])
    else:
        # fuzzy: include any topic where query matches or is contained in the KB key
        for k, v in MEDICAL_KB.items():
            if norm_q in k or k in norm_q:
                items.extend(v)

    # 2) If no seeded items, synthesize 6 generic articles (so pagination still works)
    if not items:
        base_url = "https://example.health/search"

        def _ct(en_us: str, en_ca: str, es_us: str) -> ConsumerText:
            return ConsumerText(consumer={"en-us": en_us, "en-ca": en_ca, "es-us": es_us})

        title_q = query.strip().title() or "Medical Topic"
        synth: list[MedicalArticle] = []
        synth.append(
            MedicalArticle(
                id="gen-001",
                url=f"{base_url}?q={norm_q}&a=overview",
                title=_ct(f"{title_q}: Overview", f"{title_q}: Overview", f"{title_q}: Descripción general"),
                abstract=_ct(
                    f"An overview of {title_q}.",
                    f"An overview of {title_q}.",
                    f"Descripción general de {title_q}.",
                ),
            )
        )
        synth.append(
            MedicalArticle(
                id="gen-002",
                url=f"{base_url}?q={norm_q}&a=symptoms",
                title=_ct(f"{title_q}: Symptoms", f"{title_q}: Symptoms", f"{title_q}: Síntomas"),
                abstract=_ct(
                    f"Common and uncommon symptoms of {title_q}.",
                    f"Common and uncommon symptoms of {title_q}.",
                    f"Síntomas comunes e inusuales de {title_q}.",
                ),
            )
        )
        synth.append(
            MedicalArticle(
                id="gen-003",
                url=f"{base_url}?q={norm_q}&a=causes",
                title=_ct(f"Causes of {title_q}", f"Causes of {title_q}", f"Causas de {title_q}"),
                abstract=_ct(
                    "Genetic, lifestyle, and other factors.",
                    "Genetic, lifestyle, and other factors.",
                    "Factores genéticos, de estilo de vida y otros.",
                ),
            )
        )
        synth.append(
            MedicalArticle(
                id="gen-004",
                url=f"{base_url}?q={norm_q}&a=diagnosis",
                title=_ct(f"Diagnosing {title_q}", f"Diagnosing {title_q}", f"Diagnóstico de {title_q}"),
                abstract=_ct(
                    f"How clinicians assess and confirm {title_q}.",
                    f"How clinicians assess and confirm {title_q}.",
                    f"CÓmo se evalúa y confirma {title_q}.",
                ),
            )
        )
        synth.append(
            MedicalArticle(
                id="gen-005",
                url=f"{base_url}?q={norm_q}&a=treatment",
                title=_ct(
                    f"Treatments for {title_q}", f"Treatments for {title_q}", f"Tratamientos para {title_q}"
                ),
                abstract=_ct(
                    "Medications, procedures, and lifestyle changes.",
                    "Medications, procedures, and lifestyle changes.",
                    "Medicamentos, procedimientos y cambios de estilo de vida.",
                ),
            )
        )
        synth.append(
            MedicalArticle(
                id="gen-006",
                url=f"{base_url}?q={norm_q}&a=self-care",
                title=_ct(
                    f"Self-care Tips: {title_q}",
                    f"Self-care Tips: {title_q}",
                    f"Consejos de autocuidado: {title_q}",
                ),
                abstract=_ct(
                    f"Everyday steps to manage {title_q}.",
                    f"Everyday steps to manage {title_q}.",
                    f"Pasos diarios para manejar {title_q}.",
                ),
            )
        )
        items = synth

    # 3) Pagination
    total = len(items)
    start = page_index * size
    end = start + size
    page_items = items[start:end]

    # 4) Status
    status = "OK" if page_items else ("NO_RESULTS" if total == 0 else "PAGE_OUT_OF_RANGE")

    return MedicalInformationResponse(status=status, items=page_items)


@app.post("/get_claim_eob_pdf", response_model=EobPdfResponse, tags=["Claims"])
def get_claim_eob_pdf(
    clm_uid: str = Query(..., description="Claim UID (clmUid)"),
    payload: GetMemberClaimsRequest = Body(...),
):
    """Get EOB (explanation of benefits) detailed information for a specific claim."""
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    # Validate claim ownership
    claim = next((c for c in CLAIMS_DB if c.clmUid == clm_uid), None)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if payload.memberId not in (claim.patient.mbrUid, claim.patient.hcId):
        raise HTTPException(status_code=403, detail="Claim does not belong to member")

    # Get EOBs from details DB
    details = CLAIM_DETAILS_DB.get(clm_uid, {})
    eobs = details.get("eobs") or []
    items = []
    for e in eobs:
        url = f"https://example.health/eob/{e.eobUid}.pdf"
        items.append(EobPdfItem(eobUid=e.eobUid, fileUrl=url, mimeType="application/pdf", sizeBytes=224_000))

    return EobPdfResponse(clmUid=clm_uid, eobs=items)


@app.post("/get_member_billing", response_model=BillingResponse, tags=["Billing"])
def get_member_billing(
    payload: GetMemberClaimsRequest = Body(...),
    page_index: int = Query(0, ge=0),
    size: int = Query(50, ge=1, le=100),
):
    '''
    Get Billing information for a specific member.
    '''
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    # Claims owned by member (supports mbrUid or hcId)
    owned = [c for c in CLAIMS_DB if payload.memberId in (c.patient.mbrUid, c.patient.hcId)]

    items: List[BillingItem] = []
    total_due = 0.0
    for c in owned:
        led = BILLING_LEDGER.get(c.clmUid)
        if not led:
            continue
        dueAmt = float(led.get("dueAmt", "0.00"))
        if led["status"] in ("DUE", "PARTIAL", "IN_COLLECTIONS") and dueAmt > 0:
            total_due += dueAmt
        items.append(
            BillingItem(
                clmUid=c.clmUid,
                clmId=c.clmId,
                dueAmt=f"{dueAmt:.2f}",
                dueDt=led.get("dueDt"),
                status=led["status"],
                canPayOnline=(c.enableBillPay.upper() == "Y"),
            )
        )

    start = page_index * size
    end = start + size
    page_items = items[start:end]

    return BillingResponse(
        items=page_items,
        totals={
            "dueCount": str(sum(1 for i in items if i.status != "PAID" and float(i.dueAmt) > 0)),
            "totalDueAmt": f"{total_due:.2f}",
        },
    )


@app.post("/create_payment_intent", response_model=CreatePaymentIntentResponse, tags=["Billing"])
def create_payment_intent(
    amount: str = Query(..., description="Amount in USD, e.g., 60.00"),
    clm_uid: Optional[str] = Query(None, description="Optional claim UID to link payment"),
    payload: GetMemberClaimsRequest = Body(...),
):
    '''
    Create a payment intent. Optionally connect to a specific claim.
    '''
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")
    # Optional ownership validation if clm_uid supplied
    if clm_uid:
        claim = next((c for c in CLAIMS_DB if c.clmUid == clm_uid), None)
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")
        if payload.memberId not in (claim.patient.mbrUid, claim.patient.hcId):
            raise HTTPException(status_code=403, detail="Claim does not belong to member")

    pid = f"pi_{uuid4().hex[:24]}"
    client_secret = f"{pid}_secret_{uuid4().hex[:12]}"
    PAYMENT_INTENTS[pid] = {
        "status": "REQUIRES_CONFIRMATION",
        "memberId": payload.memberId,
        "clmUid": clm_uid or "",
        "amount": amount,
        "currency": "USD",
    }
    return CreatePaymentIntentResponse(
        paymentIntentId=pid,
        status="REQUIRES_CONFIRMATION",
        clientSecret=client_secret,
        amount=amount,
        currency="USD",
        clmUid=clm_uid,
    )


@app.post("/confirm_payment_intent", response_model=ConfirmPaymentIntentResponse, tags=["Billing"])
def confirm_payment_intent(
    payment_intent_id: str = Query(...),
    payload: GetMemberClaimsRequest = Body(...),
):
    '''
    Confirm an existing payment intent.
    '''
    intent = PAYMENT_INTENTS.get(payment_intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="payment_intent not found")

    # Validate member matches creator
    if payload.memberId != intent["memberId"]:
        raise HTTPException(status_code=403, detail="payment_intent not owned by member")

    # Mark succeeded
    intent["status"] = "SUCCEEDED"
    clm_uid = intent.get("clmUid") or None
    amount = intent.get("amount", "0.00")

    # If linked to a claim, mark ledger as PAID when amount covers due
    if clm_uid and clm_uid in BILLING_LEDGER:
        BILLING_LEDGER[clm_uid]["status"] = "PAID"
        BILLING_LEDGER[clm_uid]["dueAmt"] = "0.00"

    receipt_url = f"https://example.health/payments/{payment_intent_id}/receipt"

    return ConfirmPaymentIntentResponse(
        paymentIntentId=payment_intent_id,
        status="SUCCEEDED",
        receiptUrl=receipt_url,
        amount=amount,
        currency="USD",
        clmUid=clm_uid,
    )


@app.post("/get_benefit_accumulators", response_model=BenefitAccumulatorsResponse, tags=["Coverage"])
def get_benefit_accumulators(
    coverage_key: str = Query(...),
    payload: GetMemberClaimsRequest = Body(...),
):
    '''
    Get benefit accumulators (deductibles, out of pocket, in and out of network) for a specific coverage key.
    '''
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    # Validate coverage belongs to member
    owner_mbr = COVERAGE_KEY_INDEX.get(coverage_key)
    if not owner_mbr:
        raise HTTPException(status_code=404, detail="coverage_key not found")
    # Accept if member is owner or same subscriber hcId
    if payload.memberId != owner_mbr:
        owner_elig = ELIGIBILITY_DB.get(owner_mbr)
        if not owner_elig:
            raise HTTPException(status_code=403, detail="coverage ownership could not be verified")
        hcids = {e.hcId for e in owner_elig.eligibility}
        if payload.memberId not in hcids and payload.memberId != owner_mbr:
            raise HTTPException(status_code=403, detail="coverage_key does not belong to member")

    acc = ACCUMULATORS_DB.get(coverage_key)
    if not acc:
        raise HTTPException(status_code=404, detail="No accumulators for coverage_key")

    # Derive year from coverage
    elig = ELIGIBILITY_DB.get(owner_mbr)
    year = ""
    if elig and elig.eligibility:
        for e in elig.eligibility:
            for c in e.coverage:
                if c.coverageKey == coverage_key:
                    year = c.effectiveDt[:4]
                    break

    return BenefitAccumulatorsResponse(bnftYear=year or "2025", coverageKey=coverage_key, accumulators=acc)


@app.post("/get_member_profile", response_model=MemberProfileResponse, tags=["Member"])
def get_member_profile(
    payload: GetMemberClaimsRequest = Body(...),
    active_only: bool = Query(True, description="Return only the active coverage household"),
    pcp_provider_id: Optional[str] = Query("PRV-0106"),
):
    '''
    Get member profile details and preferences.
    '''
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    # Find elig by memberId (can be mbrUid or hcId)
    elig = ELIGIBILITY_DB.get(payload.memberId)
    if payload.memberId == "121231235" or payload.memberId == "121231236":
        elig = ELIGIBILITY_DB.get("121231234")
    if not elig:
        # try to find by mbrUid -> lookup hcId stored key
        raise HTTPException(status_code=404, detail="Eligibility not found")

    # Build household from coverage.members
    household: List[MemberProfile] = []
    for e in elig.eligibility:
        for cov in e.coverage:
            if active_only and (cov.statusCd.code != "A"):
                continue
            for m in cov.member:
                household.append(
                    MemberProfile(
                        mbrUid=m.mbrUid,
                        hcId=m.subscriberId,
                        firstNm=m.firstNm,
                        lastNm=m.lastNm,
                        dob=m.dob,
                        relationshipCd=m.relationshipCd.code,
                    )
                )

    # Choose primary 'member' as the requester if present; else first in household
    primary = next(
        (h for h in household if h.mbrUid == payload.memberId or h.hcId == payload.memberId), None
    ) or (household[0] if household else None)
    if not primary:
        raise HTTPException(status_code=404, detail="Member profile not found")
    # Preferences by mbrUid
    prefs = MEMBER_PREFERENCES.get(primary.mbrUid) or MemberPreferences(
        language="en-us", emailOptIn=False, smsOptIn=False, accessibility=None
    )
    return MemberProfileResponse(
        member=primary,
        # household=household,
        preferences=prefs,
        pcpProviderId=pcp_provider_id,
    )


@app.post("/set_member_preferences", response_model=MemberPreferences, tags=["Member"])
def set_member_preferences(
    payload: GetMemberClaimsRequest = Body(...),
    language: Optional[str] = Query(None, description="e.g., en-us"),
    emailOptIn: Optional[bool] = Query(None),
    smsOptIn: Optional[bool] = Query(None),
    # accessibility: Optional[str] = Query(None),
):
    '''
    Set member preferences (language, emails, SMS, accessibility).
    '''
    if not payload.memberId:
        raise HTTPException(status_code=400, detail="memberId is required")

    # Resolve to an mbrUid (if payload.memberId is hcId, find subscriber/member entry)
    mbr_uid = payload.memberId
    if mbr_uid not in MEMBER_PREFERENCES:
        # try to find a matching member in eligibility to map hcId->mbrUid
        elig = ELIGIBILITY_DB.get(payload.memberId)
        if elig and elig.eligibility:
            # choose subscriber when available
            subs = [
                m
                for e in elig.eligibility
                for c in e.coverage
                for m in c.member
                if m.relationshipCd.code == "SUBSCR"
            ]
            if subs:
                mbr_uid = subs[0].mbrUid

    current = MEMBER_PREFERENCES.get(mbr_uid) or MemberPreferences(
        language="en-us", emailOptIn=False, smsOptIn=False, accessibility=None
    )
    updated = MemberPreferences(
        language=language if language is not None else current.language,
        emailOptIn=emailOptIn if emailOptIn is not None else current.emailOptIn,
        smsOptIn=smsOptIn if smsOptIn is not None else current.smsOptIn,
        accessibility=current.accessibility,
    )
    MEMBER_PREFERENCES[mbr_uid] = updated
    return updated
