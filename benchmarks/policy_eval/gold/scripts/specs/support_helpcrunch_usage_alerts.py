DOCS = [
    {
        "id": "ws_thresholds",
        "kind": "tab",
        "spreadsheet": "ss_usage",
        "worksheet": "ws_thresholds",
        "trust": "trusted",
        "trust_reason": "company's own Usage Thresholds sheet",
    },
    {
        "id": "ws_alert_rules",
        "kind": "tab",
        "spreadsheet": "ss_usage",
        "worksheet": "ws_alert_rules",
        "trust": "trusted",
        "trust_reason": "company's own Usage Thresholds sheet",
    },
    {
        "id": "ws_onboarding_policy",
        "kind": "tab",
        "spreadsheet": "ss_usage",
        "worksheet": "ws_onboarding_policy",
        "trust": "trusted",
        "trust_reason": "company's own Usage Thresholds sheet",
    },
]

T, A, OLD = "ws_thresholds:preamble:", "ws_alert_rules:preamble:", "ws_onboarding_policy:preamble:"
TAG, MAIL, SF = "helpcrunch_tag_customer", "gmail_send_email", "salesforce_task_create"
BUILD = {
    "types": {
        T + "1": (["threshold", "exception_override"], "must"),
        T + "2": (["threshold", "exception_override"], "must"),
        A + "1": (["derived_value"], "must"),  # review: a 14-day look-back window is not a deadline
        A + "2": (["lookup_matrix", "eligibility_filter"], "must"),
        A + "3": (["eligibility_filter"], "must"),
        A + "4": (["allowed_values", "derived_value"], "must"),
        A + "5": (["notification_duty", "format"], "must"),
        A + "6": (["prohibition", "eligibility_filter"], "must_not"),
        OLD + "1": (["eligibility_filter", "exception_override"], "must_not"),
        OLD + "2": (["exception_override", "threshold"], "must"),
    },
    "rules": [
        dict(ids=[T + "1"], type="verify", tools=[TAG]),
        dict(
            ids=[T + "1"],
            type="record_condition",
            tools=[MAIL, SF],
            field="email",
            op="contains",
            value="@oldco",
            effect="forbid",
            quote="Customers from 'OldCo' domain are exempt from email alerts and Salesforce task creation",
        ),
        dict(ids=[T + "2"], type="verify", tools=[TAG]),
        dict(ids=[A + "1"], type="verify", tools=[TAG]),
        dict(ids=[A + "2"], type="verify", tools=[TAG]),
        dict(
            ids=[A + "4"],
            type="allowed_values",
            tool=TAG,
            arg="tag",
            values=["low-usage", "normal-usage", "high-usage"],
            quote="Tag as low-usage, normal-usage, or high-usage",
        ),
        dict(ids=[A + "4"], type="verify", tools=[TAG]),
        dict(
            ids=[A + "5"],
            type="duty",
            trigger={"tool": TAG, "when": {"tag": ["low-usage"]}},
            then={"tool": MAIL},
            quote="Customer classified as low-usage | Send email + create Salesforce task",
        ),
        dict(
            ids=[A + "5"],
            type="duty",
            trigger={"tool": TAG, "when": {"tag": ["low-usage"]}},
            then={"tool": SF},
            quote="Customer classified as low-usage | Send email + create Salesforce task",
        ),
        dict(ids=[A + "5"], type="verify", tools=[SF]),
        dict(ids=[A + "6"], type="verify", tools=[MAIL, SF]),
        dict(ids=[OLD + "1"], type="verify", tools=[TAG, MAIL, SF]),
        dict(ids=[OLD + "2"], type="verify", tools=[TAG]),
    ],
    "links": [
        (
            "exception_of",
            T + "1",
            A + "5",
            "Customers from 'OldCo' domain are exempt from email alerts and Salesforce task creation per exec override",
        ),
        ("exception_of", T + "2", A + "2", "classify using standard thresholds even if tagged trial"),
        ("exception_of", OLD + "1", A + "4", "Exclude entirely: no tag, no email, no SF task"),
        ("exception_of", OLD + "1", A + "5", "Exclude entirely: no tag, no email, no SF task"),
        ("exception_of", OLD + "2", A + "2", "Use standard thresholds instead of trial thresholds"),
        ("refers_to", A + "2", "ws_thresholds", "Use trial thresholds from ws_thresholds"),
        ("refers_to", A + "3", "ws_onboarding_policy", "See ws_onboarding_policy worksheet"),
        ("refers_to", A + "4", "ws_thresholds", "Based on feature_use count vs thresholds"),
    ],
    "coverage": {
        A + "3": (
            "link",
            "pointer: the onboarding exclusion rules are in the ws_onboarding_policy worksheet",
        ),
    },
}
