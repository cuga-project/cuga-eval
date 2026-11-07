"""Hand-built procedure graph of CareIG_SOP_v5.0 (HANDBOOK task medical_careig_specialty_pharmacy_f5947c33).

Same method as crestwood_graph.py: built by Claude from the SOP text only; the task's case files, emails, rubric and
tests were NOT read. Every node cites its SOP section.

    python3 -I careig_graph.py <templates.json> <out.json>
"""

import json
import sys

GLOBAL_RULES = [
    {"id": "G-case-id", "src": "§1", "rule": "Case data lives in a case folder CASE_ID = LastName_MMDDYYYY (patient DOB). Use CASE_ID in every audit log entry, Slack post and file reference."},
    {"id": "G-dates", "src": "§1", "rule": "Dates written in files: YYYY-MM-DD unless a section specifies otherwise (e.g. coverage dates MM/DD/YYYY in benefits.xlsx)."},
    {"id": "G-not-covered", "src": "§1", "rule": "A situation not covered by the SOP: do not guess; stop work on that step, note it in audit_log.xlsx, and contact the direct supervisor using the escalation path in Section 12. When in doubt, escalate before acting."},
    {"id": "G-file-access", "src": "§2", "rule": "Roles write only their files (Patient Rep: intake.xlsx; BVS: benefits.xlsx, auth.xlsx; Clinical Coordinator: clinical.xlsx; Nurse: visit_note.xlsx; Billing: claim.xlsx; AR: claim.xlsx payment cols). Access outside scope: log to audit_log.xlsx (Action = Out-of-Scope Access) and report to compliance@careig.com."},
    {"id": "G-templates-files", "src": "§3", "rule": "Template files are blank masters: copy before use, never edit in place (e.g. copy intake_blank.xlsx to intake.xlsx)."},
    {"id": "G-audit", "src": "§4.1", "attach_when": r"audit log|do not proceed|hold|stop", "rule": "Append ONE row to audit_log.xlsx at each checkpoint named in a section (Referral Received, BVS Assigned, BV Complete, PA Submitted, PA Approved — Clinical Handoff, PA Denied, Visit Note Signed, Claim Submitted, Appeal Submitted) and at every Stop Protocol. Columns: Date | CASE_ID | Action | File_Updated | Field_Updated | New_Value | Staff_User | Result (SUCCESS / FAILED / STOP — reason). Append-only; do not log substeps."},
    {"id": "G-stop", "src": "§4.2", "attach_when": r"do not proceed|hold|do not submit|do not begin|do not schedule|stop", "rule": "Stop Protocol: when a validation fails, log audit_log.xlsx Action 'Stop Protocol' with File_Updated, Field_Updated and New_Value = N/A and the reason, and HOLD the case: do not move to the next step until the supervisor or responsible team member confirms the issue is cleared."},
    {"id": "G-prohibited", "src": "§4.3", "rule": "Prohibited: billing an IVIG drug J-code when clinical.xlsx Drug_Source ≠ CareIG; billing pre-med J-codes without full documentation in Premeds_Administered; using the ordered dose for units (use Dose_Administered_Grams); submitting a claim when claim.xlsx already has Submission_Date for the same DOS; writing off > $200 without Director of Revenue Cycle approval (#billing-mgmt); responding to legal threats or attorney communications (post to #compliance); assigning an ICD-10 code not supported by the physician's documentation AND the PA approval."},
    {"id": "G-phone", "src": "§4.4", "rule": "A step that needs a phone call: if the information is already in an email, referral document or input file, use that source and log it in the call log field; if it is not available and no call can be made, follow the Stop Protocol."},
    {"id": "G-drug-names", "src": "§13.3", "rule": "Enter Drug_Name values using the Drug column names of the drug reference (Gammaplex 5% / 10%, Octagam 5% / 10%, Gammagard S/D, Gammagard Liquid 10%, Privigen 10%, Gamunex-C 10%, Hizentra 20%, HyQvia 10%)."},
    {"id": "G-icd10", "src": "§13.4", "rule": "Before ANY PA or claim: the ICD-10 from intake.xlsx Diagnosis_ICD10 must be in the ICD-10 table as written, and its required documentation must be in the case folder (procedure 13.4)."},
]

WORKFLOW = {
    "id": "workflow", "src": "§5", "name": "Workflow summary (stage → file written → Slack)",
    "steps": [
        "1 Referral received → create and populate intake.xlsx (6.1)",
        "2 Patient contacted → consent form sent → intake.xlsx Consent_Status = Form Sent (6.2)",
        "3 Signed consent received → BVS assigned → Consent_Status = Signed, BVS_Assigned; #intake-team: [BVS ASSIGNED] CASE_ID | Payer | Drug (6.2)",
        "4 BV + drug source decision + financial counseling → benefits.xlsx BV_Complete = YES; clinical.xlsx Drug_Source (7.1-7.3)",
        "5 Formulary check → PA submitted → auth.xlsx PA_Submission_Date, PA_Status = Pending; #intake-team: [PA SUBMITTED] CASE_ID | Payer | Drug (8.1-8.3)",
        "6 PA approved → clinical handoff → auth.xlsx PA_Status = Approved; clinical.xlsx Handoff_Status = Received; #clinical-scheduling: [PA APPROVED] ... (8.6)",
        "7 Supply checklist → nurse scheduled → clinical.xlsx Visit_Date, Nurse_Assigned; #clinical-scheduling: [SCHEDULED] ... (9.1-9.2)",
        "8 Visit → visit note signed → visit_note.xlsx Nurse_Signature; #clinical-scheduling: [VISIT COMPLETE] CASE_ID | DOS (9.3)",
        "9 Billing validates → builds → submits claim → claim.xlsx Submission_Date, Claim_Status = Submitted; #billing: [CLAIM SUBMITTED] ... (10.1-10.3)",
        "10 ERA/EOB posted → payment or denial; denial: #billing-appeals: [DENIAL] CASE_ID | CARC (10.4, 11)",
        "To find where an existing case is: check the files in this order and apply procedure 12.2 (monitoring) for stalled stages.",
    ],
}

ESCALATION = {
    "id": "escalation", "src": "§12.1", "name": "Escalation paths",
    "steps": [
        "PA pending > 5 days: #intake-mgmt: [PA DELAY] CASE_ID | Payer | Days Pending.",
        "Claim unpaid, no ERA: #billing: [AR FOLLOWUP] CASE_ID | [days] outstanding | [Payer]; log payer call in claim.xlsx AR_Followup_Log.",
        "Payer underpaid vs contract: #billing-mgmt: [UNDERPAYMENT] CASE_ID | Expected: $[rate] | Received: $[paid].",
        "Patient balance > $500 unresolved: confirm 3 contact attempts in intake.xlsx; < 3: email patient; 3+: #billing-mgmt requesting collections authorization.",
        "Write-off > $200: #billing-mgmt: [WRITE-OFF REQUEST] CASE_ID | Amount: $[amount] | Reason: [reason]; Director approval first.",
        "Level 2 appeal denied: #billing-mgmt: [L2 DENIED] CASE_ID.",
        "Legal threat or attorney communication: STOP; do not respond or modify case files; #compliance: [LEGAL THREAT] CASE_ID; notify Director of Operations and legal@careig.com.",
        "Suspected fraud or billing abuse: STOP; do not discuss elsewhere or modify files; #compliance: [COMPLIANCE REPORT] CASE_ID; call the Compliance Hotline.",
        "Wrong drug lot/dose from partner pharmacy: do not administer; clinical.xlsx Drug_Issue_Notes; #clinical-scheduling: [DRUG ISSUE] CASE_ID — visit on hold; contact partner pharmacy.",
    ],
    "must_not": ["Never respond to a legal threat or attorney communication, and do not modify the case files.", "Suspected fraud: do not discuss it elsewhere or modify files."],
}

P = []


def proc(pid, name, category, applies, steps, inputs=(), decisions=(), must_not=(), links=(), deadlines=(), notes=()):
    P.append({"id": pid, "name": name, "category": category, "applies_when": applies, "inputs": list(inputs),
              "decisions": list(decisions), "steps": list(steps), "must_not": list(must_not), "links": list(links),
              "deadlines": list(deadlines), "notes": list(notes), "src": f"§{pid}"})


proc("6.1", "Case Setup", "Intake", "A referral is received for a new patient (no intake.xlsx yet).",
     ["Copy intake_blank.xlsx to create intake.xlsx for the case.",
      "Populate from the referral: Patient_Last_Name, First_Name, DOB, Address, Phone, Email (email optional); Physician_Name, Physician_NPI, Physician_Email; Diagnosis_ICD10; Drug_Name, Drug_Dose_Grams (convert mg to grams), Drug_Frequency; Primary_Insurance_Name, Member_ID, Group_Number, Payer_Phone; Secondary_Insurance_Name, Member_ID (if listed); Contraindications; Consent_Status = Pending.",
      "Audit log: Action = Referral Received."],
     decisions=[{"id": "npi", "rule": "Physician_NPI is non-blank after referral entry", "else": "#intake-alerts: [INTAKE HOLD] CASE_ID — Physician NPI missing; email a request for information to intake.xlsx Physician_Email; do not proceed"}],
     must_not=["Do not proceed past intake when Physician_NPI is blank."],
     links=[{"type": "next", "to": "6.2"}])

proc("6.2", "Patient Contact", "Intake", "Intake is created and the patient must be contacted for consent, or signed consent arrives.",
     ["Call the patient at intake.xlsx Patient_Phone with the verbatim script; no answer → verbatim voicemail (do not state the diagnosis). (No phone: §4.4 phone workaround.)",
      "Log each attempt in intake.xlsx Contact_Attempt_Log: [Date] [Time] — [Reached / No Answer / Voicemail].",
      "3 entries and none Reached: #intake-alerts: [UNREACHABLE] CASE_ID — 3 failed attempts; complete Template 1 and email it to intake.xlsx Physician_Email; do not proceed.",
      "Patient reached: confirm demographics, explain consent, email the consent form to intake.xlsx Patient_Email, subject 'CareIG — Consent Form Required | [Patient Last Name]' (no email: mail to Patient_Address and note the method in Contact_Attempt_Log); Consent_Status = Form Sent.",
      "Signed consent received: save as consent_signed.pdf; Consent_Status = Signed.",
      "Assign BVS: intake.xlsx BVS_Assigned; #intake-team: [BVS ASSIGNED] [CASE_ID] | Payer: [Insurance_Name] | Drug: [Drug_Name] | Dose: [Drug_Dose_Grams]g.",
      "Audit log: Action = BVS Assigned."],
     decisions=[{"id": "consent", "rule": "intake.xlsx Consent_Status = Signed before BV starts", "else": "#intake-alerts: [CONSENT MISSING] CASE_ID; do not begin BV"}],
     must_not=["Do not begin benefits verification unless Consent_Status = Signed.", "Do not state the diagnosis in a voicemail."],
     links=[{"type": "next", "to": "7.1"}])

proc("7.1", "Benefits Verification", "Benefits Verification", "Consent is signed and BV is needed (payer call; use emails/files per §4.4).",
     ["Get from the payer (call at intake.xlsx Primary_Payer_Phone, or existing written sources per §4.4) and write to benefits.xlsx: Home_Infusion_Covered; Benefit_Type (medical / pharmacy); PA_Required, PA_Phone, PA_Submission_Email; Specialty_Pharmacy_Required, Specialty_Pharmacy_Name; CareIG_Network_Status; Deductible_Individual, Deductible_Met_YTD; OOP_Max_Individual, OOP_Max_Met_YTD; Coinsurance_Pct, Copay_Amount; Plan_Year_Type; Payer_Type (Medicare Part B / Medicare Adv. / Medicaid / Commercial PPO / Commercial HMO); Nursing_Code_Pref (from payer_rules.xlsx); Coverage Effective and Term dates (MM/DD/YYYY); BV_Call_Date, BV_Rep_Name, BV_Call_Ref_Number.",
      "Set BV_Complete = YES LAST, only when every required field is non-blank.",
      "Audit log: Action = BV Complete."],
     must_not=["Do not set BV_Complete = YES while any required field is blank."],
     links=[{"type": "next", "to": "7.2"}])

proc("7.2", "Drug Source Decision", "Benefits Verification", "Right after BV: write clinical.xlsx Drug_Source.",
     ["In-Network AND Specialty_Pharmacy_Required = NO → Drug_Source = CareIG.",
      "Out-of-Network AND Specialty_Pharmacy_Required = YES → Drug_Source = benefits.xlsx Specialty_Pharmacy_Name; CareIG bills nursing and supplies only (no IVIG drug J-code).",
      "Out-of-Network AND Specialty_Pharmacy_Required = NO → #intake-mgmt: [OON NO PREFERRED PHARMACY] CASE_ID — CareIG is out-of-network but payer has no required specialty pharmacy. Supervisor must determine next step...; do not proceed until the supervisor confirms Drug_Source.",
      "Benefit_Type = Pharmacy → #billing-mgmt: [BENEFIT TYPE ISSUE] CASE_ID — IVIG under pharmacy benefit. Awaiting Director guidance; do not proceed until resolved.",
      "In-Network AND Specialty_Pharmacy_Required = YES → Drug_Source = Specialty_Pharmacy_Name; nursing and supplies only."],
     inputs=[{"fact": "CareIG_Network_Status, Specialty_Pharmacy_Required, Specialty_Pharmacy_Name, Benefit_Type", "source": "benefits.xlsx"}],
     decisions=[{"id": "drug_source", "rule": "the five network / specialty pharmacy / benefit type rules above"}],
     must_not=["Do not proceed when out-of-network with no required specialty pharmacy, or when IVIG is under the pharmacy benefit, until resolved."],
     links=[{"type": "next", "to": "7.3"}])

proc("7.3", "Patient Financial Counseling", "Benefits Verification", "After BV and drug source: tell the patient the estimated out-of-pocket per visit.",
     ["Estimate: remaining deductible (Deductible_Individual − Deductible_Met_YTD) + Coinsurance_Pct × expected billed amount (+ Copay_Amount if applicable); billed amount = drug J-code Billed_Rate (fee_schedule.xlsx) × expected units + estimated nursing and supply charges from the same file.",
      "Call the patient with the script and the dollar figure (no phone: §4.4).",
      "Log in benefits.xlsx Financial_Counseling_Log: [Date] [Time] — [outcome].",
      "Hardship reported: intake.xlsx Financial_Hardship = YES; #intake-team: [FINANCIAL HARDSHIP] CASE_ID — refer to Patient Assistance Program."],
     links=[{"type": "next", "to": "8.0"}])

proc("8.0", "Prior Authorization — entry rule", "Prior Authorization", "BV is complete and a PA may be needed.",
     ["benefits.xlsx PA_Required = NO → skip 8.1-8.5; go to 8.6 with auth.xlsx PA_Status = Not Required and PA_Number = N/A.",
      "PA_Required = YES → 8.1 formulary check, 8.2 documents, 8.3 submission."],
     links=[{"type": "next", "to": "8.1"}, {"type": "next", "to": "8.2"}, {"type": "next", "to": "8.3"}])

proc("8.1", "Formulary Check", "Prior Authorization", "Before submitting any PA.",
     ["payer_rules.xlsx: row for the payer (benefits.xlsx Primary_Insurance_Name), col Formulary_Covered_Drugs; is intake.xlsx Drug_Name listed?",
      "Not listed: contact the physician (intake.xlsx Physician_Phone) for an alternative covered drug or a written formulary exception letter; then (or if not reached and still unresolved) #intake-team: [FORMULARY ISSUE] CASE_ID | Drug: [Drug_Name] | Payer: [Insurance_Name]. Exception: physician guidance already on file that resolves it (e.g. an email authorizing a covered substitute) → apply it, no [FORMULARY ISSUE] post.",
      "Exception letter received: save formulary_exception.pdf; auth.xlsx Formulary_Exception_Notes; include in the PA packet; go to 8.2.",
      "Substitute drug: update intake.xlsx Drug_Name; restart 8.1.",
      "Neither within 2 business days: #intake-mgmt: [FORMULARY UNRESOLVED] CASE_ID; hold the case."],
     decisions=[{"id": "formulary", "rule": "intake.xlsx Drug_Name is in payer_rules.xlsx Formulary_Covered_Drugs for the payer", "else": "physician path above; no PA until resolved"}],
     must_not=["Do not submit the PA until the drug is on formulary, an exception letter is on file, or a covered substitute is confirmed."],
     links=[{"type": "next", "to": "8.2"}])

proc("8.2", "Required PA Documents", "Prior Authorization", "Before PA submission: check every required document in the case folder.",
     ["Required: pa_form_[PayerName].pdf (payer-specific PA form); lmn_[PhysicianName].pdf (Letter of Medical Necessity — signed, on letterhead, dated within 90 days); igglevel_[MMDDYYYY].pdf (most recent IgG lab, if applicable); progress_note_[MMDDYYYY].pdf (most recent progress note); formulary_exception.pdf (if applicable).",
      "Also check the ICD-10 documentation requirement (13.4) for the diagnosis.",
      "Any document missing or invalid: #intake-alerts: [PA HOLD] CASE_ID — [missing / invalid]: [document name]; do not submit; Stop Protocol (§4.2) with reason \"invalid file\"."],
     decisions=[{"id": "documents_valid", "rule": "every required document exists and is valid (LMN signed, on letterhead, dated within 90 days; labs within the windows of 13.4)", "else": "[PA HOLD] post, Stop Protocol, do not submit"}],
     must_not=["Do not submit a PA when any required document is missing or invalid (e.g. LMN unsigned or older than 90 days, IgG lab outside its window)."],
     links=[{"type": "next", "to": "13.4"}, {"type": "next", "to": "8.3"}])

proc("8.3", "PA Submission", "Prior Authorization", "Formulary and documents are valid: submit the PA.",
     ["Email to payer_rules.xlsx PA_Submission_Email. Subject: [PA REQUEST] CareIG | [Patient Last Name] | MemberID: [Member_ID] | Drug: [Drug_Name] | Dose: [Drug_Dose_Grams]g | Dx: [Diagnosis_ICD10]. Attach all required PA documents.",
      "auth.xlsx: PA_Submission_Date = today, PA_Status = Pending, Last_Followup_Date = today.",
      "#intake-team: [PA SUBMITTED] [CASE_ID] | Payer: [name] | Drug: [Drug_Name].",
      "Audit log: Action = PA Submitted."],
     must_not=["Do not submit if 8.1 or 8.2 or 13.4 failed."],
     links=[{"type": "next", "to": "8.4"}])

proc("8.4", "PA Follow-Up", "Prior Authorization", "A PA is pending.",
     ["Every business day: auth.xlsx PA_Status; still Pending and (today − Last_Followup_Date) ≥ 2 days → call the payer PA line (benefits.xlsx PA_Phone; §4.4 if no call possible); append to auth.xlsx PA_Call_Log: [Date] [Time] | Rep: [name] | Status: [status] | Next expected update: [date]; Last_Followup_Date = today.",
      "Still Pending after 5 days from PA_Submission_Date: #intake-mgmt: [PA DELAY] [CASE_ID] | Payer: [name] | Days Pending: [count]."])

proc("8.5", "Peer-to-Peer Request", "Prior Authorization", "The payer offers a P2P review after a PA denial.",
     ["Get time slots from the payer; auth.xlsx P2P_Available_Slots.",
      "Complete Template 2; save p2p_request.pdf; email to intake.xlsx Physician_Email, subject [P2P REQUEST] [CASE_ID] | [Payer].",
      "auth.xlsx P2P_Status = Requested, P2P_Request_Date = today.",
      "P2P_Status = Requested AND P2P_MD_Response_Date blank AND (today − P2P_Request_Date) ≥ 2 days: #intake-alerts: [P2P NO RESPONSE] CASE_ID; P2P_Status = No Response; go to Level 1 appeal (11.2)."])

proc("8.6", "PA Approval — Clinical Handoff", "Prior Authorization", "A PA approval arrives (or PA not required).",
     ["Save the approval as pa_approval_[PayerName].pdf; auth.xlsx PA_Number, PA_Approved_Drug, PA_Approved_Dose, PA_Approved_Frequency, PA_Effective_Date, PA_Expiration_Date, PA_Status = Approved.",
      "clinical.xlsx: Handoff_Status = Received, PA_Number, PA_Expiration_Date.",
      "#clinical-scheduling: [PA APPROVED] [CASE_ID] | Drug: [PA_Approved_Drug] | Dose: [PA_Approved_Dose]g | PA#: [PA_Number] | Exp: [PA_Expiration_Date] | Drug Source: [Drug_Source].",
      "PA_Approved_Drug ≠ intake Drug_Name (case-insensitive): #intake-alerts: [PA DRUG MISMATCH] CASE_ID | Ordered: [Drug_Name] | Approved: [PA_Approved_Drug]; resolve before scheduling.",
      "PA_Approved_Dose < Drug_Dose_Grams: #intake-alerts: [PA DOSE MISMATCH] CASE_ID | Ordered: [Drug_Dose_Grams]g | Approved: [PA_Approved_Dose]g; do not schedule.",
      "Audit log: Action = PA Approved — Clinical Handoff."],
     must_not=["Do not schedule when the approved drug differs or the approved dose is below the ordered dose."])

proc("8.7", "PA Denial", "Prior Authorization", "A PA denial arrives.",
     ["auth.xlsx: PA_Denial_Date = today, PA_Denial_Reason = denial text, PA_Status = Denied.",
      "#billing-appeals: [PA DENIED] [CASE_ID] | Payer: [name] | Reason: [PA_Denial_Reason]; go to Section 11 (and 8.5 if a P2P is offered).",
      "Audit log: Action = PA Denied."],
     links=[{"type": "next", "to": "8.5"}, {"type": "next", "to": "11.2"}])

proc("9.1", "Supply Checklist", "Clinical", "Before scheduling a nurse visit.",
     ["clinical.xlsx all YES: Drug_Order_Placed, Drug_Delivery_Confirmed (record delivery date), Drug_Lot_Number, Drug_NDC, Filter_Tubing_Ordered, Benadryl_Available (N/A if not ordered), Supplies_Other; NS_500mL_Qty_Ordered integer ≥ 2 (Gammaplex: 0 and ≥ 2 bags of 500 mL 10% Dextrose); then Supply_Checklist_Complete = YES.",
      "Supply_Checklist_Complete ≠ YES when scheduling is attempted: #clinical-scheduling: [SUPPLY HOLD] CASE_ID — checklist incomplete; do not schedule."],
     must_not=["Do not schedule a visit until Supply_Checklist_Complete = YES."], links=[{"type": "next", "to": "9.2"}])

proc("9.2", "Nurse Scheduling", "Clinical", "Supplies are complete; schedule the visit.",
     ["Nurse matching patient zip and credential (RN for the first visit; payer_rules.xlsx Nursing_Credential_Requirement later).",
      "Calendar: IVIG Visit — [CASE_ID], include the nurse; duration from infusion_duration.xlsx (drug + dose range).",
      "Confirm with the patient (script).",
      "clinical.xlsx Visit_Date, Visit_Time, Nurse_Assigned; #clinical-scheduling: [SCHEDULED] [CASE_ID] | Date: [Visit_Date] | Nurse: [Nurse_Assigned].",
      "Email the nurse: [VISIT ASSIGNMENT] [CASE_ID] | [Date] with address, drug, dose, lot, NDC, rate, pre-meds, emergency contact, contraindications."])

proc("9.3", "Visit Documentation", "Clinical", "After a visit: the nurse note.",
     ["visit_note.xlsx complete within 4 hours with Nurse_Signature (full name and credential); Premeds_Administered format [Drug] [Dose][unit] [Route] at [Time] for [Indication] or 'None administered'; Dextrose bags for Gammaplex.",
      "Nurse_Signature blank: #clinical-scheduling: [UNSIGNED NOTE] CASE_ID — claim on hold until signed.",
      "#clinical-scheduling: [VISIT COMPLETE] [CASE_ID] | DOS: [Visit_Date]; audit log: Visit Note Signed."],
     must_not=["No claim while Nurse_Signature is blank."])

proc("10.1", "Pre-Billing Validation", "Billing", "Before building claim.xlsx.",
     ["All must be TRUE, else post to #billing and stop: Nurse_Signature non-blank [BILLING HOLD — UNSIGNED NOTE]; PA_Status = Approved [BILLING HOLD — NO PA APPROVAL]; PA_Number non-blank [BILLING HOLD — PA NUMBER MISSING]; PA_Expiration_Date ≥ Visit_Date [BILLING HOLD — PA EXPIRED ON DOS] CASE_ID | PA Exp: [date] | DOS: [date]; PA_Approved_Drug = Drug_Name_Trade [BILLING HOLD — DRUG MISMATCH]; PA_Approved_Dose ≥ Dose_Administered_Grams [BILLING HOLD — DOSE EXCEEDS PA] (+ escalate to BVS); Diagnosis_ICD10 consistent with the PA [BILLING HOLD — ICD10 INCONSISTENT]; Dose_Administered_Grams > 0 [BILLING HOLD — DOSE NOT DOCUMENTED]; no Submission_Date for this DOS [DUPLICATE CLAIM RISK] CASE_ID | DOS; active coverage on DOS [BILLING HOLD — COVERAGE NOT CONFIRMED]."],
     must_not=["Do not build or submit a claim when any pre-billing condition is false."], links=[{"type": "next", "to": "10.2"}])

proc("10.2", "Claim Construction", "Billing", "Pre-billing validation passed.",
     ["Copy claim_blank.xlsx to claim.xlsx.",
      "Drug J-code (jcodes.xlsx for Drug_Name_Trade): units = floor(Dose_Administered_Grams × 1000 ÷ unit size) (500 mg; Hizentra/HyQvia 100 mg).",
      "Nursing: ≤ 60 min → 99600 × 1 only; Nursing_Code_Pref blank/99600 → 99600 × 1 + 99603 × floor((minutes − 60) ÷ 60); G0153 (Medicare B) × 1 only; T1029/T1032 per state.",
      "Saline J7030 × NS_500mL_Bags_Used, J7050 × NS_250mL_Bags_Used (Gammaplex: no J7030/J7050; Dextrose via A4221).",
      "Pre-meds: Diphenhydramine J0171 × mg/50; Promethazine J2550 × mg/25; none → blank.",
      "Supplies A4221 × 1; pump used → A4222 × 1 as well.",
      "Header: PA_Number, Physician_NPI, CareIG_NPI and Tax_ID (payer_rules.xlsx), DOS = Visit_Date, ICD10, Taxonomy (org_identifiers.xlsx).",
      "Drug_Source ≠ CareIG: drug J-code fields blank; Billing_Model = Split — Drug billed by [Drug_Source].",
      "Claim_Frequency_Code 1 original / 7 corrected / 8 void; Route SQ → Drug_Modifier SC.",
      "Total_Billed = Σ units × fee_schedule.xlsx Billed_Rate."],
     links=[{"type": "next", "to": "10.3"}])

proc("10.3", "Claim Submission", "Billing", "claim.xlsx is built.",
     ["Export claim_[DOS].pdf; email to payer_rules.xlsx Claim_Submission_Email, subject [CLAIM SUBMISSION] CareIG NPI: [NPI] | [Patient Last Name] | MemberID: [Member_ID] | DOS: [Visit_Date].",
      "claim.xlsx Submission_Date = today, Submission_Ref_Number, Claim_Status = Submitted.",
      "#billing: [CLAIM SUBMITTED] [CASE_ID] | DOS: [Visit_Date] | Payer: [name] | Billed: $[Total_Billed]; audit log: Claim Submitted."])

proc("10.4", "ERA & Payment Posting", "Billing", "An ERA/EOB arrives.",
     ["Save as era_[DOS]_[Payer].pdf.", "Paid < payer_rules.xlsx Contracted_Rate: #billing-mgmt: [UNDERPAYMENT] ...; do not write off.",
      "Denial line ($0, CARC): copy denial_blank.xlsx to DENIAL_[CARC]_[DOS].xlsx; CARC_Code, Denial_Date, DOS, Denied_Code, Denied_Amount; Section 11.",
      "claim.xlsx Payment_Posted_Date = today, Claim_Status = Paid / Partially Paid / Denied.",
      "Patient_Responsibility > 0: statement_[DOS].pdf from patient_statement_template.docx; email to Patient_Email, subject CareIG Statement of Account | DOS: [Visit_Date]."])

proc("11.1", "Denial Actions by CARC Code", "Denials", "A claim denial with a CARC code.",
     ["CO-4 correct modifier per Route, resubmit; CO-11 confirm ICD-10 vs PA, mismatch → email physician [ICD10 CLARIFICATION NEEDED] CASE_ID | DOS, no resubmission before written confirmation; CO-16 fix missing field, resubmit; CO-18 duplicate → void with code 8 (Claim_Status = Voided, keep row) else resubmit with 7; CO-22 bill the primary payer first, then resubmit with COB fields; CO-50 Level 1 appeal; CO-96 compare contracted rate, dispute → #billing-mgmt, write-off needs Director; CO-97 benefit tier check → correct or Level 1 appeal; PR-1/2/3 patient responsibility from the ERA → claim.xlsx Patient_Responsibility + statement; OA-23 underpaid → #billing-mgmt; PI-204 Level 1 appeal with PA approval, LMN, notes, IgG labs."],
     links=[{"type": "next", "to": "11.2"}])

proc("11.2", "Appeal Submission", "Denials", "An appeal is needed.",
     ["Gather the original claim PDF, PA approval, LMN, visit note export, ERA/EOB.", "Template 3 (appeal_template.docx) → appeal_L[1 or 2]_[DOS].pdf.",
      "Email to payer_rules.xlsx Appeal_Submission_Email, subject [APPEAL L[1/2]] CareIG | [Patient Last Name] | MemberID: [Member_ID] | DOS: [DOS] | Claim: [Submission_Ref_Number] | CARC: [code].",
      "appeals/appeals_log.xlsx: DOS, CARC_Code, Appeal_Level, Appeal_Submitted_Date, Appeal_Status = Submitted.",
      "#billing-appeals: [APPEAL FILED L[1/2]] [CASE_ID] | DOS | Payer | CARC; audit log: Appeal Submitted.",
      "Follow-up after 15 days; Level 2 denied → #billing-mgmt: [L2 DENIED] CASE_ID."])

proc("12.2", "Workflow Monitoring", "Monitoring", "Reviewing an existing (in-progress) case: find where it is stalled and send the notice once.",
     ["Referral Received in audit_log but no BVS Assigned → #intake-alerts: [UNASSIGNED] CASE_ID — no BVS assigned.",
      "BV_Complete blank after BVS Assigned → #intake-alerts: [BV OVERDUE] CASE_ID.",
      "PA_Submission_Date blank after BV_Complete = YES → #intake-alerts: [PA NOT SUBMITTED] CASE_ID.",
      "PA_Status = Pending AND Last_Followup_Date 2+ days old → call payer (§4.4); update PA_Call_Log and Last_Followup_Date.",
      "Handoff_Status blank after PA_Status = Approved → #clinical-scheduling: [HANDOFF MISSING] CASE_ID.",
      "Visit_Date blank after Handoff_Status = Received → #clinical-scheduling: [UNSCHEDULED] CASE_ID.",
      "Nurse_Signature blank after Visit_Date → #clinical-scheduling: [UNSIGNED NOTE] CASE_ID.",
      "Submission_Date blank after Nurse_Signature → #billing: [CLAIM NOT SUBMITTED] CASE_ID.",
      "ERA_Received_Date set AND Payment_Posted_Date blank → #billing: [ERA UNPOSTED] CASE_ID.",
      "A denial file with Appeal_Submitted blank → #billing-appeals: [DENIAL UNWORKED] CASE_ID.",
      "(today − DOS) > 80% of Timely_Filing_Days AND no Submission_Date → #billing: [TIMELY FILING RISK] CASE_ID | [days elapsed] of [limit] days | [Payer]; submit immediately.",
      "Then continue the case from that stage with its procedure (and its checks)."],
     notes=["Send each notice only if it was not already sent."])

proc("13.4", "ICD-10 Documentation Check", "Reference", "Before any PA or claim: check the diagnosis code and its documentation.",
     ["The intake.xlsx Diagnosis_ICD10 must be in this table as written, with its documentation in the case folder:",
      "D83.9 CVID: MD progress note; IgG < 400 mg/dL collected within the last 6 months before the PA or claim (specimen COLLECTION date governs, not the report date).",
      "D80.0 Hereditary hypogammaglobulinemia: MD note with hereditary basis; IgG level. D80.1 Nonfamilial: IgG < 400 mg/dL lab; MD progress note. D80.6: clinical notes; specialist consult preferred. D89.3: transplant documentation; oncology/hematology consult.",
      "G61.0 Guillain-Barré: neurology consult; NCS/EMG; MD LMN. G70.00 Myasthenia gravis: EMG/NCS; neurology note. G70.01 with exacerbation: crisis history; set auth.xlsx Urgency = STAT. D69.3 ITP: platelet labs; MD diagnosis note. B20 HIV: CD4; viral load; diagnosis; LMN. Z94.0–Z94.9 transplant: surgical record or discharge summary.",
      "Code not in the table, or documentation missing or out of window: the PA must not be submitted ([PA HOLD] and Stop Protocol per 8.2)."],
     must_not=["Do not submit a PA or claim for an ICD-10 code that is not in the table or lacks its required documentation.", "Do not assign an ICD-10 code not supported by the physician's documentation and the PA approval."])


def main() -> None:
    templates = json.load(open(sys.argv[1]))
    graph = {
        "id": "CareIG_SOP_v5.0", "version": "claude_v1",
        "built_by": "Claude, by hand from the SOP text only (no case files, emails, rubric or tests read); hypothesis test 2026-11-04",
        "global_rules": GLOBAL_RULES, "triage": WORKFLOW, "escalation": ESCALATION, "routing": {},
        "procedures": P, "templates": templates,
        "definitions": {"DOS": "Date of Service: the date the patient received the infusion visit", "CASE_ID": "LastName_MMDDYYYY with the patient's DOB"},
        "calendar": {"workdays": [0, 1, 2, 3, 4], "holidays": []},
    }
    json.dump(graph, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    print(len(P), "procedures,", len(templates), "templates,", len(GLOBAL_RULES), "global rules")


if __name__ == "__main__":
    main()
