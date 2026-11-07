"""Hand-built procedure graph of Crestwood_University_HR_SOP_v5 (HANDBOOK task hr_crestwood_university_79786c46).

Hypothesis test (2026-11-04): does a high-quality procedure graph, queried by the agent through policy tools, help a
strong agent? Built by Claude from the SOP text only. The task's emails, rubric and tests were NOT read. Every node
cites its SOP section; "inference" marks the few places where the SOP is silent and the graph says what it assumes.

    python3 -I crestwood_graph.py <templates.json> <out.json>
"""

import json
import sys

G = "global"
GLOBAL_RULES = [
    {
        "id": "G-scope",
        "src": "§1",
        "rule": "Do not deviate from the SOP. A situation the SOP does not cover: escalate to the HR Director by posting in Slack: [OUT OF SCOPE] – [email subject line]. (inference: channel #hr-escalations, the channel for issues requiring HR Director attention, §5)",
    },
    {
        "id": "G-role",
        "src": "§1, §11",
        "rule": "The HR Coordinator's role is administrative and digital (email, Slack, calendar, Jira, spreadsheets, templates). Physical tasks (in-person orientation, examining physical documents, badges) are done by the hiring manager or supervisor.",
    },
    {
        "id": "G-verify",
        "src": "§6",
        "rule": "Verify every employee and case fact from the reference files before acting; never from memory.",
    },
    {
        "id": "G-dates",
        "src": "§3.1",
        "rule": "Times are MST/MDT. Dates in any field or message: MM/DD/YYYY. Timestamps in tracking spreadsheets: MM/DD/YYYY HH:MMam/pm.",
    },
    {
        "id": "G-email-address",
        "src": "§3.2",
        "rule": "Employee email: look it up in the Email column of employee_roster.xlsx (format first initial.last name@crestwood.edu). New hires not yet provisioned: use the personal email from the new hire notification.",
    },
    {
        "id": "G-slack",
        "src": "§5",
        "rule": "Case communication only in the designated channels, never direct messages: #hr-onboarding (new hires, I-9, benefits reminders, orientation); #hr-offboarding (resignations, terminations, COBRA, final pay, access revocation); #hr-leave-requests (FMLA, ADA, PTO disputes, return-to-work); #hr-performance (PIP, evaluations, discipline); #hr-recruiting (requisitions, screening, offers, background checks); #hr-escalations (HR Director/VP attention: legal threats, compliance deadlines, cases unresolved > 10 business days); #hr-general (non-case questions).",
    },
    {
        "id": "G-business-days",
        "src": "§10",
        "rule": "SLA and 'business day' counts: Monday–Friday, excluding holidays. 2026 holidays: 01/01, 01/19, 02/16, 05/25, 07/03, 09/07, 11/26, 11/27, 12/24–12/31. Use policy__add_days for date arithmetic.",
    },
    {
        "id": "G-templates",
        "src": "§18",
        "rule": "Templates must be used as written; personalize the greeting only; replace every [bracketed] placeholder with confirmed information; never send a template with an unfilled placeholder. Get exact text with policy__get_template.",
    },
    {
        "id": "G-subject",
        "src": "§19",
        "rule": "New email (not reply/forward) subject: [Template Name] — [Employee or Candidate Last Name], [Employee ID if applicable]. Replies and forwards keep the existing subject unchanged.",
    },
    {
        "id": "G-slack-default",
        "src": "§19",
        "rule": "Where an action needs a Slack post and the section gives no format: [SOP SUBHEADER]: [Employee Name], [Employee ID], Jira: [Ticket ID] (e.g. FINAL PAY & ACCRUED PTO: Maria Torres, E-1042, Jira: OFFBOARD-Torres-03152026).",
    },
    {
        "id": "G-jira-description",
        "src": "§19",
        "rule": "A new Jira ticket description starts empty; add a field only when a section instructs it, in the exact form: 'Employee Name: [Full Name]', 'Employee ID: [ID]' (section references an employee), 'Assignee: [Full Name]' (routing table names one), 'Priority: [P1/P2/P3/P4]' (section asks for a priority), 'Deadline: [MM/DD/YYYY]' and 'Status: [value]' (compliance or action deadline). When updating a ticket, update the field in the description and log the change as a comment.",
    },
    {
        "id": "G-jira-comment",
        "src": "§19",
        "rule": "Jira comment format: [Date and time] [SOP SUBHEADER] — [Action] — [Object]. Actions: TEMPLATE SENT (Template [#] to [recipient email]); FILE ATTACHED ([filename] to [recipient email]); EMAIL FORWARDED (to [recipient email]); SPREADSHEET UPDATED ([filename] — [column name] set to [value]); CALENDAR EVENT CREATED/REMOVED ([event title] on [MM/DD/YYYY]); SLACK POSTED ([channel name]); WAITING ON ([who] — [what is needed]); CONFIRMED RECEIVED ([document or item] from [sender]); TICKET UPDATED ([Field Name] from [old] to [new]); ESCALATED (to [recipient] — [reason]); CLOSED (All steps completed.). Example: 02/18/2026 10:30am [13.1] — TEMPLATE SENT — Template 15 to j.smith@crestwood.edu",
    },
    {
        "id": "G-multi-topic",
        "src": "§8",
        "rule": "An email with more than one issue: a separate Jira ticket per issue, ONE consolidated reply; the highest priority of any issue applies to the whole email for SLA and folder routing.",
    },
    {
        "id": "G-replies",
        "src": "§8",
        "rule": "A reply to a previous email continues the existing case: add to the existing Jira ticket, do not create a new ticket, do not re-send templates already sent.",
    },
    {
        "id": "G-jira-name-exception",
        "src": "§8",
        "rule": "If a section defines its own Jira ticket name format, use it instead of the routing table format.",
    },
]

TRIAGE = {
    "id": "triage",
    "src": "§8",
    "name": "Triage & Routing (every incoming request; internal HR team messages are exempt)",
    "steps": [
        "1. Confirm the requester is in employee_roster.xlsx or recruiting_tracker.xlsx. Not found → reply with Template 1 and take no further action (unless they reply with clarifying information). STOP.",
        "2. Identify the request category (Onboarding, Offboarding, Leave Management, Performance Management, Recruiting, Benefits & Payroll, Employee Relations, General Inquiries; §7).",
        "3. Employee relations (workplace complaint, harassment, discrimination) → forward immediately to m.voss@crestwood.edu, reply with Template 2. Take no further action. STOP.",
        "4. Payroll or compensation → forward to c.briggs@crestwood.edu, reply with Template 3. Take no further action. STOP.",
        "5. Check Jira for an existing open ticket for the same employee and request type. If one exists, add the new information as a comment; do not create a duplicate.",
        "6. Otherwise create a Jira ticket with the naming convention and assignee from the routing table (or the section's own format).",
        "7. Act per the procedure for the category (policy__get_procedure), with the templates of §18.",
        "8. Email housekeeping per §17 (procedure 'housekeeping').",
    ],
    "hr_team": {
        "Dr. James Whitfield": "VP of HR, j.whitfield@crestwood.edu",
        "Nicole Ashford": "HR Director, n.ashford@crestwood.edu",
        "Patricia Huang": "Benefits & Leave Manager, p.huang@crestwood.edu",
        "Derek Okonkwo": "Recruiting & Talent Manager, d.okonkwo@crestwood.edu",
        "Marta Voss": "Employee Relations Specialist, m.voss@crestwood.edu",
        "Calvin Briggs": "Payroll Liaison, c.briggs@crestwood.edu",
        "Jenna Park": "IT Access Coordinator, j.park@crestwood.edu",
    },
}

ROUTING = {  # §8 naming table, §17 folders, §5 channels
    "Onboarding": {
        "jira": "ONBOARD-[Employee Last Name]-[Employee's start date MMDDYYYY]",
        "assignee": "HR Coordinator on duty",
        "folder": "Onboarding",
        "channel_if_a_step_posts": "#hr-onboarding",
    },
    "Offboarding": {
        "jira": "OFFBOARD-[Employee Last Name]-[Employee's last day of work MMDDYYYY]",
        "assignee": "HR Coordinator on duty",
        "folder": "Offboarding",
        "channel_if_a_step_posts": "#hr-offboarding",
    },
    "Leave Management": {
        "jira": "LEAVE-[Employee Last Name]-[Date the leave request was received by HR MMDDYYYY]",
        "assignee": "Patricia Huang",
        "folder": "Leave",
        "channel_if_a_step_posts": "#hr-leave-requests",
    },
    "Performance Management": {
        "jira": "PERF-[Employee Last Name]-[Date the action was initiated MMDDYYYY]",
        "assignee": "Nicole Ashford",
        "folder": "Performance",
        "channel_if_a_step_posts": "#hr-performance",
    },
    "Recruiting": {
        "jira": "RECRUIT-[...]-[Date the requisition was approved MMDDYYYY]",
        "assignee": "Derek Okonkwo",
        "folder": "Recruiting",
        "channel_if_a_step_posts": "#hr-recruiting",
    },
    "Employee Relations": {
        "jira": "ER-[Employee Last Name]-[Date the complaint was received MMDDYYYY] (but triage step 3 says forward and take no further action)",
        "assignee": "Marta Voss",
        "folder": "General (forwarded only)",
        "channel_if_a_step_posts": None,
    },
    "Benefits & Payroll": {
        "jira": "BENEFITS-[Employee Last Name]-[Date the request was received MMDDYYYY]",
        "assignee": "Calvin Briggs / Patricia Huang",
        "folder": "General (payroll: forwarded only)",
        "channel_if_a_step_posts": None,
    },
    "General Inquiries": {
        "jira": None,
        "assignee": None,
        "folder": "General",
        "channel_if_a_step_posts": "#hr-general",
    },
}

HOUSEKEEPING = {
    "id": "housekeeping",
    "src": "§17",
    "name": "Email housekeeping (after processing EVERY email)",
    "steps": [
        "Mark every processed email as read, without exception.",
        "P1/P2 emails: leave in Inbox and flag as important; do not move to a folder until the case is fully resolved (once resolved: keep the flag and move to the topic folder).",
        "P3/P4 emails: move to the matching folder; do not flag.",
        "Forwarded-only emails (e.g. payroll, employee relations): move to 'General'.",
        "Folder names exactly: Onboarding (precedence 1), Offboarding (2), Leave (3), Performance (4), Recruiting (5), General (6: forwarded-only, policy questions, employment verifications, anything already resolved). Never create new folders.",
        "An email with several topics in different folders: the folder with the highest precedence (lowest number).",
    ],
}

PRIORITY = {
    "id": "priority",
    "src": "§9",
    "name": "Priority matrix",
    "levels": [
        "P1 Urgent (same business day): compliance deadline within 24 hours; legal or safety issue; employee locked out of pay or benefits. E.g. I-9 deadline expiring today; COBRA 14-day window closing; workplace safety threat.",
        "P2 High (1 business day): compliance deadline within 3 business days; formal complaint; FMLA eligibility determination; PIP-related termination in progress. E.g. I-9 due within 3 days; FMLA certification deadline.",
        "P3 Standard (3 business days): routine processing, no imminent deadline; standard onboarding/offboarding (start date > 3 days away); evaluation scheduling; PTO balance inquiries; standard resignation.",
        "P4 Low (5 business days): general inquiries; employment verification; policy questions; document requests (e.g. asking about PTO policy).",
    ],
}

ESCALATION = {
    "id": "escalation",
    "src": "§16",
    "name": "Escalations",
    "steps": [
        "Escalate to the HR Director (Nicole Ashford) for: any P1 issue; any case unresolved for more than 10 business days; any legal threat, reference to an attorney or regulatory complaint; potential harm to an employee or the university; any media inquiry.",
        "Legal threat: do NOT reply to the email. Post to #hr-escalations: LEGAL THREAT: [Employee Name], [Subject Line] – do not reply. Forward to hr-escalations@crestwood.edu.",
        "Media inquiry: do NOT reply. Forward to communications@crestwood.edu and to hr-escalations@crestwood.edu.",
    ],
    "must_not": ["Never reply to an email that contains a legal threat or a media inquiry."],
}

P = []  # procedures


def proc(
    pid,
    name,
    category,
    applies,
    steps,
    inputs=(),
    decisions=(),
    must_not=(),
    links=(),
    deadlines=(),
    notes=(),
):
    P.append(
        {
            "id": pid,
            "name": name,
            "category": category,
            "applies_when": applies,
            "inputs": list(inputs),
            "decisions": list(decisions),
            "steps": list(steps),
            "must_not": list(must_not),
            "links": list(links),
            "deadlines": list(deadlines),
            "notes": list(notes),
            "src": f"§{pid}",
        }
    )


proc(
    "11.1",
    "Receiving the New Hire Notification",
    "Onboarding",
    "A hiring manager or the recruiting team confirms a new hire (name, personal email, position, department, campus, start date, classification).",
    [
        "1. employee_roster.xlsx: add a row with all provided details; hire date; status 'Onboarding'.",
        "2. onboarding_checklist.xlsx: add a row for the employee; all checklist fields blank.",
        "3. Jira: create ONBOARD-[Last Name]-[Start Date MMDDYYYY].",
        "4. Slack #hr-onboarding: NEW HIRE: [Employee Name], [Position], [Department], [Campus], Start Date: [MM/DD/YYYY], Jira: [Ticket ID]",
        "5. Email Template 4 (New Hire Welcome) to the employee's PERSONAL email; CC the hiring manager; attach i9_form.pdf (the template says it is attached).",
        "6. Email Template 5 (IT Access Provisioning Request) to j.park@crestwood.edu with name, position, department, campus, start date, supervisor name.",
        "7. Email Template 31 (Orientation Coordinator Request) to the hiring manager; attach i9_form.pdf AND benefits_enrollment_packet.pdf.",
        "8. Calendar: event 'Orientation – [Employee Name]' on the first day, 9:00am–12:00pm MST.",
    ],
    links=[{"type": "next", "to": "11.2"}, {"type": "next", "to": "11.3"}, {"type": "next", "to": "11.4"}],
    notes=[
        "Priority P3 if the start date is more than 3 days away; P2 if the I-9 is due within 3 business days."
    ],
)

proc(
    "11.2",
    "I-9 Employment Eligibility Verification",
    "Onboarding",
    "A new employee's I-9 is due or overdue, or a completed I-9 arrives.",
    [
        "Upon receipt of the completed, signed I-9 (from the hiring manager): record the I-9 completion date in onboarding_checklist.xlsx; update the Jira ticket.",
        "Day 2, I-9 not received: Template 6 (I-9 Urgent Reminder) to the HIRING MANAGER (not the employee); CC the employee.",
        "Day 3, still not received (the federal deadline): send a follow-up to the hiring manager; Slack #hr-escalations: I-9 OVERDUE: [Employee Name], [Employee ID], Start Date: [MM/DD/YYYY], Deadline: [MM/DD/YYYY] – Section 2 not received; forward to n.ashford@crestwood.edu.",
        "After Day 3 (deadline passed): forward to n.ashford@crestwood.edu AND j.whitfield@crestwood.edu; Template 7 to the hiring manager (employee may not continue working until the I-9 is completed); post to #hr-escalations.",
    ],
    inputs=[
        {"fact": "start date", "source": "employee_roster.xlsx (hire date) / onboarding_checklist.xlsx"},
        {
            "fact": "I-9 completion",
            "source": "onboarding_checklist.xlsx I-9 field; hr@ inbox for the scanned form",
        },
    ],
    deadlines=[
        "Section 1: by the employee on or before the first day.",
        "Section 2: by the hiring manager within 3 business days of the first day of work (the SOP calls the federal deadline 'Day 3'). Count business days with policy__add_days.",
    ],
    notes=["P1 if the I-9 deadline expires today; P2 if due within 3 business days."],
)

proc(
    "11.3",
    "Benefits Enrollment",
    "Onboarding",
    "A new employee is within or past the 30-day benefits enrollment window, or an enrollment/waiver arrives.",
    [
        "Day 1: (packet given by the hiring manager via Template 31) record 'Packet Provided' and the date in onboarding_checklist.xlsx.",
        "Day 15: if benefits_enrollment.xlsx shows no enrollment or waiver → Template 8 (Benefits Enrollment Reminder) to the employee; log the reminder date in onboarding_checklist.xlsx.",
        "Day 25: if still none → Template 9 (Final Benefits Notice) to the employee, CC Patricia Huang (p.huang@crestwood.edu); log in onboarding_checklist.xlsx.",
        "Day 30 (deadline): if still none → update benefits_enrollment.xlsx with 'Default Enrollment' and the date; Template 10 to the employee confirming default enrollment.",
    ],
    inputs=[
        {"fact": "start date", "source": "employee_roster.xlsx"},
        {"fact": "enrollment or waiver", "source": "benefits_enrollment.xlsx"},
    ],
    deadlines=[
        "Window: 30 calendar days from the start date; if the 30th day is a weekend or holiday, the deadline moves to the next business day.",
        "Default enrollment effective date: the first day of the month after the end of the 30-day window. SOP example: start 03/10/2026 → window ends 04/09/2026 → effective 05/01/2026.",
    ],
)

proc(
    "11.4",
    "Onboarding Completion",
    "Onboarding",
    "All onboarding checklist items are complete (I-9 received, benefits enrolled or waived, IT access confirmed, orientation completed).",
    [
        "employee_roster.xlsx: change status from 'Onboarding' to 'Active'.",
        "Slack #hr-onboarding: ONBOARDING COMPLETE: [Employee Name], [Employee ID], [MM/DD/YYYY]",
    ],
)

proc(
    "12.1",
    "Receiving Separation Notice",
    "Offboarding",
    "HR receives notice that an employee is separating: voluntary resignation, involuntary termination, retirement or end of contract.",
    [
        "1. employee_roster.xlsx: confirm the employee's record; note hire date, department, campus, supervisor.",
        "2. Jira: create OFFBOARD-[Last Name]-[Last Day MMDDYYYY].",
        "3. Slack #hr-offboarding: SEPARATION: [Employee Name], [Employee ID], [Separation Type], Last Day: [MM/DD/YYYY], Jira: [Ticket ID]",
        "Then run ALL of 12.2 (COBRA), 12.3 (final pay), 12.4 (access revocation), 12.5 (exit interview, voluntary only) and 12.6 (completion).",
    ],
    decisions=[
        {
            "id": "authorized",
            "rule": "Involuntary termination: proceed only with written authorization from Nicole Ashford or Marta Voss.",
            "else": "do not initiate involuntary offboarding",
        }
    ],
    must_not=[
        "Do not initiate involuntary offboarding without written authorization from Nicole Ashford (HR Director) or Marta Voss (Employee Relations Specialist).",
        "Notice periods (exempt 20 business days, non-exempt 10) are guidelines, not requirements: do not reject a short notice.",
    ],
    links=[{"type": "next", "to": t} for t in ("12.2", "12.3", "12.4", "12.5", "12.6")],
)

proc(
    "12.2",
    "COBRA Notification",
    "Offboarding",
    "Every separation (check whether the employee was enrolled in health benefits).",
    [
        "1. benefits_enrollment.xlsx: confirm the current benefits enrollment status.",
        "2. If enrolled in health benefits: Template 11 (COBRA Notification) to the employee within 14 calendar days of the last day; record the date sent in the Jira ticket AND in benefits_enrollment.xlsx 'COBRA Notification Date'.",
        "3. If enrolled: benefits_enrollment.xlsx status → 'Separated – COBRA Notified' and record the notification date.",
        "If NOT enrolled in health benefits: no COBRA notice; Jira note 'No COBRA required – employee not enrolled in health benefits.'; benefits_enrollment.xlsx status → 'Separated – No COBRA'.",
    ],
    inputs=[
        {"fact": "health benefits enrollment", "source": "benefits_enrollment.xlsx"},
        {"fact": "last day", "source": "notice / employee_roster.xlsx"},
    ],
    decisions=[
        {
            "id": "health_enrolled",
            "rule": "enrolled in university health benefits per benefits_enrollment.xlsx",
            "then": "Template 11 path",
            "else": "No COBRA path",
        }
    ],
    deadlines=[
        "COBRA notice within 14 calendar days of the last day (P1 if that window closes within 24 hours)."
    ],
)

proc(
    "12.3",
    "Final Pay & Accrued PTO",
    "Offboarding",
    "Every separation.",
    [
        "1. leave_tracker.xlsx: read the 'Current PTO Balance' (do not calculate it).",
        "2. Email Template 12 (Final Pay Request to Payroll) to c.briggs@crestwood.edu: name, employee ID, last day, separation type, PTO balance as read; pick the Colorado-law sentence: involuntary → final pay due immediately upon termination; voluntary → due on the next regular payday.",
        "3. Record the final pay request date in the Jira ticket.",
    ],
    inputs=[{"fact": "Current PTO Balance", "source": "leave_tracker.xlsx"}],
)

proc(
    "12.4",
    "Access Revocation",
    "Offboarding",
    "Every separation.",
    [
        "1. Email Template 13 (Access Revocation Request) to j.park@crestwood.edu: name, employee ID, last day, timing = 'Immediately' for involuntary, 'End of business on last day' for voluntary/retirement.",
        "2. Update the Jira ticket when IT confirms revocation.",
    ],
    deadlines=["Revoke on the last day; involuntary: immediately upon notification."],
)

proc(
    "12.5",
    "Exit Interview",
    "Offboarding",
    "A voluntarily separating employee (not involuntary terminations).",
    [
        "1. Template 14 (Exit Interview Invitation) to the employee within 2 business days of receiving the resignation notice.",
        "2. If the employee accepts: Calendar 30-minute event 'Exit Interview – [Employee Name]' with the employee and Nicole Ashford.",
        "3. After the interview: save the completed exit interview form as a PDF in the employee's file.",
    ],
    must_not=["No exit interview for involuntary terminations."],
)

proc(
    "12.6",
    "Offboarding Completion",
    "Offboarding",
    "All offboarding steps are complete (COBRA sent or noted not required, final pay requested, access revoked, exit interview completed or declined).",
    [
        "employee_roster.xlsx: status → 'Separated'; record the last day and separation type.",
        "Slack #hr-offboarding: OFFBOARDING COMPLETE: [Employee Name], [Employee ID], Separation Type: [Type], Last Day: [MM/DD/YYYY]",
    ],
)

proc(
    "13.1",
    "FMLA Leave Requests",
    "Leave Management",
    "An employee requests FMLA leave, or an FMLA medical certification arrives or is overdue.",
    [
        "Eligibility: (1) employee_roster.xlsx hire date → months employed to today; fewer than 12 → INELIGIBLE. (2) employee_roster.xlsx 'Hours Worked (Trailing 12 Months)' below 1,250 → INELIGIBLE. (3) Both met → ELIGIBLE.",
        "ELIGIBLE 4. Template 15 (FMLA Eligibility Notice – Approved) to the employee within 5 business days of receiving the request; certification due 15 calendar days after the notice.",
        "ELIGIBLE 5. Jira: LEAVE-[Last Name]-[Date request received MMDDYYYY].",
        "ELIGIBLE 6. Slack #hr-leave-requests: FMLA REQUEST: [Employee Name], [Employee ID], Eligible: YES, Certification Due: [MM/DD/YYYY], Jira: [Ticket ID]",
        "ELIGIBLE 7. Calendar reminder 'FMLA Certification Due – [Employee Name]' on the certification deadline date.",
        "ELIGIBLE 8. When the certification arrives: forward to p.huang@crestwood.edu; leave_tracker.xlsx leave dates + status 'Approved – Pending Certification Review'.",
        "ELIGIBLE 9. After Patricia approves: leave_tracker.xlsx status 'Approved'; Template 16 (FMLA Leave Confirmed) to the employee, CC the supervisor of record.",
        "INELIGIBLE 4. Template 17 (FMLA Eligibility Notice – Denied) within 5 business days with the reason: 'employed for fewer than 12 months', 'fewer than 1,250 hours worked in the preceding 12 months' or 'both'; CC Patricia Huang.",
        "INELIGIBLE 5. Jira: LEAVE-[Last Name]-[Date request received MMDDYYYY]; leave_tracker.xlsx request date + status 'Denied – [Reason]'.",
        "CERTIFICATION NOT RECEIVED within 15 calendar days: Template 18 (FMLA Certification Overdue) to the employee; Slack #hr-leave-requests: FMLA CERTIFICATION OVERDUE: [Employee Name], [Employee ID], Due: [MM/DD/YYYY], [X] days overdue; forward to p.huang@crestwood.edu (she decides denial or extension).",
    ],
    inputs=[
        {"fact": "hire date", "source": "employee_roster.xlsx"},
        {"fact": "Hours Worked (Trailing 12 Months)", "source": "employee_roster.xlsx"},
        {"fact": "request received date", "source": "email date"},
    ],
    decisions=[
        {
            "id": "fmla_eligible",
            "rule": "months_between(hire_date, today) >= 12 AND hours_trailing_12m >= 1250",
            "then": "ELIGIBLE steps",
            "else": "INELIGIBLE steps with the reason",
        }
    ],
    links=[{"type": "next", "to": "13.4", "when": "the employee later returns from leave"}],
    notes=["Priority P2 (FMLA eligibility determination)."],
)

proc(
    "13.2",
    "ADA Accommodation Requests",
    "Leave Management",
    "An employee requests a workplace accommodation due to a disability.",
    [
        "1. Forward the request to p.huang@crestwood.edu immediately.",
        "2. Jira: LEAVE-[Last Name]-ADA-[Date request received MMDDYYYY].",
        "3. Template 19 (ADA Accommodation Request Acknowledged) to the employee within 2 business days.",
        "4. Patricia Huang runs the interactive process; the HR Coordinator only helps with scheduling.",
    ],
    must_not=[
        "Do not assess or deny the request yourself.",
        "Do not discuss the disability or accommodation in Slack; email only, recipients limited to Patricia Huang and Nicole Ashford.",
    ],
)

proc(
    "13.3",
    "PTO Balance Inquiries",
    "Leave Management",
    "An employee asks for their PTO balance.",
    [
        "1. leave_tracker.xlsx: read 'Current PTO Balance' and 'PTO Accrual Rate' for the employee.",
        "2. Reply with Template 20 (PTO Balance Response) with the balance and accrual rate exactly as shown in the spreadsheet.",
    ],
    inputs=[{"fact": "Current PTO Balance, PTO Accrual Rate", "source": "leave_tracker.xlsx"}],
    must_not=["Do not calculate the PTO balance; use the spreadsheet value."],
    notes=["Priority P3 (PTO balance inquiry)."],
)

proc(
    "13.4",
    "Return-to-Work Clearance",
    "Leave Management",
    "An employee returning from FMLA or medical leave notifies HR of the return date, or sends a fitness-for-duty certification.",
    [
        "1. When the employee gives the intended return date: Template 21 (Return-to-Work Requirements) specifying the documentation needed.",
        "2. When the fitness-for-duty certification arrives: forward to p.huang@crestwood.edu; leave_tracker.xlsx return date + status 'Returned'.",
        "3. Email the supervisor of record that the employee is cleared: Template 22.",
    ],
)

proc(
    "14.1",
    "Annual Performance Evaluations",
    "Performance Management",
    "Staff annual evaluation cycle (not faculty; faculty evaluations belong to the Provost's Office).",
    [
        "March 1: Template 23 to all supervisors with their direct reports due (all active staff from employee_roster.xlsx).",
        "May 1: Template 24 to supervisors who have not submitted.",
        "June 15: Template 25 to supervisors with outstanding evaluations; CC Nicole Ashford.",
        "When evaluations arrive: performance_log.xlsx evaluation date, rating, evaluator; file the signed evaluation as PDF.",
    ],
    must_not=["This SOP does not cover faculty evaluations."],
)

proc(
    "14.2",
    "Probationary Reviews",
    "Performance Management",
    "A new staff employee's 90-day probation (review due by calendar day 85), or a probationary review arrives.",
    [
        "Day 60: Template 26 (Probationary Review Reminder) to the supervisor (review due by Day 85).",
        "Day 85, not received: follow-up to the supervisor; CC Nicole Ashford.",
        "When received: update performance_log.xlsx; if the rating is 'Unsatisfactory', forward immediately to n.ashford@crestwood.edu.",
    ],
    must_not=["Do not communicate the review result to the employee (the supervisor does)."],
)

proc(
    "14.3",
    "Progressive Discipline",
    "Performance Management",
    "A supervisor reports a verbal warning, sends a written warning draft, a PIP draft, a PIP outcome, or a termination for performance.",
    [
        "Order: verbal warning → written warning → PIP → termination; steps may not be skipped unless authorized in writing by Nicole Ashford or Dr. James Whitfield.",
        "Verbal warning: performance_log.xlsx date, type 'Verbal Warning', brief description. No template to the employee.",
        "Written warning draft: forward to n.ashford@crestwood.edu for approval; after delivery the signed document is filed as PDF; update performance_log.xlsx.",
        "PIP draft: 1 (supervisor drafts with pip_template.docx) 2 forward to n.ashford@crestwood.edu for approval; 3 once approved: Jira PERF-[Last Name]-PIP-[PIP Start Date MMDDYYYY]; 4 Calendar 'PIP Review – [Employee Name]' on the PIP end date; 5 Slack #hr-performance: PIP INITIATED: [Employee Name], [Employee ID], Duration: [30/60/90] days, End Date: [MM/DD/YYYY], Jira: [Ticket ID]; 6 file the signed PIP as PDF, update performance_log.xlsx.",
        "PIP end date: goals met → performance_log.xlsx status 'PIP – Completed Successfully'; not met → forward to n.ashford@crestwood.edu (extension or termination).",
        "Termination after discipline: requires written authorization from BOTH Nicole Ashford AND Dr. James Whitfield; then run Offboarding (§12) with separation type 'Involuntary Termination'.",
    ],
    must_not=[
        "Do not skip discipline steps without written authorization from Nicole Ashford or Dr. James Whitfield.",
        "Do not deliver a PIP before Nicole Ashford approves it.",
        "No termination for performance without written authorization from BOTH Nicole Ashford and Dr. James Whitfield.",
    ],
    links=[{"type": "next", "to": "12.1", "when": "authorized termination"}],
)

proc(
    "15.1",
    "Requisition Approval",
    "Recruiting",
    "A hiring manager submits a Personnel Requisition Form.",
    [
        "1-2. Verify all three signatures: department head, dean/VP, budget office confirmation. Any missing → reply with Template 27 listing the missing signatures; take no further action until all are received. STOP.",
        "3. All present: forward to d.okonkwo@crestwood.edu for final approval.",
        "4. Once approved: Jira RECRUIT-[Full Position Title]-[Approval Date MMDDYYYY] (e.g. RECRUIT-Administrative Assistant-03152026); recruiting_tracker.xlsx new row: position title, department, campus, requisition date, status 'Approved'.",
        "5. Slack #hr-recruiting: REQUISITION APPROVED: [Position Title], [Department], [Campus], Jira: [Ticket ID]",
    ],
    decisions=[
        {
            "id": "signatures",
            "rule": "department head AND dean/VP AND budget office signatures present",
            "else": "Template 27 and stop",
        }
    ],
    must_not=["No position may be posted or filled without an approved requisition."],
)

proc(
    "15.2",
    "Job Posting",
    "Recruiting",
    "An approved requisition needs a job posting.",
    [
        "1. Draft with job_posting_template.docx: title, department, campus, reporting supervisor, classification, salary range, minimum and preferred qualifications, application deadline, apply to applications@crestwood.edu.",
        "2. Send the draft to d.okonkwo@crestwood.edu for review and approval.",
        "3. Once approved: email the final posting as PDF to d.okonkwo@crestwood.edu; recruiting_tracker.xlsx status 'Posted' + posting date + application deadline.",
        "4. Calendar 'Posting Closes – [Position Title]' on the application deadline.",
    ],
    deadlines=[
        "Posted at least 10 business days (internal-only postings need Derek Okonkwo's written authorization)."
    ],
)

proc(
    "15.3",
    "Candidate Screening",
    "Recruiting",
    "Derek Okonkwo forwards the applications after the posting deadline.",
    [
        "1. Review the forwarded applications.",
        "2. Screen each against the minimum qualifications; recruiting_tracker.xlsx 'Meets MQ' or 'Does Not Meet MQ'.",
        "3. Send the list of qualified candidates to d.okonkwo@crestwood.edu and the hiring manager.",
        "4. Template 28 (Application Not Selected) to candidates who do not meet the MQ.",
    ],
)

proc(
    "15.4",
    "Interview Scheduling",
    "Recruiting",
    "The hiring manager selects candidates for interview, or availability/slot replies arrive.",
    [
        "1. Template 32 to the hiring manager (and search committee): availability within the next 10 business days.",
        "2. After their reply: Template 33 to each selected candidate with the slots; reply deadline 3 business days from the email.",
        "3. Assign slots; the same slot chosen twice goes to the first responder; email the others the remaining options.",
        "4. Template 29 (Interview Invitation) to each candidate with date, time, location, format, duration.",
        "5. Calendar 'Interview – [Candidate Name] – [Position Title]' per interview; invite all participants.",
        "6. recruiting_tracker.xlsx interview dates + status 'Interview Scheduled'.",
    ],
)

proc(
    "15.5",
    "Offer & Background Check",
    "Recruiting",
    "The hiring manager identifies a finalist; an offer is accepted; background check results arrive.",
    [
        "1. Email d.okonkwo@crestwood.edu: recommended candidate, proposed salary, start date, for approval.",
        "2. Once approved: offer letter from offer_letter_template.docx (title, department, campus, supervisor, salary, classification, start date, contingent on background check).",
        "3. Offer PDF to the candidate with Template 30; CC Derek Okonkwo and the hiring manager; response deadline 3 business days from today.",
        "4. On acceptance: mail the background check authorization form; recruiting_tracker.xlsx status 'Offer Accepted – Background Check Pending'.",
        "5. Results: forward to d.okonkwo@crestwood.edu; cleared → status 'Cleared – Ready for Onboarding' and start onboarding (§11); not cleared → Derek decides.",
        "6. Template 28 to all other interviewed candidates not selected.",
    ],
    links=[{"type": "next", "to": "11.1", "when": "background check cleared"}],
)

proc(
    "15.6",
    "Offer Rescission",
    "Recruiting",
    "A candidate rescinds acceptance of an offer.",
    ["Forward the email to d.okonkwo@crestwood.edu. No other action is required."],
)

DEFINITIONS = {
    "Probationary Period": "first 90 calendar days of employment for staff, first academic year for faculty",
    "Benefits Enrollment Window": "first 30 calendar days from the start date",
    "Supervisor of Record": "the direct supervisor listed in employee_roster.xlsx",
    "Qualifying Event": "marriage, birth, divorce, loss of other coverage: mid-year benefits changes or COBRA",
    "I-9": "Employment Eligibility Verification; required within 3 business days of the first day of work",
    "FMLA": "up to 12 weeks unpaid job-protected leave per year for eligible employees",
}
HOLIDAYS_2026 = [
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-05-25",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-11-27",
] + [f"2026-12-{d}" for d in range(24, 32)]


def main() -> None:
    templates = json.load(open(sys.argv[1]))
    graph = {
        "id": "Crestwood_University_HR_SOP_v5",
        "version": "claude_v1",
        "built_by": "Claude, by hand from the SOP text only (no emails, rubric or tests read); hypothesis test 2026-11-04",
        "global_rules": GLOBAL_RULES,
        "triage": TRIAGE,
        "routing": ROUTING,
        "housekeeping": HOUSEKEEPING,
        "priority": PRIORITY,
        "escalation": ESCALATION,
        "procedures": P,
        "templates": templates,
        "definitions": DEFINITIONS,
        "calendar": {"workdays": [0, 1, 2, 3, 4], "holidays": HOLIDAYS_2026},
    }
    json.dump(graph, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    print(len(P), "procedures,", len(templates), "templates,", len(GLOBAL_RULES), "global rules")


if __name__ == "__main__":
    main()
