from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ===== Request Models =====
class Location(BaseModel):
    city: Optional[str] = None
    distance: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    zipCode: Optional[str] = None


class GetMemberClaimsRequest(BaseModel):
    memberId: str = Field(..., description="Member ID to fetch claims for")
    location: Optional[Location] = None


# ===== Shared Models =====


class CodeNameDesc(BaseModel):
    code: str
    name: str
    description: str


class Patient(BaseModel):
    mbrUid: str
    hcId: str
    firstNm: str
    lastNm: str
    dob: str  # YYYY-MM-DD


class Amount(BaseModel):
    allowedAmt: Optional[str] = None
    coinsuranceAmt: Optional[str] = None
    copayAmt: Optional[str] = None
    deductibleAmt: Optional[str] = None
    mbrResponsibilityAmt: Optional[str] = None
    providerResponsibilityAmt: Optional[str] = None
    notCoveredAmt: Optional[str] = None
    planSavingsAmt: Optional[str] = None
    planDiscountAmt: Optional[str] = None
    paidAmt: Optional[str] = None
    totalChargeAmt: Optional[str] = None
    totGrossAmt: Optional[str] = None
    chargeAmt: Optional[str] = None


class Provider(BaseModel):
    professionalNm: Optional[str] = None
    taxId: Optional[str] = None


# ===== Detailed models for get_claim_details =====


class ProcedureCd(BaseModel):
    code: str


class DiagnosisCode(BaseModel):
    code: str


class DiagnosesGroup(BaseModel):
    diagnosisCd: List[DiagnosisCode]


class ServiceLine(BaseModel):
    serviceStartDt: str
    serviceEndDt: str
    allowedAmt: Optional[str] = None
    deductibleAmt: Optional[str] = None
    coinsuranceAmt: Optional[str] = None
    copayAmt: Optional[str] = None
    mbrResponsibilityAmt: Optional[str] = None
    notCoveredAmt: Optional[str] = None
    planSavingsAmt: Optional[str] = None
    planDiscountAmt: Optional[str] = None
    chargeAmt: Optional[str] = None
    paidAmt: Optional[str] = None
    procedureCd: ProcedureCd
    diagnoses: List[DiagnosesGroup]


class Eob(BaseModel):
    eobUid: str
    sorCd: str
    eobMbrId: str
    eobDt: str
    eobSequenceNbr: str
    checkNbr: Optional[str] = None
    checkDt: Optional[str] = None
    clmId: str
    serviceStartDt: str
    serviceEndDt: str
    clmProcessDt: str
    subscriberNm: str
    patientNm: str
    legacyId: Optional[str] = None
    underwritingStateCd: Optional[str] = None


class Claim(BaseModel):
    clmUid: str
    clmId: str
    clmRefId: str
    cdhpInd: Literal["Y", "N"]
    enableBillPay: Literal["Y", "N"]
    clmSourceCd: CodeNameDesc
    clmClassCd: CodeNameDesc
    clmTypeCd: CodeNameDesc
    clmStatusCd: CodeNameDesc
    clmSensitiveInd: Literal["Y", "N"]
    capitatedServiceInd: Literal["Y", "N"]
    networkId: Optional[str] = None
    clmStartDt: str
    clmEndDt: str
    clmReceiveDt: str
    clmProcessDt: str
    patient: Patient
    amount: Amount
    servicingProvider: Provider
    billingProvider: Provider
    serviceLines: Optional[List[ServiceLine]] = None
    sensitiveForMinorInd: Optional[str] = None
    eobs: Optional[List[Eob]] = None


# ===== Response Models for claims =====


class PageInfo(BaseModel):
    size: int
    totalElements: int
    totalPages: int
    number: int


class ClaimsResponse(BaseModel):
    metadata: dict
    claims: List[Claim]


# ===== Models for get_coverage_period =====


class Vendor(BaseModel):
    vendorNm: str


class CoverageTypeEntry(BaseModel):
    coverageTypeCd: CodeNameDesc
    vendor: List[Vendor]


class RelationshipCd(BaseModel):
    code: str
    name: str
    description: str


class GenderCd(BaseModel):
    code: str
    name: str
    description: str


class MemberCoverage(BaseModel):
    mbrUid: str
    firstNm: str
    middleNm: Optional[str] = None
    lastNm: str
    dob: str
    relationshipCd: RelationshipCd
    effectiveDt: str
    terminationDt: Optional[str] = None
    statusCd: CodeNameDesc
    coverageTypeCd: List[CodeNameDesc]
    mbrSequenceNbr: str
    subscriberId: str
    genderCd: GenderCd


class CoverageEntry(BaseModel):
    coverageKey: str
    effectiveDt: str
    terminationDt: Optional[str] = None
    maxOOPSalaryInd: str
    isCoupeHealth: bool
    minorAvailable: bool
    enrollmentTypeCd: CodeNameDesc
    statusCd: CodeNameDesc
    coverageType: List[CoverageTypeEntry]
    planNm: str
    benefitSystemId: str
    member: List[MemberCoverage]
    bnftYearCd: str
    healthcareArgmtCd: CodeNameDesc


class EligibilityEntry(BaseModel):
    hcId: str
    contractId: str
    contractUid: str
    groupId: str
    groupNm: str
    effectiveDt: str
    statusCd: CodeNameDesc
    brandCd: CodeNameDesc
    sourceSystemId: str
    coverage: List[CoverageEntry]


class CoveragePeriodResponse(BaseModel):
    eligibility: List[EligibilityEntry]


# ===== Models for get_plan_information =====


class BenefitPeriod(BaseModel):
    cd: str
    desc: str


class BenefitItem(BaseModel):
    cd: str
    value: str
    unit: Optional[str] = None
    desc: str
    optionNm: Optional[str] = None
    optionDesc: Optional[str] = None


class CostShareEntry(BaseModel):
    benefit: BenefitItem
    coverageLevel: Optional[str] = None
    coverageCd: Optional[str] = None
    timePeriod: Optional[str] = None


class NetworkPlan(BaseModel):
    cd: str
    desc: str
    costShare: List[CostShareEntry]


class ValueBasedProviderInfo(BaseModel):
    coverageFlag: str


class PlanInformationResponse(BaseModel):
    contractCd: str
    contractState: str
    startDt: str
    endDt: str
    marketSegment: str
    planType: str
    benefitPeriod: BenefitPeriod
    valueBasedProviderInfo: ValueBasedProviderInfo
    network: List[NetworkPlan]


# ===== Models for search_benefits =====


class CostShareKV(BaseModel):
    type: str
    value: str


class NetworkShare(BaseModel):
    code: Literal["INN", "OON"]
    type: Literal["In Network", "Out of Network"]
    deductibleApplies: str
    precertRequired: str
    costshares: List[CostShareKV]


class POS(BaseModel):
    posCd: Optional[str] = None
    posDesc: str


class Situation(BaseModel):
    pos: List[POS]
    networks: List[NetworkShare]


class BenefitDetail(BaseModel):
    benefitNm: str
    benefitType: str
    specialtyType: List[str]
    benefitSysID: str
    situations: List[Situation]


class ServiceEntry(BaseModel):
    categoryNm: str
    benefits: List[BenefitDetail]


class CategoryEntry(BaseModel):
    services: List[ServiceEntry]


class ServiceCategory(BaseModel):
    planType: str
    categories: List[CategoryEntry]


class AssociatedTreatment(BaseModel):
    code: str
    name: str


class BenefitResult(BaseModel):
    mcid: str
    contractUID: str
    contractCd: str
    docID: str
    effectiveDt: str
    inquiryUsed: str
    serviceCategory: List[ServiceCategory]
    associatedtreatments: Optional[List[AssociatedTreatment]] = None


class BenefitsSearchResponse(BaseModel):
    benefitResults: List[BenefitResult]


# --- find_care_specialty models ---

from typing import List, Optional

from pydantic import BaseModel


class ProviderAddressBlock(BaseModel):
    businessName: str
    addressId: str
    addressOne: str
    addressTwo: Optional[str] = None
    county: Optional[str] = None
    country: str
    distance: float  # computed server-side (miles)
    latitude: str  # store as string to match example
    longitude: str  # store as string to match example
    phone: Optional[str] = None
    email: Optional[str] = None
    city: str
    state: str
    postalCode: str


class ProviderLocation(BaseModel):
    address: ProviderAddressBlock


class ProviderTaxonomy(BaseModel):
    code: str
    name: str
    description: str


class ProviderSpecialty(BaseModel):
    taxonomies: List[ProviderTaxonomy]
    specialtyCategories: List[str]  # e.g., ["25", "231", "75"]


class ProviderNetworkStatus(BaseModel):
    status: str  # e.g., "TP_INNETWORK"
    accept_new_patients: bool
    coverages: List[str]  # e.g., ["MED"]


class ProviderOut(BaseModel):
    id: str
    providerName: str
    location: ProviderLocation
    specialty: ProviderSpecialty
    networkStatus: ProviderNetworkStatus


class FindCareSpecialtyResponse(BaseModel):
    providers: List[ProviderOut]


# --- get_benefit_details models (missing classes) ---

from typing import List, Optional

from pydantic import BaseModel


class DetailCostShareKV(BaseModel):
    type: str
    value: str


class DetailNetworkShare(BaseModel):
    code: str  # e.g., "INN", "OON"
    type: str  # e.g., "In Network", "Out of Network"
    deductibleApplies: str
    precertRequired: str
    costshares: List[DetailCostShareKV]


class DetailPOS(BaseModel):
    posCd: Optional[str] = None
    posDesc: str


class DetailSituation(BaseModel):
    pos: List[DetailPOS]
    diagnosisCd: List[str]
    networks: List[DetailNetworkShare]


class ServiceBenefitDetail(BaseModel):
    benefitNm: str
    benefitType: str
    specialtyType: List[str]
    srvcDefnId: List[str]
    situations: List[DetailSituation]


class ServiceDetailsGroup(BaseModel):
    categoryNm: str
    service: List[ServiceBenefitDetail]


class ServiceCategoryDetails(BaseModel):
    planType: str
    services: List[ServiceDetailsGroup]


class PlanLevelBenefitsGroup(BaseModel):
    networks: List[DetailNetworkShare]


class PlanLevelEntry(BaseModel):
    planType: str
    benefits: List[PlanLevelBenefitsGroup]


class BenefitDetailsResult(BaseModel):
    mcid: str
    contractUID: str
    effectiveDt: str
    benefitSysId: str
    serviceCategory: List[ServiceCategoryDetails]
    planLevel: List[PlanLevelEntry]


class BenefitsDetailsResponse(BaseModel):
    benefitResults: List[BenefitDetailsResult]


# --- find_care_suggestions models ---

from typing import Any, List, Optional

from pydantic import BaseModel


class SuggestionCriteria(BaseModel):
    taxonomyList: List["ProviderTaxonomy"]  # reuse provider taxonomy model
    specialtyCategoryList: List[CodeNameDesc]
    genderList: List[str] = []
    languageList: List[CodeNameDesc] = []
    providerName: Optional[str] = ""
    ableToServeAsPcp: Optional[bool] = False
    acceptsNewPatient: Optional[bool] = False
    npi: Optional[str] = ""


class SuggestionItem(BaseModel):
    text: str
    type: str  # e.g., SPECIALTY, PROVIDER_NAME, PROCEDURE
    score: float
    criteria: SuggestionCriteria
    procedureCode: Optional[str] = None
    medicalCode: Optional[str] = None
    metaData: Dict[str, Any] = {}
    dplQueryParams: Dict[str, str] = {}  # params to pass to find_care_specialty


class LocationDetails(BaseModel):
    city: Optional[str] = ""
    countyCode: Optional[str] = ""
    countyName: Optional[str] = ""
    displayName: Optional[str] = ""
    distance: Optional[str] = ""
    fipsStCd: Optional[str] = ""
    latitude: Optional[str] = ""
    locationType: Optional[str] = "COORDINATE"
    longitude: Optional[str] = ""
    stateCode: Optional[str] = ""
    stateName: Optional[str] = ""
    zipCode: Optional[str] = ""


class FindCareSuggestionsResponse(BaseModel):
    primarySearchIntent: str  # SPECIALTY | PROCEDURE | PROVIDER_NAME | CONDITION
    suggestionList: List[SuggestionItem]
    locationDetails: LocationDetails


# --- get_medical_information models ---


class ConsumerText(BaseModel):
    # Multilingual consumer strings; keys are locales like 'en-us', 'en-ca', 'es-us'
    consumer: Dict[str, str]


class MedicalArticle(BaseModel):
    id: str
    type: str = "article"
    title: ConsumerText
    abstract: ConsumerText
    url: str


class MedicalInformationResponse(BaseModel):
    status: str
    items: List[MedicalArticle]


# --- Billing ---


class BillingItem(BaseModel):
    clmUid: str
    clmId: str
    dueAmt: str
    dueDt: Optional[str] = None
    status: str  # e.g., DUE | PAID | PARTIAL | IN_COLLECTIONS
    canPayOnline: bool


class BillingResponse(BaseModel):
    items: List[BillingItem]
    totals: Dict[str, str]  # e.g., {"dueCount": "3", "totalDueAmt": "345.00"}


# --- EOB PDF ---


class EobPdfItem(BaseModel):
    eobUid: str
    fileUrl: str
    mimeType: str
    sizeBytes: int


class EobPdfResponse(BaseModel):
    clmUid: str
    eobs: List[EobPdfItem]


# --- Payments ---


class CreatePaymentIntentResponse(BaseModel):
    paymentIntentId: str
    status: str  # e.g., REQUIRES_CONFIRMATION
    clientSecret: str
    amount: str
    currency: str = "USD"
    clmUid: Optional[str] = None


class ConfirmPaymentIntentResponse(BaseModel):
    paymentIntentId: str
    status: str  # e.g., SUCCEEDED
    receiptUrl: str
    amount: str
    currency: str = "USD"
    clmUid: Optional[str] = None


# --- Benefit Accumulators ---


class AccumulatorEntry(BaseModel):
    type: str  # DED | OOP
    level: str  # INDV | FAM
    network: str  # INN | OON
    met: str  # "250.00"
    limit: str  # "1000.00"


class BenefitAccumulatorsResponse(BaseModel):
    bnftYear: str
    coverageKey: str
    accumulators: List[AccumulatorEntry]


# --- Member Profile & Preferences ---


class MemberPreferences(BaseModel):
    language: str  # e.g., "en-us"
    emailOptIn: bool
    smsOptIn: bool
    accessibility: Optional[str] = None


class MemberProfile(BaseModel):
    mbrUid: str
    hcId: str
    firstNm: str
    lastNm: str
    dob: str
    relationshipCd: str  # SUBSCR | SPOUS | CHILD


class MemberProfileResponse(BaseModel):
    member: MemberProfile
    preferences: MemberPreferences
    pcpProviderId: Optional[str] = None


# class MemberProfileResponse(BaseModel):
#     member: MemberProfile
#     household: List[MemberProfile]         # includes subscriber + dependents on active coverage
#     preferences: MemberPreferences
#     pcpProviderId: Optional[str] = None


# Optional convenience request type if you prefer body-embedded preferences; not mandatory for our endpoints
class SetMemberPreferencesRequest(GetMemberClaimsRequest):
    preferences: MemberPreferences
