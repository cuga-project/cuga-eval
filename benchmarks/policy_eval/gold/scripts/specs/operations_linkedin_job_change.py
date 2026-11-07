DOCS = [
    {
        "id": "ws_flagging_rules",
        "kind": "tab",
        "spreadsheet": "ss_contact_policy",
        "worksheet": "ws_flagging_rules",
        "columns": ["Rule", "Description"],
        "trust": "trusted",
        "trust_reason": "company's own Contact Management Policy sheet",
    },
    {
        "id": "msg_contact_note_001",
        "kind": "email",
        "record": "msg_contact_note_001",
        "trust": "trusted",
        "trust_reason": "internal sender sales-manager@company.example.com (staff context about a contact)",
    },
    {
        "id": "msg_rebrand_note_001",
        "kind": "email",
        "record": "msg_rebrand_note_001",
        "trust": "trusted",
        "trust_reason": "internal sender account-manager@company.example.com (staff context about a company rebrand)",
    },
]

F, C, R = "ws_flagging_rules:preamble:", "msg_contact_note_001:preamble:", "msg_rebrand_note_001:preamble:"
W = ["salesforce_contact_update", "salesforce_task_create", "slack_send_channel_message"]
BUILD = {
    "types": {
        F + "1": (["eligibility_filter", "exception_override"], "must_not"),
        F + "2": (["source_of_truth", "exception_override"], "must"),
        F + "3": (["eligibility_filter", "exception_override"], "must_not"),
        F + "4": (["definition", "eligibility_filter"], "must_not"),
        C + "1": (["source_of_truth"], None),
        C + "2": (["source_of_truth"], None),
        C + "3": (["prohibition", "eligibility_filter"], "must_not"),
        R + "1": (["source_of_truth"], None),
        R + "2": (["source_of_truth"], None),
        R + "3": (["source_of_truth"], None),
        R + "4": (["eligibility_filter"], "must_not"),
    },
    "rules": [
        # review: not on salesforce_task_create: its owner_id (owner_001) names every contact of that owner,
        # including the seconded one, so the follow-up task for a real job changer was denied
        dict(
            ids=[F + "1"],
            type="record_condition",
            tools=["salesforce_contact_update"],
            field="notes",
            op="contains",
            value="secondment",
            effect="forbid",
            quote="Contacts whose Salesforce Notes indicate a 'temporary secondment' or 'secondment' are not job changers",
        ),
        dict(ids=[F + "1"], type="verify", tools=["salesforce_task_create", "slack_send_channel_message"]),
        dict(ids=[F + "2"], type="verify", tools=W),
        dict(ids=[F + "3"], type="verify", tools=W),
        dict(ids=[F + "4"], type="verify", tools=W),
        dict(ids=[C + "1", C + "2", C + "3"], type="verify", tools=W),
        dict(ids=[R + "1", R + "2", R + "3", R + "4"], type="verify", tools=W),
    ],
    "links": [
        ("defines", F + "4", F + "1", "A change in job title at the SAME company is NOT a job change"),
        ("defines", F + "4", F + "3", "A change in job title at the SAME company is NOT a job change"),
        ("defines", F + "4", R + "4", "A change in job title at the SAME company is NOT a job change"),
    ],
    "definitions": {F + "4": "job change"},
    "coverage": {},
}
