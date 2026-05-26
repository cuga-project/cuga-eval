from typing import Dict, List, Tuple

from models import (
    POS,
    # additional
    AccumulatorEntry,
    Amount,
    AssociatedTreatment,
    BenefitDetail,
    BenefitItem,
    BenefitPeriod,
    # Search benefits models
    BenefitResult,
    CategoryEntry,
    # Claims models
    Claim,
    CodeNameDesc,
    ConsumerText,
    CostShareEntry,
    CostShareKV,
    CoverageEntry,
    # Coverage/Plan models
    CoveragePeriodResponse,
    CoverageTypeEntry,
    DetailCostShareKV,
    DetailNetworkShare,
    DetailPOS,
    DetailSituation,
    DiagnosesGroup,
    DiagnosisCode,
    EligibilityEntry,
    Eob,
    GenderCd,
    # Medical info
    MedicalArticle,
    MemberCoverage,
    MemberPreferences,
    NetworkPlan,
    NetworkShare,
    Patient,
    PlanInformationResponse,
    PlanLevelBenefitsGroup,
    PlanLevelEntry,
    ProcedureCd,
    Provider,
    ProviderAddressBlock,
    ProviderLocation,
    ProviderNetworkStatus,
    ProviderOut,
    ProviderSpecialty,
    ProviderTaxonomy,
    RelationshipCd,
    ServiceBenefitDetail,
    ServiceCategory,
    ServiceCategoryDetails,
    ServiceDetailsGroup,
    ServiceEntry,
    ServiceLine,
    Situation,
    SuggestionCriteria,
    SuggestionItem,
    ValueBasedProviderInfo,
    Vendor,
)

# =====================================================
# Shared codebooks and helper builders
# =====================================================

CLM_SOURCE_WGS20 = CodeNameDesc(code="808", name="WGS20", description="WGS20")
CLM_CLASS_MEDICAL = CodeNameDesc(code="M", name="Medical Claim", description="Medical Claim")
CLM_TYPE_PROF = CodeNameDesc(code="PR", name="Professional", description="Professional Claim")

STATUS_CODEBOOK = {
    "APRVD": CodeNameDesc(
        code="APRVD",
        name="Approved",
        description="What does an approved claim mean? We finished reviewing this claim and approved the claim under your plan.",
    ),
    "DND": CodeNameDesc(
        code="DND",
        name="Denied",
        description="Why was this claim denied? Common reasons are that we received the same claim twice, or the service performed is not covered under your plan.",
    ),
    "PEND": CodeNameDesc(
        code="PEND",
        name="Pending",
        description="This claim is in review. We’ll update once processing is complete.",
    ),
    "PROC": CodeNameDesc(
        code="PROC", name="Processing", description="We are currently processing this claim."
    ),
}


def amt(
    allowed="10.00",
    coins="0.00",
    copay="0.00",
    ded="0.00",
    mbr="0.00",
    prov="0.00",
    notcov="0.00",
    save="0.00",
    disc="0.00",
    paid="0.00",
    total="10.00",
    gross="0.00",
    charge=None,
) -> Amount:
    return Amount(
        allowedAmt=allowed,
        coinsuranceAmt=coins,
        copayAmt=copay,
        deductibleAmt=ded,
        mbrResponsibilityAmt=mbr,
        providerResponsibilityAmt=prov,
        notCoveredAmt=notcov,
        planSavingsAmt=save,
        planDiscountAmt=disc,
        paidAmt=paid,
        totalChargeAmt=total,
        totGrossAmt=gross,
        chargeAmt=charge,
    )


def masked_providers() -> Tuple[Provider, Provider]:
    servicing = Provider(professionalNm="#%sensitive#%", taxId=None)
    billing = Provider(professionalNm="#%sensitive#%", taxId="#%sensitive#%")
    return servicing, billing


def patient_john() -> Patient:
    return Patient(mbrUid="121231234", hcId="868Y10397", firstNm="JOHN", lastNm="DOE", dob="1970-02-13")


def patient_alt() -> Patient:
    return Patient(mbrUid="882771300", hcId="441Z22001", firstNm="JANE", lastNm="DOE", dob="1985-04-21")


# =====================================================
# Claims seeding + details
# =====================================================


def build_claim(
    clmUid: str,
    clmId: str,
    clmRefId: str,
    status_code: str,
    start: str,
    end: str,
    recv: str,
    proc: str,
    patient: Patient,
    amount: Amount,
    cdhp="N",
    enableBillPay="Y",
    sensitive="Y",
    capitated="N",
    network="Y",
) -> Claim:
    sp, bp = masked_providers()
    return Claim(
        clmUid=clmUid,
        clmId=clmId,
        clmRefId=clmRefId,
        cdhpInd=cdhp,
        enableBillPay=enableBillPay,
        clmSourceCd=CLM_SOURCE_WGS20,
        clmClassCd=CLM_CLASS_MEDICAL,
        clmTypeCd=CLM_TYPE_PROF,
        clmStatusCd=STATUS_CODEBOOK[status_code],
        clmSensitiveInd=sensitive,
        capitatedServiceInd=capitated,
        networkId=network,
        clmStartDt=start,
        clmEndDt=end,
        clmReceiveDt=recv,
        clmProcessDt=proc,
        patient=patient,
        amount=amount,
        servicingProvider=sp,
        billingProvider=bp,
        serviceLines=None,
        sensitiveForMinorInd=None,
        eobs=None,
    )


def seed_claims() -> List[Claim]:
    claims: List[Claim] = []

    # Member 1 (JOHN)
    john = patient_john()
    claims.append(
        build_claim(
            clmUid="451F6F37F295390506B9CF9F6DFBC930",
            clmId="2025034AA1251",
            clmRefId="AB31155D94A4059C8793CE365B429168",
            status_code="APRVD",
            start="2025-02-02",
            end="2025-02-02",
            recv="2025-02-03",
            proc="2025-02-04",
            patient=john,
            amount=amt(allowed="10.00", paid="10.00", total="10.00", save="10.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="63FA69DB119C2E16E21B487BC411E1F2",
            clmId="2025034AA2251",
            clmRefId="4D845B9FCA7EA6FCEC36755C68342BC8",
            status_code="DND",
            start="2025-01-31",
            end="2025-01-31",
            recv="2025-02-03",
            proc="2025-02-04",
            patient=john,
            amount=amt(mbr="10.00", notcov="10.00", total="10.00", allowed="10.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="B1E7C2D8A9F048B7B2A9DCE431F0CD10",
            clmId="2025034AA3251",
            clmRefId="2A0A5B3F9F114F8F8A9D3B1E1AA22F77",
            status_code="PEND",
            start="2025-07-05",
            end="2025-07-05",
            recv="2025-07-06",
            proc="2025-07-06",
            patient=john,
            amount=amt(allowed="200.00", copay="20.00", total="220.00", paid="0.00", save="0.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="9C0C8D7A6B5A4899BC12EF3344CDA123",
            clmId="2025034AA4251",
            clmRefId="7E2F1B4C9DAE4B7E9A1C2D3F4B5C6D70",
            status_code="PROC",
            start="2025-01-20",
            end="2025-01-20",
            recv="2025-01-21",
            proc="2025-01-22",
            patient=john,
            amount=amt(allowed="75.00", paid="60.00", mbr="15.00", total="75.00", save="15.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="9C0C8D7A6B5A489AAC12EF3344CDA1Aq",
            clmId="2025034AA5001",
            clmRefId="7E2F1B4C9DAE4B7E9A1C2D3F4B5C6D11",
            status_code="APRVD",
            start="2025-02-10",
            end="2025-02-10",
            recv="2025-02-11",
            proc="2025-02-12",
            patient=john,
            amount=amt(allowed="90.00", paid="72.00", mbr="18.00", total="90.00", save="18.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="7E2F1B4C9DAAAB7E9A1C2D3F4B5C6D70",
            clmId="2025034AA5002",
            clmRefId="7E2F1B4C9DAE4B7E9A1C2D3F4B5C6D777",
            status_code="DND",
            start="2025-02-12",
            end="2025-02-12",
            recv="2025-02-13",
            proc="2025-02-14",
            patient=john,
            amount=amt(allowed="150.00", notcov="150.00", mbr="150.00", total="150.00", paid="0.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="7E2F1AQQ9DAE4B7E9A1C2D3F4B5C6D70",
            clmId="2025034AA5003",
            clmRefId="7E2F1B4C9DAE4B7E9A1C2D3F4B5CAWT65",
            status_code="PROC",
            start="2025-02-15",
            end="2025-02-15",
            recv="2025-02-16",
            proc="2025-02-17",
            patient=john,
            amount=amt(allowed="65.00", paid="50.00", mbr="15.00", total="65.00", save="15.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="7E2F1B4C9DAE4B7E9A1C2D3F4B5C2687",
            clmId="2025034AA5004",
            clmRefId="7E2F1B4C9DAE4B7E9A1C2D3F12311A",
            status_code="PEND",
            start="2025-02-20",
            end="2025-02-20",
            recv="2025-02-21",
            proc="2025-02-21",
            patient=john,
            amount=amt(allowed="210.00", copay="25.00", mbr="25.00", total="235.00", paid="0.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="7E2F1B4C9DAE4B7E9A1NNT1F4B5C6D70",
            clmId="2025034AA5005",
            clmRefId="7E2F1B4C9DA22B7E9A1C2D3F4B5C6D22",
            status_code="APRVD",
            start="2025-02-25",
            end="2025-02-25",
            recv="2025-02-26",
            proc="2025-02-27",
            patient=john,
            amount=amt(allowed="40.00", paid="40.00", mbr="0.00", total="40.00", save="10.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="9C0C8Q1A6B28411BA3A2333AQW1DA213",
            clmId="2025034AA5006",
            clmRefId="REF9C0C8Q1A6B28411BA3A2333AQW1DA213",
            status_code="APRVD",
            start="2025-03-01",
            end="2025-03-01",
            recv="2025-03-02",
            proc="2025-03-03",
            patient=john,
            amount=amt(allowed="120.00", paid="96.00", mbr="24.00", total="120.00", save="30.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="9C0C8D7A6B5A4899BC12EF3344CDA456",
            clmId="2025034AA5007",
            clmRefId="REF9C0C8D7A6B5A4899BC12EF3344CDA456",
            status_code="DND",
            start="2025-03-05",
            end="2025-03-05",
            recv="2025-03-06",
            proc="2025-03-07",
            patient=john,
            amount=amt(allowed="80.00", notcov="80.00", mbr="80.00", total="80.00", paid="0.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="9C0C8Q1A6B28A2ABA3A2333AQW1DA888",
            clmId="2025034AA5008",
            clmRefId="REF9C0C8Q1A6B28A2ABA3A2333AQW1DA888",
            status_code="PROC",
            start="2025-03-10",
            end="2025-03-10",
            recv="2025-03-11",
            proc="2025-03-12",
            patient=john,
            amount=amt(allowed="55.00", paid="44.00", mbr="11.00", total="55.00", save="11.00"),
        )
    )
    # Dependent patients for claims context (share subscriber's hcId)
    sara_patient = Patient(mbrUid="121231235", hcId=john.hcId, firstNm="SARA", lastNm="DOE", dob="2008-06-10")
    tom_patient = Patient(mbrUid="121231236", hcId=john.hcId, firstNm="TOM", lastNm="DOE", dob="2012-09-15")

    # Claims for SARA (approved & denied)
    claims.append(
        build_claim(
            clmUid="9CUY8Q1A6B28A2ABA3KI333AQW1DA557",
            clmId="2025034CHILD01",
            clmRefId="REF9CUY8Q1A6B28A2ABA3KI333AQW1DA557",
            status_code="APRVD",
            start="2025-02-08",
            end="2025-02-08",
            recv="2025-02-09",
            proc="2025-02-10",
            patient=sara_patient,
            amount=amt(allowed="85.00", paid="85.00", mbr="0.00", total="85.00", save="20.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="9C0C8D7A6B5A499BA3A4F33AQW1DA211",
            clmId="2025034CHILD02",
            clmRefId="REF9C0C8D7A6B5A499BA3A4F33AQW1DA211",
            status_code="PEND",
            start="2025-03-02",
            end="2025-03-02",
            recv="2025-03-03",
            proc="2025-03-04",
            patient=sara_patient,
            amount=amt(allowed="60.00", notcov="60.00", mbr="60.00", total="60.00", paid="0.00"),
        )
    )

    # Claims for TOM (approved & denied)
    claims.append(
        build_claim(
            clmUid="9C0C8D7A6B5A4899BA3A4F3344CDA451",
            clmId="2025034CHILD03",
            clmRefId="REF9C0C8D7A6B5A4899BA3A4F3344CDA451",
            status_code="APRVD",
            start="2025-02-18",
            end="2025-02-18",
            recv="2025-02-19",
            proc="2025-02-20",
            patient=tom_patient,
            amount=amt(allowed="70.00", paid="56.00", mbr="14.00", total="70.00", save="14.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="9C0C8Q1A6B28499BA3A2333AQW1DAADE",
            clmId="2025034CHILD04",
            clmRefId="REF9C0C8Q1A6B28499BA3A2333AQW1DAADE",
            status_code="DND",
            start="2025-03-06",
            end="2025-03-06",
            recv="2025-03-07",
            proc="2025-03-08",
            patient=tom_patient,
            amount=amt(allowed="95.00", notcov="95.00", mbr="95.00", total="95.00", paid="0.00"),
        )
    )

    # Member 2 (JANE)
    jane = patient_alt()
    claims.append(
        build_claim(
            clmUid="A1111111111111111111111111111111",
            clmId="2025034BB1251",
            clmRefId="B2222222222222222222222222222222",
            status_code="APRVD",
            start="2025-01-15",
            end="2025-01-15",
            recv="2025-01-16",
            proc="2025-01-18",
            patient=jane,
            amount=amt(allowed="320.00", paid="280.00", mbr="40.00", total="320.00", save="40.00"),
        )
    )
    claims.append(
        build_claim(
            clmUid="C3333333333333333333333333333333",
            clmId="2025034BB2251",
            clmRefId="D4444444444444444444444444444444",
            status_code="DND",
            start="2025-02-10",
            end="2025-02-10",
            recv="2025-02-11",
            proc="2025-02-12",
            patient=jane,
            amount=amt(allowed="50.00", notcov="50.00", total="50.00", paid="0.00"),
        )
    )
    return claims


def _line(
    start: str,
    end: str,
    proc_code: str,
    dx_codes: List[str],
    allowed: str,
    deductible: str,
    coins: str,
    copay: str,
    mbr: str,
    notcov: str,
    save: str,
    disc: str,
    charge: str,
    paid: str,
) -> ServiceLine:
    return ServiceLine(
        serviceStartDt=start,
        serviceEndDt=end,
        allowedAmt=allowed,
        deductibleAmt=deductible,
        coinsuranceAmt=coins,
        copayAmt=copay,
        mbrResponsibilityAmt=mbr,
        notCoveredAmt=notcov,
        planSavingsAmt=save,
        planDiscountAmt=disc,
        chargeAmt=charge,
        paidAmt=paid,
        procedureCd=ProcedureCd(code=proc_code),
        diagnoses=[DiagnosesGroup(diagnosisCd=[DiagnosisCode(code=c) for c in dx_codes])],
    )


def _eob(
    eobUid: str,
    sorCd: str,
    mbrid: str,
    eobDt: str,
    seq: str,
    checkNbr: str,
    checkDt: str,
    clmId: str,
    start: str,
    end: str,
    procDt: str,
    subscriberNm: str,
    patientNm: str,
    legacyId: str = "",
    uwState: str = "",
) -> Eob:
    return Eob(
        eobUid=eobUid,
        sorCd=sorCd,
        eobMbrId=mbrid,
        eobDt=eobDt,
        eobSequenceNbr=seq,
        checkNbr=checkNbr or None,
        checkDt=checkDt or None,
        clmId=clmId,
        serviceStartDt=start,
        serviceEndDt=end,
        clmProcessDt=procDt,
        subscriberNm=subscriberNm,
        patientNm=patientNm,
        legacyId=legacyId or None,
        underwritingStateCd=uwState or None,
    )


def build_claim_details_index(claims: List[Claim]) -> Dict[str, Dict[str, List]]:
    by_uid: Dict[str, Dict[str, List]] = {}

    def fullname(p: Patient) -> str:
        return f"{p.firstNm} {p.lastNm}".strip()

    for c in claims:
        lines: List[ServiceLine] = [
            _line(
                start=c.clmStartDt,
                end=c.clmEndDt,
                proc_code="99213",
                dx_codes=["Z00.00"],
                allowed=c.amount.allowedAmt or "0.00",
                deductible=c.amount.deductibleAmt or "0.00",
                coins=c.amount.coinsuranceAmt or "0.00",
                copay=c.amount.copayAmt or "0.00",
                mbr=c.amount.mbrResponsibilityAmt or "0.00",
                notcov=c.amount.notCoveredAmt or "0.00",
                save=c.amount.planSavingsAmt or "0.00",
                disc=c.amount.planDiscountAmt or "0.00",
                charge=c.amount.totalChargeAmt or c.amount.chargeAmt or "0.00",
                paid=c.amount.paidAmt or "0.00",
            )
        ]
        eobs: List[Eob] = []

        if c.clmStatusCd.code in ("APRVD", "PROC"):
            eobs.append(
                _eob(
                    eobUid=f"EOB-{c.clmUid[:8]}",
                    sorCd="EOBSYS",
                    mbrid=c.patient.mbrUid,
                    eobDt=c.clmProcessDt,
                    seq="1",
                    checkNbr="100200300" if c.amount.paidAmt and float(c.amount.paidAmt) > 0 else "",
                    checkDt=c.clmProcessDt if c.amount.paidAmt and float(c.amount.paidAmt) > 0 else "",
                    clmId=c.clmId,
                    start=c.clmStartDt,
                    end=c.clmEndDt,
                    procDt=c.clmProcessDt,
                    subscriberNm=fullname(c.patient),
                    patientNm=fullname(c.patient),
                    legacyId=f"LEG-{c.clmId[-4:]}",
                    uwState="NY",
                )
            )

        # Specialize lines per seeded claims to align with summary amounts
        if c.clmUid == "451F6F37F295390506B9CF9F6DFBC930":
            lines = [
                _line(
                    c.clmStartDt,
                    c.clmEndDt,
                    "99213",
                    ["Z00.00"],
                    "10.00",
                    "0.00",
                    "0.00",
                    "0.00",
                    "0.00",
                    "0.00",
                    "10.00",
                    "0.00",
                    "10.00",
                    "10.00",
                )
            ]
        if c.clmUid == "63FA69DB119C2E16E21B487BC411E1F2":
            lines = [
                _line(
                    c.clmStartDt,
                    c.clmEndDt,
                    "97110",
                    ["M25.50"],
                    "10.00",
                    "0.00",
                    "0.00",
                    "0.00",
                    "10.00",
                    "10.00",
                    "0.00",
                    "0.00",
                    "10.00",
                    "0.00",
                )
            ]
        if c.clmUid == "B1E7C2D8A9F048B7B2A9DCE431F0CD10":
            lines = [
                _line(
                    c.clmStartDt,
                    c.clmEndDt,
                    "93000",
                    ["R51"],
                    "200.00",
                    "0.00",
                    "0.00",
                    "20.00",
                    "20.00",
                    "0.00",
                    "0.00",
                    "0.00",
                    "220.00",
                    "0.00",
                )
            ]
        if c.clmUid == "9C0C8D7A6B5A4899BC12EF3344CDA123":
            lines = [
                _line(
                    c.clmStartDt,
                    c.clmEndDt,
                    "80050",
                    ["J06.9"],
                    "75.00",
                    "0.00",
                    "0.00",
                    "0.00",
                    "15.00",
                    "0.00",
                    "15.00",
                    "0.00",
                    "75.00",
                    "60.00",
                )
            ]
        if c.clmUid == "A1111111111111111111111111111111":
            lines = [
                _line(
                    c.clmStartDt,
                    c.clmEndDt,
                    "99214",
                    ["I10"],
                    "320.00",
                    "0.00",
                    "0.00",
                    "0.0",
                    "40.00",
                    "0.0",
                    "40.00",
                    "0.0",
                    "320.00",
                    "280.00",
                )
            ]
        if c.clmUid == "C3333333333333333333333333333333":
            lines = [
                _line(
                    c.clmStartDt,
                    c.clmEndDt,
                    "97140",
                    ["M54.5"],
                    "50.00",
                    "0.00",
                    "0.00",
                    "0.00",
                    "50.00",
                    "50.00",
                    "0.00",
                    "0.00",
                    "50.00",
                    "0.00",
                )
            ]

        by_uid[c.clmUid] = {"serviceLines": lines, "eobs": eobs}

    return by_uid


# =====================================================
# Coverage & Plan seeding
# =====================================================


def _rel(code: str, name: str) -> RelationshipCd:
    return RelationshipCd(code=code, name=name, description=name)


def _gender(code: str, name: str) -> GenderCd:
    return GenderCd(code=code, name=name, description=name)


def seed_eligibility_and_plans():
    """
    Returns:
      ELIGIBILITY_DB: dict[str -> CoveragePeriodResponse] (keyed by mbrUid and hcId)
      COVERAGE_KEY_INDEX: dict[coverage_key -> owner_mbrUid]
      PLAN_INFO_DB: dict[(coverage_key, opted_plan_type) -> PlanInformationResponse]
      CONTRACT_UID_TO_CD: dict[contract_uid -> contractCd]
    """
    ELIGIBILITY_DB: Dict[str, CoveragePeriodResponse] = {}
    COVERAGE_KEY_INDEX: Dict[str, str] = {}
    PLAN_INFO_DB: Dict[tuple, PlanInformationResponse] = {}
    CONTRACT_UID_TO_CD: Dict[str, str] = {}

    # ----- John -----
    john = patient_john()
    john_cov_key_2025 = "1J1U-20250101-20251231-MED-57AMFC"
    john_cov_key_2024 = "1J1U-20240101-20241231-MED-OLDPPO"
    COVERAGE_KEY_INDEX[john_cov_key_2025] = john.mbrUid
    COVERAGE_KEY_INDEX[john_cov_key_2024] = john.mbrUid

    john_coverage_2025 = CoverageEntry(
        coverageKey=john_cov_key_2025,
        effectiveDt="2025-01-01",
        terminationDt="2025-12-31",
        maxOOPSalaryInd="N",
        isCoupeHealth=True,
        minorAvailable=True,
        enrollmentTypeCd=CodeNameDesc(code="ENR", name="Enrolled", description="Enrolled"),
        statusCd=CodeNameDesc(code="A", name="Active", description="Active Coverage"),
        coverageType=[
            CoverageTypeEntry(
                coverageTypeCd=CodeNameDesc(code="MED", name="Medical", description="Medical Coverage"),
                vendor=[Vendor(vendorNm="Acme Health")],
            )
        ],
        planNm="Acme Standard PPO",
        benefitSystemId="BEN-SYS-01",
        member=[
            MemberCoverage(
                mbrUid=john.mbrUid,
                firstNm=john.firstNm,
                middleNm=None,
                lastNm=john.lastNm,
                dob=john.dob,
                relationshipCd=_rel("SUBSCR", "Subscriber"),
                effectiveDt="2025-01-01",
                terminationDt="2025-12-31",
                statusCd=CodeNameDesc(code="A", name="Active", description="Active"),
                coverageTypeCd=[CodeNameDesc(code="MED", name="Medical", description="Medical")],
                mbrSequenceNbr="01",
                subscriberId=john.hcId,
                genderCd=_gender("M", "Male"),
            ),
            MemberCoverage(
                mbrUid="121231235",
                firstNm="SARA",
                middleNm=None,
                lastNm="DOE",
                dob="2008-06-10",
                relationshipCd=_rel("CHILD", "Child"),
                effectiveDt="2025-01-01",
                terminationDt="2025-12-31",
                statusCd=CodeNameDesc(code="A", name="Active", description="Active"),
                coverageTypeCd=[CodeNameDesc(code="MED", name="Medical", description="Medical")],
                mbrSequenceNbr="02",
                subscriberId=john.hcId,
                genderCd=_gender("F", "Female"),
            ),
            MemberCoverage(
                mbrUid="121231236",
                firstNm="TOM",
                middleNm=None,
                lastNm="DOE",
                dob="2012-09-15",
                relationshipCd=_rel("CHILD", "Child"),
                effectiveDt="2025-01-01",
                terminationDt="2025-12-31",
                statusCd=CodeNameDesc(code="A", name="Active", description="Active"),
                coverageTypeCd=[CodeNameDesc(code="MED", name="Medical", description="Medical")],
                mbrSequenceNbr="03",
                subscriberId=john.hcId,
                genderCd=_gender("M", "Male"),
            ),
        ],
        bnftYearCd="CY",
        healthcareArgmtCd=CodeNameDesc(code="PPO", name="Preferred Provider Organization", description="PPO"),
    )

    john_coverage_2024 = CoverageEntry(
        coverageKey=john_cov_key_2024,
        effectiveDt="2024-01-01",
        terminationDt="2024-12-31",
        maxOOPSalaryInd="N",
        isCoupeHealth=False,
        minorAvailable=True,
        enrollmentTypeCd=CodeNameDesc(code="ENR", name="Enrolled", description="Enrolled"),
        statusCd=CodeNameDesc(code="I", name="Inactive", description="Inactive Coverage"),
        coverageType=[
            CoverageTypeEntry(
                coverageTypeCd=CodeNameDesc(code="MED", name="Medical", description="Medical Coverage"),
                vendor=[Vendor(vendorNm="Legacy Health")],
            )
        ],
        planNm="Legacy PPO",
        benefitSystemId="BEN-SYS-00",
        member=[
            MemberCoverage(
                mbrUid=john.mbrUid,
                firstNm=john.firstNm,
                middleNm=None,
                lastNm=john.lastNm,
                dob=john.dob,
                relationshipCd=_rel("SUBSCR", "Subscriber"),
                effectiveDt="2024-01-01",
                terminationDt="2024-12-31",
                statusCd=CodeNameDesc(code="I", name="Inactive", description="Inactive"),
                coverageTypeCd=[CodeNameDesc(code="MED", name="Medical", description="Medical")],
                mbrSequenceNbr="01",
                subscriberId=john.hcId,
                genderCd=_gender("M", "Male"),
            ),
            MemberCoverage(
                mbrUid="121231233",
                firstNm="Jenny",
                middleNm=None,
                lastNm=john.lastNm,
                dob=john.dob,
                relationshipCd=_rel("SPOU", "Spouse"),
                effectiveDt="2024-01-01",
                terminationDt="2024-12-31",
                statusCd=CodeNameDesc(code="I", name="Inactive", description="Inactive"),
                coverageTypeCd=[CodeNameDesc(code="MED", name="Medical", description="Medical")],
                mbrSequenceNbr="01",
                subscriberId=john.hcId,
                genderCd=_gender("F", "Female"),
            ),
        ],
        bnftYearCd="CY",
        healthcareArgmtCd=CodeNameDesc(code="PPO", name="Preferred Provider Organization", description="PPO"),
    )

    john_elig = EligibilityEntry(
        hcId=john.hcId,
        contractId="CNTR-1001",
        contractUid="CONTRACT-UID-JOHN-1001",
        groupId="GRP-ACME",
        groupNm="Acme Corp",
        effectiveDt="2024-01-01",
        statusCd=CodeNameDesc(code="A", name="Active", description="Active at contract level"),
        brandCd=CodeNameDesc(code="ACME", name="ACME HEALTH", description="ACME HEALTH"),
        sourceSystemId="ELIGSYS",
        coverage=[john_coverage_2024, john_coverage_2025],
    )
    ELIGIBILITY_DB[john.mbrUid] = CoveragePeriodResponse(eligibility=[john_elig])
    ELIGIBILITY_DB[john.hcId] = ELIGIBILITY_DB[john.mbrUid]
    CONTRACT_UID_TO_CD["CONTRACT-UID-JOHN-1001"] = "1J1U"

    # ----- JANE -----
    jane = patient_alt()
    jane_cov_key_2025 = "9Z9X-20250101-20251231-MED-INDHMO"
    COVERAGE_KEY_INDEX[jane_cov_key_2025] = jane.mbrUid

    jane_coverage_2025 = CoverageEntry(
        coverageKey=jane_cov_key_2025,
        effectiveDt="2025-01-01",
        terminationDt="2025-12-31",
        maxOOPSalaryInd="N",
        isCoupeHealth=False,
        minorAvailable=False,
        enrollmentTypeCd=CodeNameDesc(code="ENR", name="Enrolled", description="Enrolled"),
        statusCd=CodeNameDesc(code="A", name="Active", description="Active Coverage"),
        coverageType=[
            CoverageTypeEntry(
                coverageTypeCd=CodeNameDesc(code="MED", name="Medical", description="Medical Coverage"),
                vendor=[Vendor(vendorNm="Vista Health")],
            )
        ],
        planNm="Vista HMO Bronze",
        benefitSystemId="BEN-SYS-11",
        member=[
            MemberCoverage(
                mbrUid=jane.mbrUid,
                firstNm=jane.firstNm,
                middleNm=None,
                lastNm=jane.lastNm,
                dob=jane.dob,
                relationshipCd=_rel("SUBSCR", "Subscriber"),
                effectiveDt="2025-01-01",
                terminationDt="2025-12-31",
                statusCd=CodeNameDesc(code="A", name="Active", description="Active"),
                coverageTypeCd=[CodeNameDesc(code="MED", name="Medical", description="Medical")],
                mbrSequenceNbr="01",
                subscriberId=jane.hcId,
                genderCd=_gender("F", "Female"),
            )
        ],
        bnftYearCd="CY",
        healthcareArgmtCd=CodeNameDesc(code="HMO", name="Health Maintenance Organization", description="HMO"),
    )

    jane_elig = EligibilityEntry(
        hcId=jane.hcId,
        contractId="CNTR-2002",
        contractUid="CONTRACT-UID-JANE-2002",
        groupId="IND",
        groupNm="Individual Market",
        effectiveDt="2025-01-01",
        statusCd=CodeNameDesc(code="A", name="Active", description="Active at contract level"),
        brandCd=CodeNameDesc(code="VSTA", name="VISTA HEALTH", description="VISTA HEALTH"),
        sourceSystemId="ELIGSYS",
        coverage=[jane_coverage_2025],
    )
    ELIGIBILITY_DB[jane.mbrUid] = CoveragePeriodResponse(eligibility=[jane_elig])
    ELIGIBILITY_DB[jane.hcId] = ELIGIBILITY_DB[jane.mbrUid]
    CONTRACT_UID_TO_CD["CONTRACT-UID-JANE-2002"] = "9Z9X"

    # ----- Plan Information -----

    # JOHN 2025
    PLAN_INFO_DB[(john_cov_key_2025, "MED")] = PlanInformationResponse(
        contractCd="1J1U",
        contractState="CA",
        startDt="2025-01-01",
        endDt="2025-12-31",
        marketSegment="Large Group",
        planType="Medical",
        benefitPeriod=BenefitPeriod(cd="CalendarYear", desc="Per Calendar Year"),
        valueBasedProviderInfo=ValueBasedProviderInfo(coverageFlag="Not Applicable"),
        network=[
            NetworkPlan(
                cd="ALL",
                desc="ALL",
                costShare=[
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="25",
                            unit=None,
                            desc="Choice",
                            optionNm="DEPELIGMAX",
                            optionDesc="DEPENDENT MAX AGE LIMIT",
                        )
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="Y",
                            unit=None,
                            desc="Choice",
                            optionNm="NEWADDBENPAY",
                            optionDesc="NEWBORN ADDED BEFORE BENEFITS PAY",
                        )
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="Y",
                            unit=None,
                            desc="Choice",
                            optionNm="FORCLMCOVD",
                            optionDesc="FOREIGN CLAIMS COVERED",
                        )
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Unit",
                            value="12",
                            unit="Month(s)",
                            desc="Unit",
                            optionNm="CLMFILE",
                            optionDesc="CLAIM FILING LIMIT",
                        ),
                        timePeriod="From the date of service",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="Y",
                            unit=None,
                            desc="Choice",
                            optionNm="COBAPPLIES",
                            optionDesc="COORDINATION OF BENEFITS APPLIES",
                        )
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="Y",
                            unit=None,
                            desc="Choice",
                            optionNm="TELEHLTH",
                            optionDesc="TELEHEALTH SERVICES AVAILABLE",
                        )
                    ),
                ],
            ),
            NetworkPlan(
                cd="HMO",
                desc="In Network",
                costShare=[
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="N",
                            unit=None,
                            desc="Choice",
                            optionNm="CMDRXDEDCOMB",
                            optionDesc="MED AND RX DED COMBINED",
                        )
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="Y",
                            unit=None,
                            desc="Choice",
                            optionNm="CMEDRXOOPCMB",
                            optionDesc="MEDICAL & RX OOP COMBINED",
                        )
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Deductible",
                            value="500",
                            unit="Dollar(S)",
                            desc="Deductible",
                            optionNm="CFAMDEDDOL",
                            optionDesc="FAMILY DEDUCTIBLE",
                        ),
                        coverageLevel="Family",
                        coverageCd="FAM",
                        timePeriod="Per Calendar Year",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Deductible",
                            value="250",
                            unit="Dollar(S)",
                            desc="Deductible",
                            optionNm="CINDDEDDOL",
                            optionDesc="INDIVIDUAL DEDUCTIBLE",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Calendar Year",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="OutOfPocketMax",
                            value="3000",
                            unit="Dollar(S)",
                            desc="Out of Pocket Maximum",
                            optionNm="CFAMCOPCYMX",
                            optionDesc="FAMILY COPAY MAX",
                        ),
                        coverageLevel="Family",
                        coverageCd="FAM",
                        timePeriod="Per Calendar Year",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="OutOfPocketMax",
                            value="1500",
                            unit="Dollar(S)",
                            desc="Out of Pocket Maximum",
                            optionNm="CSNGLCOPCYMX",
                            optionDesc="SINGLE PARTY COPAY MAX",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Calendar Year",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Copay",
                            value="45",
                            unit="Dollar(S)",
                            desc="Specialist Copay",
                            optionNm="SPEC_COPAY",
                            optionDesc="SPECIALIST OFFICE VISIT COPAY",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Visit",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Copay",
                            value="75",
                            unit="Dollar(S)",
                            desc="Urgent Care Copay",
                            optionNm="URG_COPAY",
                            optionDesc="URGENT CARE FACILITY COPAY",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Visit",
                    ),
                ],
            ),
            NetworkPlan(
                cd="PAR",
                desc="Participating",
                costShare=[
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="Y",
                            unit=None,
                            desc="Choice",
                            optionNm="ECONSULAPLY",
                            optionDesc="ECONSULT INTERPROFESSIONAL CONSLT APPLIES",
                        )
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Coinsurance",
                            value="20",
                            unit="PCT",
                            desc="Imaging Coinsurance",
                            optionNm="IMG_COINS",
                            optionDesc="ADVANCED IMAGING COINSURANCE",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Calendar Year",
                    ),
                ],
            ),
        ],
    )

    # JOHN 2024
    PLAN_INFO_DB[(john_cov_key_2024, "MED")] = PlanInformationResponse(
        contractCd="1J1U",
        contractState="NY",
        startDt="2024-01-01",
        endDt="2024-12-31",
        marketSegment="Large Group",
        planType="Medical",
        benefitPeriod=BenefitPeriod(cd="CalendarYear", desc="Per Calendar Year"),
        valueBasedProviderInfo=ValueBasedProviderInfo(coverageFlag="Not Applicable"),
        network=[
            NetworkPlan(
                cd="INN",
                desc="In-Network",
                costShare=[
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Deductible", value="1500", unit="USD", desc="Individual Deductible"
                        )
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(cd="Coinsurance", value="30", unit="PCT", desc="Coinsurance")
                    ),
                ],
            )
        ],
    )

    # JANE 2025
    PLAN_INFO_DB[(jane_cov_key_2025, "MED")] = PlanInformationResponse(
        contractCd="9Z9X",
        contractState="CA",
        startDt="2025-01-01",
        endDt="2025-12-31",
        marketSegment="Individual",
        planType="Medical",
        benefitPeriod=BenefitPeriod(cd="CalendarYear", desc="Per Calendar Year"),
        valueBasedProviderInfo=ValueBasedProviderInfo(coverageFlag="Not Applicable"),
        network=[
            NetworkPlan(
                cd="ALL",
                desc="ALL",
                costShare=[
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Unit",
                            value="9",
                            unit="Month(s)",
                            desc="Unit",
                            optionNm="CLMFILE",
                            optionDesc="CLAIM FILING LIMIT",
                        ),
                        coverageLevel=None,
                        coverageCd=None,
                        timePeriod="From the date of service",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Choice",
                            value="Y",
                            unit=None,
                            desc="Choice",
                            optionNm="FORCLMCOVD",
                            optionDesc="FOREIGN CLAIMS COVERED",
                        )
                    ),
                ],
            ),
            NetworkPlan(
                cd="HMO",
                desc="In Network",
                costShare=[
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Copay",
                            value="35",
                            unit="Dollar(S)",
                            desc="PCP Copay",
                            optionNm="PCP_COPAY",
                            optionDesc="PRIMARY CARE COPAY",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Visit",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Deductible",
                            value="0",
                            unit="Dollar(S)",
                            desc="Deductible",
                            optionNm="CINDDEDDOL",
                            optionDesc="INDIVIDUAL DEDUCTIBLE",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Calendar Year",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="OutOfPocketMax",
                            value="4500",
                            unit="Dollar(S)",
                            desc="Out of Pocket Maximum",
                            optionNm="CSNGLCOPCYMX",
                            optionDesc="SINGLE PARTY COPAY MAX",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Calendar Year",
                    ),
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Copay",
                            value="10",
                            unit="Dollar(S)",
                            desc="Generic Rx Copay",
                            optionNm="RX_GEN_COPAY",
                            optionDesc="GENERIC PRESCRIPTION COPAY",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Fill",
                    ),
                ],
            ),
            NetworkPlan(
                cd="PAR",
                desc="Participating",
                costShare=[
                    CostShareEntry(
                        benefit=BenefitItem(
                            cd="Coinsurance",
                            value="30",
                            unit="PCT",
                            desc="Outpatient Surgery Coinsurance",
                            optionNm="OPS_COINS",
                            optionDesc="OUTPATIENT SURGERY COINSURANCE",
                        ),
                        coverageLevel="Individual",
                        coverageCd="IND",
                        timePeriod="Per Calendar Year",
                    ),
                ],
            ),
        ],
    )

    return ELIGIBILITY_DB, COVERAGE_KEY_INDEX, PLAN_INFO_DB, CONTRACT_UID_TO_CD


# =====================================================
# Benefit search builders
# =====================================================


def _pos_all() -> List[POS]:
    return [POS(posCd=None, posDesc="ALL")]


def _pos_office() -> List[POS]:
    return [POS(posCd="11", posDesc="Office")]


def build_emergency_er(
    contract_uid: str, contract_cd: str, effective_mmddyyyy: str, doc_id: str, mcid: str
) -> BenefitResult:
    return BenefitResult(
        mcid=mcid,
        contractUID=contract_uid,
        contractCd=contract_cd,
        docID=doc_id,
        effectiveDt=effective_mmddyyyy,
        inquiryUsed="Injury",
        serviceCategory=[
            ServiceCategory(
                planType="Medical",
                categories=[
                    CategoryEntry(
                        services=[
                            ServiceEntry(
                                categoryNm="Emergency Care",
                                benefits=[
                                    BenefitDetail(
                                        benefitNm="Emergency - Emergency Room (Institutional)",
                                        benefitType="Emergency - Emergency Room",
                                        specialtyType=["Institutional"],
                                        benefitSysID="82da10ab-c05d-46e1-bf48-ad61ea70eb3d",
                                        situations=[
                                            Situation(
                                                pos=_pos_all(),
                                                networks=[
                                                    NetworkShare(
                                                        code="INN",
                                                        type="In Network",
                                                        deductibleApplies="Yes",
                                                        precertRequired="N",
                                                        costshares=[
                                                            CostShareKV(type="Coinsurance", value="0%"),
                                                            CostShareKV(
                                                                type="Copayment", value="$400 Per Visit"
                                                            ),
                                                        ],
                                                    ),
                                                    NetworkShare(
                                                        code="OON",
                                                        type="Out of Network",
                                                        deductibleApplies="Covered - At the INN benefit level",
                                                        precertRequired="N",
                                                        costshares=[
                                                            CostShareKV(
                                                                type="Coinsurance",
                                                                value="Covered - At the INN benefit level",
                                                            ),
                                                            CostShareKV(
                                                                type="Copayment",
                                                                value="Covered - At the INN benefit level",
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                            )
                                        ],
                                    )
                                ],
                            )
                        ]
                    )
                ],
            )
        ],
        associatedtreatments=None,
    )


def build_office_visits(
    contract_uid: str, contract_cd: str, effective_mmddyyyy: str, doc_id: str, mcid: str
) -> BenefitResult:
    return BenefitResult(
        mcid=mcid,
        contractUID=contract_uid,
        contractCd=contract_cd,
        docID=doc_id,
        effectiveDt=effective_mmddyyyy,
        inquiryUsed="Office Visit",
        serviceCategory=[
            ServiceCategory(
                planType="Medical",
                categories=[
                    CategoryEntry(
                        services=[
                            ServiceEntry(
                                categoryNm="Professional Physician Services",
                                benefits=[
                                    BenefitDetail(
                                        benefitNm="Office Visits Outpatient Professional - PCP",
                                        benefitType="Office Visits",
                                        specialtyType=["Outpatient Professional"],
                                        benefitSysID="pcp-ov-11",
                                        situations=[
                                            Situation(
                                                pos=_pos_office(),
                                                networks=[
                                                    NetworkShare(
                                                        code="INN",
                                                        type="In Network",
                                                        deductibleApplies="No",
                                                        precertRequired="N",
                                                        costshares=[
                                                            CostShareKV(type="Coinsurance", value="0%"),
                                                            CostShareKV(
                                                                type="Copayment", value="$25 Per Visit"
                                                            ),
                                                        ],
                                                    )
                                                ],
                                            )
                                        ],
                                    ),
                                    BenefitDetail(
                                        benefitNm="Office Visits Outpatient Professional - Specialist",
                                        benefitType="Office Visits",
                                        specialtyType=["Outpatient Professional"],
                                        benefitSysID="spec-ov-11",
                                        situations=[
                                            Situation(
                                                pos=_pos_office(),
                                                networks=[
                                                    NetworkShare(
                                                        code="INN",
                                                        type="In Network",
                                                        deductibleApplies="No",
                                                        precertRequired="N",
                                                        costshares=[
                                                            CostShareKV(type="Coinsurance", value="0%"),
                                                            CostShareKV(
                                                                type="Copayment", value="$55 Per Visit"
                                                            ),
                                                        ],
                                                    )
                                                ],
                                            )
                                        ],
                                    ),
                                ],
                            )
                        ]
                    )
                ],
            )
        ],
        associatedtreatments=None,
    )


def build_mri(
    contract_uid: str, contract_cd: str, effective_mmddyyyy: str, doc_id: str, mcid: str
) -> BenefitResult:
    return BenefitResult(
        mcid=mcid,
        contractUID=contract_uid,
        contractCd=contract_cd,
        docID=doc_id,
        effectiveDt=effective_mmddyyyy,
        inquiryUsed="MRI",
        serviceCategory=[
            ServiceCategory(
                planType="Medical",
                categories=[
                    CategoryEntry(
                        services=[
                            ServiceEntry(
                                categoryNm="Diagnostic Services",
                                benefits=[
                                    BenefitDetail(
                                        benefitNm="MRI (Magnetic Resonance Imaging)",
                                        benefitType="Imaging",
                                        specialtyType=["Outpatient Hospital", "Freestanding Facility"],
                                        benefitSysID="mri-IMG-OP",
                                        situations=[
                                            Situation(
                                                pos=_pos_all(),
                                                networks=[
                                                    NetworkShare(
                                                        code="INN",
                                                        type="In Network",
                                                        deductibleApplies="Yes",
                                                        precertRequired="Y",
                                                        costshares=[
                                                            CostShareKV(type="Coinsurance", value="20%"),
                                                            CostShareKV(type="Copayment", value="$0"),
                                                        ],
                                                    ),
                                                    NetworkShare(
                                                        code="OON",
                                                        type="Out of Network",
                                                        deductibleApplies="Yes",
                                                        precertRequired="N",
                                                        costshares=[
                                                            CostShareKV(type="Coinsurance", value="40%")
                                                        ],
                                                    ),
                                                ],
                                            )
                                        ],
                                    )
                                ],
                            )
                        ]
                    )
                ],
            )
        ],
        associatedtreatments=[AssociatedTreatment(code="CPT:70551", name="MRI brain without contrast")],
    )


def build_knee_surgery(
    contract_uid: str, contract_cd: str, effective_mmddyyyy: str, doc_id: str, mcid: str
) -> BenefitResult:
    return BenefitResult(
        mcid=mcid,
        contractUID=contract_uid,
        contractCd=contract_cd,
        docID=doc_id,
        effectiveDt=effective_mmddyyyy,
        inquiryUsed="Knee Surgery",
        serviceCategory=[
            ServiceCategory(
                planType="Medical",
                categories=[
                    CategoryEntry(
                        services=[
                            ServiceEntry(
                                categoryNm="Surgical Services",
                                benefits=[
                                    BenefitDetail(
                                        benefitNm="Outpatient Surgery - Knee",
                                        benefitType="Surgery",
                                        specialtyType=["Ambulatory Surgical Center", "Outpatient Hospital"],
                                        benefitSysID="knee-surg-op",
                                        situations=[
                                            Situation(
                                                pos=_pos_all(),
                                                networks=[
                                                    NetworkShare(
                                                        code="INN",
                                                        type="In Network",
                                                        deductibleApplies="Yes",
                                                        precertRequired="Y",
                                                        costshares=[
                                                            CostShareKV(
                                                                type="Coinsurance",
                                                                value="20% after deductible",
                                                            )
                                                        ],
                                                    ),
                                                    NetworkShare(
                                                        code="OON",
                                                        type="Out of Network",
                                                        deductibleApplies="Yes",
                                                        precertRequired="Y",
                                                        costshares=[
                                                            CostShareKV(
                                                                type="Coinsurance",
                                                                value="40% after deductible",
                                                            )
                                                        ],
                                                    ),
                                                ],
                                            )
                                        ],
                                    )
                                ],
                            )
                        ]
                    )
                ],
            )
        ],
        associatedtreatments=[AssociatedTreatment(code="CPT:29881", name="Knee arthroscopy")],
    )


SUPPORTED_BENEFIT_INTENTS = {
    "knee injury": build_emergency_er,
    "office visit": build_office_visits,
    "mri": build_mri,
    "knee surgery": build_knee_surgery,
}


# ============ Benefit Details ============


def _detail_pos_all() -> List[DetailPOS]:
    return [DetailPOS(posCd=None, posDesc="ALL")]


def _detail_pos_office() -> List[DetailPOS]:
    return [DetailPOS(posCd="11", posDesc="Office")]


def _plan_level_inn_copay_coins(copay: str, coins: str) -> List[DetailNetworkShare]:
    return [
        DetailNetworkShare(
            code="INN",
            type="In Network",
            deductibleApplies="Depends on benefit",
            precertRequired="N",
            costshares=[
                DetailCostShareKV(type="Copayment", value=copay),
                DetailCostShareKV(type="Coinsurance", value=coins),
            ],
        )
    ]


# BENEFIT_DETAILS_DB key: (contract_uid, benefit_sys_id)
BENEFIT_DETAILS_DB: Dict[tuple, Dict] = {
    # Emergency Room (Institutional)
    ("CONTRACT-UID-JOHN-1001", "82da10ab-c05d-46e1-bf48-ad61ea70eb3d"): {
        "serviceCategory": [
            ServiceCategoryDetails(
                planType="Medical",
                services=[
                    ServiceDetailsGroup(
                        categoryNm="Emergency Care",
                        service=[
                            ServiceBenefitDetail(
                                benefitNm="Emergency - Emergency Room (Institutional)",
                                benefitType="Emergency - Emergency Room",
                                specialtyType=["Institutional"],
                                srvcDefnId=["ER-INST-001"],
                                situations=[
                                    DetailSituation(
                                        pos=_detail_pos_all(),
                                        diagnosisCd=["S86.911A", "T14.90XA"],  # knee/unspecified injury
                                        networks=[
                                            DetailNetworkShare(
                                                code="INN",
                                                type="In Network",
                                                deductibleApplies="Yes",
                                                precertRequired="N",
                                                costshares=[
                                                    DetailCostShareKV(
                                                        type="Copayment", value="$400 Per Visit"
                                                    ),
                                                    DetailCostShareKV(type="Coinsurance", value="0%"),
                                                ],
                                            ),
                                            DetailNetworkShare(
                                                code="OON",
                                                type="Out of Network",
                                                deductibleApplies="Covered - At the INN benefit level",
                                                precertRequired="N",
                                                costshares=[
                                                    DetailCostShareKV(
                                                        type="Copayment",
                                                        value="Covered - At the INN benefit level",
                                                    ),
                                                    DetailCostShareKV(
                                                        type="Coinsurance",
                                                        value="Covered - At the INN benefit level",
                                                    ),
                                                ],
                                            ),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
        "planLevel": [
            PlanLevelEntry(
                planType="Medical",
                benefits=[
                    PlanLevelBenefitsGroup(networks=_plan_level_inn_copay_coins("$400 Per Visit", "0%"))
                ],
            )
        ],
    },
    # Office Visits - PCP
    ("CONTRACT-UID-JOHN-1001", "pcp-ov-11"): {
        "serviceCategory": [
            ServiceCategoryDetails(
                planType="Medical",
                services=[
                    ServiceDetailsGroup(
                        categoryNm="Professional Physician Services",
                        service=[
                            ServiceBenefitDetail(
                                benefitNm="Office Visits Outpatient Professional - PCP",
                                benefitType="Office Visits",
                                specialtyType=["Outpatient Professional"],
                                srvcDefnId=["PCP-11-OV"],
                                situations=[
                                    DetailSituation(
                                        pos=_detail_pos_office(),
                                        diagnosisCd=["Z00.00", "J01.90"],
                                        networks=[
                                            DetailNetworkShare(
                                                code="INN",
                                                type="In Network",
                                                deductibleApplies="No",
                                                precertRequired="N",
                                                costshares=[
                                                    DetailCostShareKV(
                                                        type="Copayment", value="$25 Per Visit"
                                                    ),
                                                    DetailCostShareKV(type="Coinsurance", value="0%"),
                                                ],
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
        "planLevel": [
            PlanLevelEntry(
                planType="Medical",
                benefits=[
                    PlanLevelBenefitsGroup(networks=_plan_level_inn_copay_coins("$25 Per Visit", "0%"))
                ],
            )
        ],
    },
    # Office Visits - Specialist
    ("CONTRACT-UID-JOHN-1001", "spec-ov-11"): {
        "serviceCategory": [
            ServiceCategoryDetails(
                planType="Medical",
                services=[
                    ServiceDetailsGroup(
                        categoryNm="Professional Physician Services",
                        service=[
                            ServiceBenefitDetail(
                                benefitNm="Office Visits Outpatient Professional - Specialist",
                                benefitType="Office Visits",
                                specialtyType=["Outpatient Professional"],
                                srvcDefnId=["SPEC-11-OV"],
                                situations=[
                                    DetailSituation(
                                        pos=_detail_pos_office(),
                                        diagnosisCd=["M25.50"],
                                        networks=[
                                            DetailNetworkShare(
                                                code="INN",
                                                type="In Network",
                                                deductibleApplies="No",
                                                precertRequired="N",
                                                costshares=[
                                                    DetailCostShareKV(
                                                        type="Copayment", value="$55 Per Visit"
                                                    ),
                                                    DetailCostShareKV(type="Coinsurance", value="0%"),
                                                ],
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
        "planLevel": [
            PlanLevelEntry(
                planType="Medical",
                benefits=[
                    PlanLevelBenefitsGroup(networks=_plan_level_inn_copay_coins("$55 Per Visit", "0%"))
                ],
            )
        ],
    },
    # MRI
    ("CONTRACT-UID-JOHN-1001", "mri-IMG-OP"): {
        "serviceCategory": [
            ServiceCategoryDetails(
                planType="Medical",
                services=[
                    ServiceDetailsGroup(
                        categoryNm="Diagnostic Services",
                        service=[
                            ServiceBenefitDetail(
                                benefitNm="MRI (Magnetic Resonance Imaging)",
                                benefitType="Imaging",
                                specialtyType=["Outpatient Hospital", "Freestanding Facility"],
                                srvcDefnId=["IMG-MRI-OP"],
                                situations=[
                                    DetailSituation(
                                        pos=_detail_pos_all(),
                                        diagnosisCd=["R51", "G44.209"],
                                        networks=[
                                            DetailNetworkShare(
                                                code="INN",
                                                type="In Network",
                                                deductibleApplies="Yes",
                                                precertRequired="Y",
                                                costshares=[
                                                    DetailCostShareKV(type="Coinsurance", value="20%"),
                                                    DetailCostShareKV(type="Copayment", value="$0"),
                                                ],
                                            ),
                                            DetailNetworkShare(
                                                code="OON",
                                                type="Out of Network",
                                                deductibleApplies="Yes",
                                                precertRequired="N",
                                                costshares=[
                                                    DetailCostShareKV(type="Coinsurance", value="40%")
                                                ],
                                            ),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
        "planLevel": [
            PlanLevelEntry(
                planType="Medical",
                benefits=[
                    PlanLevelBenefitsGroup(
                        networks=[
                            DetailNetworkShare(
                                code="INN",
                                type="In Network",
                                deductibleApplies="Yes",
                                precertRequired="Y",
                                costshares=[DetailCostShareKV(type="Coinsurance", value="20%")],
                            )
                        ]
                    )
                ],
            )
        ],
    },
    # Knee Surgery (Outpatient)
    ("CONTRACT-UID-JOHN-1001", "knee-surg-op"): {
        "serviceCategory": [
            ServiceCategoryDetails(
                planType="Medical",
                services=[
                    ServiceDetailsGroup(
                        categoryNm="Surgical Services",
                        service=[
                            ServiceBenefitDetail(
                                benefitNm="Outpatient Surgery - Knee",
                                benefitType="Surgery",
                                specialtyType=["Ambulatory Surgical Center", "Outpatient Hospital"],
                                srvcDefnId=["SURG-KNEE-OP"],
                                situations=[
                                    DetailSituation(
                                        pos=_detail_pos_all(),
                                        diagnosisCd=["M23.91", "S83.241A"],
                                        networks=[
                                            DetailNetworkShare(
                                                code="INN",
                                                type="In Network",
                                                deductibleApplies="Yes",
                                                precertRequired="Y",
                                                costshares=[
                                                    DetailCostShareKV(
                                                        type="Coinsurance", value="20% after deductible"
                                                    )
                                                ],
                                            ),
                                            DetailNetworkShare(
                                                code="OON",
                                                type="Out of Network",
                                                deductibleApplies="Yes",
                                                precertRequired="Y",
                                                costshares=[
                                                    DetailCostShareKV(
                                                        type="Coinsurance", value="40% after deductible"
                                                    )
                                                ],
                                            ),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
        "planLevel": [
            PlanLevelEntry(
                planType="Medical",
                benefits=[
                    PlanLevelBenefitsGroup(
                        networks=[
                            DetailNetworkShare(
                                code="INN",
                                type="In Network",
                                deductibleApplies="Yes",
                                precertRequired="Y",
                                costshares=[
                                    DetailCostShareKV(type="Coinsurance", value="20% after deductible")
                                ],
                            )
                        ]
                    )
                ],
            )
        ],
    },
}

# (Optional) mirror of the above for JANE's contract:
for _sys in ["82da10ab-c05d-46e1-bf48-ad61ea70eb3d", "pcp-ov-11", "spec-ov-11", "mri-IMG-OP", "knee-surg-op"]:
    if ("CONTRACT-UID-JANE-2002", _sys) not in BENEFIT_DETAILS_DB:
        BENEFIT_DETAILS_DB[("CONTRACT-UID-JANE-2002", _sys)] = BENEFIT_DETAILS_DB[
            ("CONTRACT-UID-JOHN-1001", _sys)
        ]

# ============ Provider Directory ============

PROVIDERS_DB: List[ProviderOut] = [
    ProviderOut(
        id="PRV-0001",
        providerName="Ethan Cole",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Acme Primary Care Clinic",
                addressId="ADDR-0001",
                addressOne="100 Wellness Way",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,  # will be overwritten per query
                latitude="40.7000",
                longitude="-73.9500",
                phone="+1-212-555-0101",
                email="frontdesk@acme-pcc.example",
                city="Brooklyn",
                state="NY",
                postalCode="11211",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                ),
                ProviderTaxonomy(
                    code="207Q00000X",
                    name="Family Medicine",
                    description="Allopathic & Osteopathic Physicians - Family Medicine",
                ),
            ],
            specialtyCategories=["25"],  # Family/General Practice
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0002",
        providerName="Sophia Ramirez",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Vista Radiology Center",
                addressId="ADDR-0002",
                addressOne="500 Imaging Blvd",
                addressTwo="Suite 200",
                county="Queens",
                country="US",
                distance=0.0,
                latitude="40.7400",
                longitude="-73.8600",
                phone="+1-718-555-0202",
                email=None,
                city="Queens",
                state="NY",
                postalCode="11373",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QR0200X", name="Radiology Clinic/Center", description="Clinic/Center - Radiology"
                ),
                ProviderTaxonomy(
                    code="2085R0202X", name="Radiology, Diagnostic", description="Radiology - Diagnostic"
                ),
            ],
            specialtyCategories=["231", "75"],  # Clinics/Radiology, Imaging centers
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=True, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0003",
        providerName="Liam Bennett",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Northside Orthopedic Group",
                addressId="ADDR-0003",
                addressOne="250 Ortho Park",
                addressTwo=None,
                county="New York",
                country="US",
                distance=0.0,
                latitude="40.7800",
                longitude="-73.9800",
                phone="+1-212-555-0303",
                email="contact@north-ortho.example",
                city="New York",
                state="NY",
                postalCode="10024",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="207X00000X",
                    name="Orthopedic Surgery",
                    description="Allopathic & Osteopathic Physicians - Orthopaedic Surgery",
                ),
            ],
            specialtyCategories=["220"],  # e.g., Surgery/Ortho (mock)
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0004",
        providerName="Olivia Carter",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Harbor Community Health",
                addressId="ADDR-0004",
                addressOne="75 Harbor St",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6800",
                longitude="-73.9700",
                phone="+1-718-555-0404",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11217",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                ),
            ],
            specialtyCategories=["25", "231"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0101",
        providerName="Noah Sullivan",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Greenpoint Family Practice",
                addressId="ADDR-0101",
                addressOne="101 Green Ave",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.7301",
                longitude="-73.9543",
                phone="+1-718-555-1101",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11222",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=True, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0102",
        providerName="Ava Thompson",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Bedford Primary Care",
                addressId="ADDR-0102",
                addressOne="202 Bedford Ave",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.7170",
                longitude="-73.9560",
                phone="+1-718-555-1102",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11249",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                ),
                ProviderTaxonomy(
                    code="207Q00000X",
                    name="Family Medicine",
                    description="Allopathic & Osteopathic Physicians - Family Medicine",
                ),
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=True, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0103",
        providerName="CMason Brooks",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Cobble Hill Medical Group",
                addressId="ADDR-0103",
                addressOne="303 Court St",
                addressTwo="Suite 2",
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6863",
                longitude="-73.9969",
                phone="+1-718-555-1103",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11231",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="207Q00000X",
                    name="Family Medicine",
                    description="Allopathic & Osteopathic Physicians - Family Medicine",
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0104",
        providerName="Isabella Hayes",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Brooklyn Heights Family Health",
                addressId="ADDR-0104",
                addressOne="88 Montague St",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6958",
                longitude="-73.9936",
                phone="+1-718-555-1104",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11201",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0105",
        providerName="Lucas Parker",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Williamsburg Family Medicine",
                addressId="ADDR-0105",
                addressOne="120 Havemeyer St",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.7124",
                longitude="-73.9560",
                phone="+1-718-555-1105",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11211",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="207Q00000X",
                    name="Family Medicine",
                    description="Allopathic & Osteopathic Physicians - Family Medicine",
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=True, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0106",
        providerName="Charlotte Reed",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Park Slope Primary Care",
                addressId="ADDR-0106",
                addressOne="400 7th Ave",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6663",
                longitude="-73.9850",
                phone="+1-718-555-1106",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11215",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=True, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0107",
        providerName="James Foster",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Prospect Heights Family Care",
                addressId="ADDR-0107",
                addressOne="55 Vanderbilt Ave",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6813",
                longitude="-73.9680",
                phone="+1-718-555-1107",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11238",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="207Q00000X",
                    name="Family Medicine",
                    description="Allopathic & Osteopathic Physicians - Family Medicine",
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=True, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0108",
        providerName="Amelia Collins",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Downtown Brooklyn Health",
                addressId="ADDR-0108",
                addressOne="2 MetroTech Center",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6933",
                longitude="-73.9875",
                phone="+1-718-555-1108",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11201",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0109",
        providerName="Henry Mitchell",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Fort Greene Family Practice",
                addressId="ADDR-0109",
                addressOne="141 Greene Ave",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6895",
                longitude="-73.9712",
                phone="+1-718-555-1109",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11238",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="207Q00000X",
                    name="Family Medicine",
                    description="Allopathic & Osteopathic Physicians - Family Medicine",
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0110",
        providerName="Emily Sanders",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Clinton Hill Primary Care",
                addressId="ADDR-0110",
                addressOne="85 Waverly Ave",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6899",
                longitude="-73.9675",
                phone="+1-718-555-1110",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11205",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0111",
        providerName="Alexander Ward",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Sunset Park Family Health",
                addressId="ADDR-0111",
                addressOne="800 5th Ave",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6480",
                longitude="-74.0100",
                phone="+1-718-555-1111",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11232",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="207Q00000X",
                    name="Family Medicine",
                    description="Allopathic & Osteopathic Physicians - Family Medicine",
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
    ProviderOut(
        id="PRV-0112",
        providerName="Grace Morgan",
        location=ProviderLocation(
            address=ProviderAddressBlock(
                businessName="Bushwick Primary Care",
                addressId="ADDR-0112",
                addressOne="900 Bushwick Ave",
                addressTwo=None,
                county="Kings",
                country="US",
                distance=0.0,
                latitude="40.6943",
                longitude="-73.9226",
                phone="+1-718-555-1112",
                email=None,
                city="Brooklyn",
                state="NY",
                postalCode="11221",
            )
        ),
        specialty=ProviderSpecialty(
            taxonomies=[
                ProviderTaxonomy(
                    code="261QP2300X", name="Primary Care Clinic", description="Clinic/Center - Primary Care"
                )
            ],
            specialtyCategories=["25"],
        ),
        networkStatus=ProviderNetworkStatus(
            status="TP_INNETWORK", accept_new_patients=False, coverages=["MED"]
        ),
    ),
]

# ====== Suggestions seeds ======

SUGGESTIONS_DB = {
    # SPECIALTY: Primary Care / Family Practice
    "primary care": [
        SuggestionItem(
            text="Primary Care Doctor near me",
            type="SPECIALTY",
            score=0.96,
            criteria=SuggestionCriteria(
                taxonomyList=[
                    ProviderTaxonomy(
                        code="261QP2300X",
                        name="Primary Care Clinic",
                        description="Clinic/Center - Primary Care",
                    ),
                    ProviderTaxonomy(
                        code="207Q00000X",
                        name="Family Medicine",
                        description="Allopathic & Osteopathic Physicians - Family Medicine",
                    ),
                ],
                specialtyCategoryList=[
                    CodeNameDesc(
                        code="25",
                        name="Family/General Practice",
                        description="Primary care / family practice",
                    )
                ],
            ),
            procedureCode=None,
            medicalCode=None,
            metaData={},
            dplQueryParams={
                "specialty_category_codes": "25",
                "taxonomy_codes": "261QP2300X,207Q00000X",
                "distance": "20",
                "page_index": "0",
                "size": "5",
            },
        ),
    ],
    # SPECIALTY: Imaging / Radiology
    "radiology": [
        SuggestionItem(
            text="Radiology Clinic or Imaging Center",
            type="SPECIALTY",
            score=0.92,
            criteria=SuggestionCriteria(
                taxonomyList=[
                    ProviderTaxonomy(
                        code="261QR0200X",
                        name="Radiology Clinic/Center",
                        description="Clinic/Center - Radiology",
                    ),
                    ProviderTaxonomy(
                        code="2085R0202X", name="Radiology, Diagnostic", description="Radiology - Diagnostic"
                    ),
                ],
                specialtyCategoryList=[
                    CodeNameDesc(code="231", name="Clinics / Radiology", description="Clinics / Radiology"),
                    CodeNameDesc(code="75", name="Imaging Centers", description="Imaging Centers"),
                ],
            ),
            procedureCode=None,
            medicalCode=None,
            metaData={},
            dplQueryParams={
                "specialty_category_codes": "231,75",
                "taxonomy_codes": "261QR0200X,2085R0202X",
                "distance": "30",
                "page_index": "0",
                "size": "5",
            },
        ),
    ],
    # PROCEDURE: MRI
    "mri": [
        SuggestionItem(
            text="MRI (Magnetic Resonance Imaging)",
            type="PROCEDURE",
            score=0.9,
            criteria=SuggestionCriteria(
                taxonomyList=[
                    ProviderTaxonomy(
                        code="261QR0200X",
                        name="Radiology Clinic/Center",
                        description="Clinic/Center - Radiology",
                    )
                ],
                specialtyCategoryList=[
                    CodeNameDesc(code="75", name="Imaging Centers", description="Imaging Centers")
                ],
            ),
            procedureCode="MRI",
            medicalCode="IMG-MRI",
            metaData={},
            dplQueryParams={
                "specialty_category_codes": "75",
                "taxonomy_codes": "261QR0200X",
                "distance": "30",
                "page_index": "0",
                "size": "5",
            },
        ),
    ],
    # PROCEDURE: Knee Surgery (orthopedics)
    "knee surgery": [
        SuggestionItem(
            text="Orthopedic Surgeon - Knee Surgery",
            type="PROCEDURE",
            score=0.91,
            criteria=SuggestionCriteria(
                taxonomyList=[
                    ProviderTaxonomy(
                        code="207X00000X",
                        name="Orthopedic Surgery",
                        description="Allopathic & Osteopathic Physicians - Orthopaedic Surgery",
                    )
                ],
                specialtyCategoryList=[
                    CodeNameDesc(code="220", name="Surgery / Orthopedics", description="Orthopedic Surgery")
                ],
            ),
            procedureCode="CPT:29881",
            medicalCode="KNEE-ARTHROSCOPY",
            metaData={},
            dplQueryParams={
                "specialty_category_codes": "220",
                "taxonomy_codes": "207X00000X",
                "distance": "25",
                "page_index": "0",
                "size": "5",
            },
        ),
    ],
}

# ====== Medical KB seeds (paginated) ======


def _ct(en_us: str, en_ca: str, es_us: str) -> ConsumerText:
    return ConsumerText(consumer={"en-us": en_us, "en-ca": en_ca, "es-us": es_us})


MEDICAL_KB = {
    # Hypertension: 8 articles (pagination needed)
    "high blood pressure": [
        MedicalArticle(
            id="htn-001",
            url="https://example.health/articles/htn-overview",
            title=_ct(
                "High Blood Pressure: Overview",
                "High Blood Pressure: Overview",
                "Presión arterial alta: Descripción general",
            ),
            abstract=_ct(
                "What hypertension is and why it matters.",
                "What hypertension is and why it matters.",
                "Qué es la hipertensión y por qué importa.",
            ),
        ),
        MedicalArticle(
            id="htn-002",
            url="https://example.health/articles/htn-symptoms",
            title=_ct("Hypertension Symptoms", "Hypertension Symptoms", "Síntomas de la hipertensión"),
            abstract=_ct(
                "Common and uncommon symptoms.",
                "Common and uncommon symptoms.",
                "Síntomas comunes e inusuales.",
            ),
        ),
        MedicalArticle(
            id="htn-003",
            url="https://example.health/articles/htn-causes",
            title=_ct(
                "Causes of High Blood Pressure",
                "Causes of High Blood Pressure",
                "Causas de la presión arterial alta",
            ),
            abstract=_ct(
                "Genetics, lifestyle, and other factors.",
                "Genetics, lifestyle, and other factors.",
                "Genética, estilo de vida y otros factores.",
            ),
        ),
        MedicalArticle(
            id="htn-004",
            url="https://example.health/articles/htn-diagnosis",
            title=_ct("Diagnosing Hypertension", "Diagnosing Hypertension", "Diagnóstico de la hipertensión"),
            abstract=_ct(
                "How doctors measure and confirm hypertension.",
                "How doctors measure and confirm hypertension.",
                "Cómo los médicos miden y confirman la hipertensión.",
            ),
        ),
        MedicalArticle(
            id="htn-005",
            url="https://example.health/articles/htn-treatment",
            title=_ct(
                "Treatment Options for Hypertension",
                "Treatment Options for Hypertension",
                "Opciones de tratamiento para la hipertensión",
            ),
            abstract=_ct(
                "Medications, diet, and exercise.",
                "Medications, diet, and exercise.",
                "Medicamentos, dieta y ejercicio.",
            ),
        ),
        MedicalArticle(
            id="htn-006",
            url="https://example.health/articles/htn-lifestyle",
            title=_ct(
                "Lifestyle Changes to Lower BP",
                "Lifestyle Changes to Lower BP",
                "Cambios de estilo de vida para bajar la presión",
            ),
            abstract=_ct(
                "Dietary patterns, sodium, and activity.",
                "Dietary patterns, sodium, and activity.",
                "Dieta, sodio y actividad.",
            ),
        ),
        MedicalArticle(
            id="htn-007",
            url="https://example.health/articles/htn-complications",
            title=_ct(
                "Complications of High Blood Pressure",
                "Complications of High Blood Pressure",
                "Complicaciones de la presión arterial alta",
            ),
            abstract=_ct(
                "Heart disease, stroke, and kidney damage.",
                "Heart disease, stroke, and kidney damage.",
                "Cardiopatía, ictus y daño renal.",
            ),
        ),
        MedicalArticle(
            id="htn-008",
            url="https://example.health/articles/htn-monitoring",
            title=_ct(
                "Monitoring Your Blood Pressure at Home",
                "Monitoring Your Blood Pressure at Home",
                "Monitoreo de la presión arterial en casa",
            ),
            abstract=_ct(
                "Devices and best practices.",
                "Devices and best practices.",
                "Dispositivos y mejores prácticas.",
            ),
        ),
    ],
    # Diabetes: 6 articles (pagination needed)
    "diabetes": [
        MedicalArticle(
            id="dm-001",
            url="https://example.health/articles/diabetes-overview",
            title=_ct("Diabetes: Overview", "Diabetes: Overview", "Diabetes: Descripción general"),
            abstract=_ct(
                "Types 1 and 2, and prediabetes.",
                "Types 1 and 2, and prediabetes.",
                "Tipos 1 y 2, y prediabetes.",
            ),
        ),
        MedicalArticle(
            id="dm-002",
            url="https://example.health/articles/diabetes-symptoms",
            title=_ct("Diabetes Symptoms", "Diabetes Symptoms", "Síntomas de la diabetes"),
            abstract=_ct(
                "Common signs and when to see a doctor.",
                "Common signs and when to see a doctor.",
                "Señales comunes y cuándo ver a un médico.",
            ),
        ),
        MedicalArticle(
            id="dm-003",
            url="https://example.health/articles/diabetes-management",
            title=_ct("Managing Diabetes", "Managing Diabetes", "Manejo de la diabetes"),
            abstract=_ct(
                "Monitoring glucose, diet, and medications.",
                "Monitoring glucose, diet, and medications.",
                "Control de glucosa, dieta y medicamentos.",
            ),
        ),
        MedicalArticle(
            id="dm-004",
            url="https://example.health/articles/diabetes-complications",
            title=_ct(
                "Complications of Diabetes", "Complications of Diabetes", "Complicaciones de la diabetes"
            ),
            abstract=_ct(
                "Eyes, nerves, kidneys, and heart.",
                "Eyes, nerves, kidneys, and heart.",
                "Ojos, nervios, riñones y corazón.",
            ),
        ),
        MedicalArticle(
            id="dm-005",
            url="https://example.health/articles/diabetes-exercise",
            title=_ct("Exercise and Diabetes", "Exercise and Diabetes", "Ejercicio y diabetes"),
            abstract=_ct(
                "How activity helps manage blood sugar.",
                "How activity helps manage blood sugar.",
                "Cómo la actividad ayuda a controlar el azúcar.",
            ),
        ),
        MedicalArticle(
            id="dm-006",
            url="https://example.health/articles/diabetes-diet",
            title=_ct("Diet for Diabetes", "Diet for Diabetes", "Dieta para la diabetes"),
            abstract=_ct(
                "Carbs, fiber, and meal planning.",
                "Carbs, fiber, and meal planning.",
                "Carbohidratos, fibra y planificación de comidas.",
            ),
        ),
    ],
    # Knee Surgery: 4 articles (no pagination needed)
    "knee surgery": [
        MedicalArticle(
            id="knee-001",
            url="https://example.health/articles/knee-prep",
            title=_ct(
                "Preparing for Knee Surgery",
                "Preparing for Knee Surgery",
                "Preparación para la cirugía de rodilla",
            ),
            abstract=_ct(
                "Pre-op guidance and expectations.",
                "Pre-op guidance and expectations.",
                "Guía preoperatoria y expectativas.",
            ),
        ),
        MedicalArticle(
            id="knee-002",
            url="https://example.health/articles/knee-types",
            title=_ct("Types of Knee Surgery", "Types of Knee Surgery", "Tipos de cirugía de rodilla"),
            abstract=_ct(
                "Arthroscopy, partial, and total replacement.",
                "Arthroscopy, partial, and total replacement.",
                "Artroscopia, parcial y reemplazo total.",
            ),
        ),
        MedicalArticle(
            id="knee-003",
            url="https://example.health/articles/knee-recovery",
            title=_ct("Knee Surgery Recovery", "Knee Surgery Recovery", "Recuperación de cirugía de rodilla"),
            abstract=_ct(
                "Rehab timelines and pain control.",
                "Rehab timelines and pain control.",
                "Tiempos de rehabilitación y control del dolor.",
            ),
        ),
        MedicalArticle(
            id="knee-004",
            url="https://example.health/articles/knee-risks",
            title=_ct("Risks of Knee Surgery", "Risks of Knee Surgery", "Riesgos de la cirugía de rodilla"),
            abstract=_ct(
                "Complications and how to reduce them.",
                "Complications and how to reduce them.",
                "Complicaciones y cómo reducirlas.",
            ),
        ),
    ],
}

# ===== Billing ledger (by clmUid) =====
# status: DUE | PAID | PARTIAL | IN_COLLECTIONS
BILLING_LEDGER: Dict[str, Dict[str, str]] = {
    # Some JOHN claims
    "63FA69DB119C2E16E21B487BC411E1F2": {"status": "DUE", "dueAmt": "10.00", "dueDt": "2025-03-15"},
    "9C0C8D7A6B5A4899BC12EF3344CDA123": {"status": "PAID", "dueAmt": "0.00", "dueDt": "2025-02-25"},
    "9C0C8D7A6B5A4899BC12EF3344CDA456": {
        "status": "IN_COLLECTIONS",
        "dueAmt": "80.00",
        "dueDt": "2025-04-10",
    },
    # SARA
    "9C0C8D7A6B5A499BA3A4F33AQW1DA211": {"status": "DUE", "dueAmt": "60.00", "dueDt": "2025-03-10"},
    # TOM
    "9C0C8Q1A6B28499BA3A2333AQW1DAADE": {"status": "DUE", "dueAmt": "95.00", "dueDt": "2025-03-12"},
    "9C0C8D7A6B5A4899BA3A4F3344CDA451": {"status": "DUE", "dueAmt": "15.00", "dueDt": "2025-03-20"},
    # JANE
    "C3333333333333333333333333333333": {"status": "DUE", "dueAmt": "50.00", "dueDt": "2025-03-18"},
}

# ===== Payment intents (runtime) =====
PAYMENT_INTENTS: Dict[str, Dict[str, str]] = {
    # Example structure:
    # "pi_xxx": {"status":"REQUIRES_CONFIRMATION","memberId":"...","clmUid":"...","amount":"...", "currency":"USD"}
}

# ===== Accumulators (by coverageKey) =====
ACCUMULATORS_DB: Dict[str, List[AccumulatorEntry]] = {
    # JOHN 2025 PPO
    "1J1U-20250101-20251231-MED-57AMFC": [
        AccumulatorEntry(type="DED", level="INDV", network="INN", met="250.00", limit="1000.00"),
        AccumulatorEntry(type="OOP", level="INDV", network="INN", met="400.00", limit="3000.00"),
        AccumulatorEntry(type="DED", level="FAM", network="INN", met="700.00", limit="3000.00"),
        AccumulatorEntry(type="OOP", level="FAM", network="INN", met="1200.00", limit="6000.00"),
        # OON examples
        AccumulatorEntry(type="DED", level="INDV", network="OON", met="0.00", limit="3000.00"),
        AccumulatorEntry(type="OOP", level="INDV", network="OON", met="0.00", limit="9000.00"),
    ],
    # JANE 2025 HMO (no deductible; OOP tracking)
    "9Z9X-20250101-20251231-MED-INDHMO": [
        AccumulatorEntry(type="DED", level="INDV", network="INN", met="0.00", limit="0.00"),
        AccumulatorEntry(type="OOP", level="INDV", network="INN", met="1200.00", limit="4500.00"),
    ],
}

# ===== Member preferences (by mbrUid) =====
MEMBER_PREFERENCES: Dict[str, MemberPreferences] = {
    "121231234": MemberPreferences(
        language="en-us", emailOptIn=True, smsOptIn=False, accessibility="True"
    ),  # JOHN
    "882771300": MemberPreferences(
        language="en-us", emailOptIn=False, smsOptIn=True, accessibility="large_text"
    ),  # JANE
    "121231235": MemberPreferences(
        language="en-us", emailOptIn=False, smsOptIn=False, accessibility=None
    ),  # SARA
    "121231236": MemberPreferences(
        language="en-us", emailOptIn=False, smsOptIn=False, accessibility=None
    ),  # TOM
}

# =====================================================
# Global DBs (exports)
# =====================================================

CLAIMS_DB: List[Claim] = seed_claims()
CLAIM_DETAILS_DB = build_claim_details_index(CLAIMS_DB)
ELIGIBILITY_DB, COVERAGE_KEY_INDEX, PLAN_INFO_DB, CONTRACT_UID_TO_CD = seed_eligibility_and_plans()

__all__ = [
    "CLAIMS_DB",
    "CLAIM_DETAILS_DB",
    "ELIGIBILITY_DB",
    "COVERAGE_KEY_INDEX",
    "PLAN_INFO_DB",
    "STATUS_CODEBOOK",
    "CONTRACT_UID_TO_CD",
    "SUPPORTED_BENEFIT_INTENTS",
    "BENEFIT_DETAILS_DB",
    "PROVIDERS_DB",
    "SUGGESTIONS_DB",
    "MEDICAL_KB",
    "BILLING_LEDGER",
    "PAYMENT_INTENTS",
    "ACCUMULATORS_DB",
    "MEMBER_PREFERENCES",
]
