DOCS = [
    {
        "id": "ws_rules",
        "kind": "tab",
        "spreadsheet": "ss_quality",
        "worksheet": "ws_rules",
        "trust": "trusted",
        "trust_reason": "company's own Data Quality sheet",
    },
    {
        "id": "ws_config",
        "kind": "tab",
        "spreadsheet": "ss_quality",
        "worksheet": "ws_config",
        "trust": "trusted",
        "trust_reason": "company's own Data Quality sheet",
    },
]

Q, C = "ws_rules:preamble:", "ws_config:preamble:"
AUDIT = ["zendesk_add_tags_to_ticket", "google_sheets_add_row"]
BUILD = {
    "types": {
        Q + "1": (["required_field", "eligibility_filter"], "must"),
        Q + "2": (["required_field", "eligibility_filter"], "must"),
        C + "1": (["required_field", "format"], "must"),
        C + "2": (["eligibility_filter", "exception_override"], "must_not"),
    },
    "rules": [
        dict(ids=[Q + "1"], type="verify", tools=AUDIT),
        dict(ids=[Q + "2"], type="verify", tools=AUDIT),
        dict(ids=[C + "1"], type="verify", tools=["gmail_send_email"]),
        dict(
            ids=[C + "2"],
            type="record_condition",
            tools=AUDIT,
            field="organization_id",
            op="equals",
            value="org_internal",
            effect="forbid",
            quote="Exempt_Org_ID | org_internal",
        ),
    ],
    "links": [
        ("exception_of", C + "2", Q + "1", "Exempt_Org_ID | org_internal"),
        ("exception_of", C + "2", Q + "2", "Exempt_Org_ID | org_internal"),
    ],
    "coverage": {},
}
