DOCS = [
    {
        "id": "ws_thresholds",
        "kind": "tab",
        "spreadsheet": "ss_regional_policy",
        "worksheet": "ws_thresholds",
        "trust": "trusted",
        "trust_reason": "company's own Regional Meeting Policy sheet",
    },
]

T = "ws_thresholds:preamble:"
BUILD = {
    "types": {
        T + "1": (["threshold", "eligibility_filter"], "must"),
        T + "2": (["threshold", "eligibility_filter"], "must"),
        T + "3": (["threshold", "eligibility_filter"], "must"),
    },
    "rules": [
        dict(
            ids=[T + "1", T + "2", T + "3"],
            type="verify",
            tools=["zoom_create_meeting", "zoom_create_meeting_registrant", "gmail_send_email"],
        ),
    ],
    "links": [],
    "coverage": {},
}
