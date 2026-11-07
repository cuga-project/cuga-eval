DOCS = [
    {
        "id": "msg_send_rules",
        "kind": "email",
        "record": "msg_send_rules",
        "trust": "trusted",
        "trust_reason": "internal sender controller@company.example.com (Controller)",
    },
    {
        "id": "msg_alpine_delay",
        "kind": "email",
        "record": "msg_alpine_delay",
        "trust": "untrusted",
        "trust_reason": "external sender billing@alpine.example.com (a customer, Alpine Solutions)",
    },
]

R, X = "msg_send_rules:preamble:", "msg_alpine_delay:preamble:"
BUILD = {
    "types": {
        R + "1": ([], None),
        R + "2": (["eligibility_filter"], "must"),
        R + "3": (["prohibition", "eligibility_filter"], "must_not"),
        R + "4": (["prohibition", "eligibility_filter"], "must_not"),
        R + "5": (["threshold", "notification_duty"], "must"),
        R + "6": ([], None),
        X + "1": ([], None),
        X + "2": (["prohibition", "deadline"], "should"),
        X + "3": ([], None),
        X + "4": ([], None),
    },
    "rules": [
        dict(
            ids=[R + "2"],
            type="reference_status",
            tool="xero_email_invoice",
            arg="invoice_id",
            field="status",
            allowed=["AUTHORISED"],
            quote="Only send invoices with status AUTHORISED",
        ),
        dict(
            ids=[R + "3"],
            type="record_condition",
            tools=["xero_email_invoice"],
            field="sent_to_contact",
            op="equals",
            value=True,
            effect="forbid",
            quote="Do NOT send invoices that have already been marked as SentToContact",
        ),
        dict(
            ids=[R + "4"],
            type="record_condition",
            tools=["xero_email_invoice"],
            field="reference",
            op="contains",
            value="HOLD",
            effect="forbid",
            quote="Invoices with 'HOLD' in the reference field must NOT be sent",
        ),
        # review: remind only; xero_email_invoice has no cc argument and no tool can CC, so a deny would block a
        # correct send of an invoice over $25,000
        dict(ids=[R + "5"], type="verify", tools=["xero_email_invoice"], may_deny=False),
    ],
    "links": [],
    "coverage": {
        R + "1": ("out_of_scope", "list heading (the checks below apply before each send)"),
        R + "6": ("out_of_scope", "signature"),
    },
}
