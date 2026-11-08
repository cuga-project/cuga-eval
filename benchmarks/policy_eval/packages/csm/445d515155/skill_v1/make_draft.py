"""Writes draft.json for the CSM Assistant Policy (policy.md + tools.json only)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
S = {
    st["id"]: st["text"]
    for d in json.load(open(os.path.join(HERE, "set.json")))["documents"]
    for sec in d["sections"]
    for st in sec["statements"]
}


def P(sid):
    return "policy:" + sid


def T(sid):
    return S[P(sid)]


IK = "interactions-knowledge:"

# ---------------------------------------------------------------- modality
modality = {}
for sid in ["preamble:3", "general-instructions:2", "general-instructions:5"]:
    modality[P(sid)] = "must"
for sid in ["preamble:4", "general-instructions:1", "general-instructions:3", "general-instructions:4"]:
    modality[P(sid)] = "must_not"
for i in range(1, 7):
    modality[P(f"administrator:{i}")] = "may"
for i in (4, 5, 6, 7):
    modality[P(f"agent:{i}")] = "may"
modality[P("agent:2")] = "must_not"
modality[P("agent:8")] = "must_not"
for i in (2, 3, 4, 6, 7):
    modality[P(f"manager:{i}")] = "may"
for i in (3, 4, 5, 6, 7):
    modality[P(f"customer-portal-user:{i}")] = "may"
modality[P("customer-portal-user:8")] = "must_not"
modality[P("customer-portal-user:9")] = "must_not"
for i in (1, 3, 4, 5, 6, 7, 8):
    modality[P(f"1:{i}")] = "must"
for i in (2, 3):
    modality[P(f"2:{i}")] = "may"
for i in (5, 6, 7):
    modality[P(f"2:{i}")] = "must"
for i in (2, 3, 4, 5, 9):
    modality[P(f"3:{i}")] = "may"
modality[P("3:7")] = "must_not"
modality[P("3:8")] = "must"
for i in (2, 3, 4, 5, 6, 8, 9):
    modality[P(f"4:{i}")] = "must"
modality[P("4:10")] = "must_not"
for i in (2, 3, 4, 5):
    modality[P(f"5:{i}")] = "must"
for i in (2, 3, 5):
    modality[P(f"6:{i}")] = "must"
modality[P("6:4")] = "must_not"
for i in (2, 4, 6):
    modality[P(f"7:{i}")] = "must"
modality[P("7:5")] = "may"
modality[P("8:1")] = "may"
for i in (6, 7, 8):
    modality[P(f"8:{i}")] = "must"
for i in (2, 3, 4):
    modality[P(f"9:{i}")] = "must"
modality[P("10:1")] = "must_not"
modality[P("10:2")] = "must_not"
for i in (2, 3, 5, 6):
    modality[P(f"11:{i}")] = "must"
modality[P("service-levels-timelines:4")] = "must"

ENUM_STMTS = {  # statement -> (field, [(tool, arg)])
    "users-groups:1": [("add_new_user", "role"), ("update_user_details", "role")],
    "users-groups:2": [("add_new_user_group", "type"), ("update_user_group", "type")],
    "geography:1": [("add_location", "city"), ("update_location", "city")],
    "geography:2": [("add_location", "country"), ("update_location", "country")],
    "accounts-contacts:1": [("create_new_account", "account_type"), ("update_account_details", "account_type")],
    "products-installed-base:1": [("add_new_product", "category"), ("update_product", "category")],
    "products-installed-base:2": [("add_new_product", "lifecycle_state"), ("update_product", "lifecycle_state")],
    "products-installed-base:3": [
        ("register_new_installed_product", "status"),
        ("update_installed_product_details", "status"),
    ],
    "contracts-entitlements-slas:1": [("enlist_new_contract", "contract_type"), ("update_contract", "contract_type")],
    "contracts-entitlements-slas:2": [("enlist_new_contract", "status"), ("update_contract", "status")],
    "contracts-entitlements-slas:3": [("add_new_entitlement", "support_level"), ("update_entitlement", "support_level")],
    "contracts-entitlements-slas:4": [
        ("add_new_entitlement", "coverage_hours"),
        ("update_entitlement", "coverage_hours"),
    ],
    "contracts-entitlements-slas:5": [("add_new_sla_definition", "metric"), ("update_sla_definition", "metric")],
    "contracts-entitlements-slas:6": [
        ("add_new_sla_definition", "applies_to_priority"),
        ("update_sla_definition", "applies_to_priority"),
    ],
    "case-management:1": [("create_new_case", "channel"), ("update_case", "channel")],
    "case-management:2": [("create_new_case", "priority"), ("update_case", "priority")],
    "case-management:3": [("create_new_case", "state"), ("update_case", "state")],
    "case-management:4": [("create_new_case", "escalation_reason"), ("update_case", "escalation_reason")],
    IK + "1": [("register_new_interaction", "channel"), ("update_interaction", "channel")],
    IK + "2": [("create_knowledge", "state"), ("update_knowledge", "state")],
    IK + "3": [("create_knowledge", "visibility"), ("update_knowledge", "visibility")],
    IK + "4": [("link_case_knowledge", "used_as"), ("updated_linked_case_knowledge", "used_as")],
}
for sid in ENUM_STMTS:
    modality[P(sid)] = "must"
modality[P(IK + "5")] = "must"
for i in (7, 8, 9, 10, 11, 13, 14, 15, 16, 19):
    modality[P(IK + str(i))] = "must"

# ---------------------------------------------------------------- rules
rules = []


def rule(rid, cls, level, sids, rtype, quote=None, why=None, **slots):
    r = {"id": rid, "class": cls, "level": level, "statement_ids": [P(s) for s in sids], "rule": {"type": rtype, **slots}}
    if quote:
        r["quote"] = quote
    if why:
        r["why"] = why
    rules.append(r)


def guidance(rid, sid, text=None, tools=None):
    slots = {"text": text or T(sid)}
    if tools:
        slots["tools"] = tools
    rule(rid, "guidance", "observe", [sid], "guidance", **slots)


# general
guidance("g_context", "preamble:3")
guidance("g_assume", "preamble:4")
rule("r_ids", "hard", "observe", ["preamble:4", "9:2", "11:2"], "id_provenance")
rule("r_grounded", "hard", "observe", ["preamble:4"], "grounded_values")
guidance("g_violation", "general-instructions:1")
guidance("g_sequential", "general-instructions:2")
guidance("g_no_outside_knowledge", "general-instructions:3")
guidance("g_no_ask", "general-instructions:4")
guidance("g_reason", "general-instructions:5")
guidance("g_disclose", "10:2")
guidance("g_use_knowledge", IK + "16")
guidance("g_enum_reject", IK + "5")

# roles
USER_GROUP_TOOLS = [
    "add_new_user",
    "update_user_details",
    "add_new_user_group",
    "update_user_group",
    "add_new_group_member",
    "remove_group_membership",
]
READ_ONLY_TOOLS = [  # accounts, contacts, products, contracts, entitlements
    "create_new_account",
    "update_account_details",
    "create_contact",
    "update_contact",
    "add_new_product",
    "update_product",
    "delete_products",
    "enlist_new_contract",
    "update_contract",
    "add_new_entitlement",
    "update_entitlement",
]
OTHER_WRITES = [  # write tools outside the agent's grant list and outside the two lists above
    "add_location",
    "update_location",
    "register_new_installed_product",
    "update_installed_product_details",
    "add_new_sla_definition",
    "update_sla_definition",
    "link_new_case_sla",
    "update_case_sla_details",
    "delete_case_slas",
    "create_knowledge",
    "update_knowledge",
    "delete_case_knowledge_linkages",
    "send_notification",
    "update_notification",
    "delete_notifications",
]
AGENT_GRANT = [
    "create_new_case",
    "update_case",
    "assign_case_to_user",
    "set_case_assignment_group",
    "register_new_interaction",
    "update_interaction",
    "link_case_knowledge",
    "updated_linked_case_knowledge",
]
rule(
    "r_agent_user_group",
    "hard",
    "deny",
    ["agent:8"],
    "role_permission",
    quote=T("agent:8"),
    tools=USER_GROUP_TOOLS,
    roles=["agent"],
    effect="forbid",
)
rule(
    "r_agent_read_only",
    "hard",
    "deny",
    ["agent:2"],
    "role_permission",
    quote=T("agent:2"),
    tools=READ_ONLY_TOOLS,
    roles=["agent"],
    effect="forbid",
)
rule(
    "r_agent_grant",
    "hard",
    "remind",
    ["agent:4", "agent:5", "agent:6", "agent:7"],
    "role_permission",
    quote=T("agent:4"),
    tools=OTHER_WRITES,
    roles=["agent"],
    effect="forbid",
)
rule(
    "r_manager_grant",
    "hard",
    "remind",
    ["manager:2", "manager:3", "manager:4", "manager:6", "manager:7"],
    "role_permission",
    quote=T("manager:2"),
    tools=USER_GROUP_TOOLS + READ_ONLY_TOOLS + [t for t in OTHER_WRITES if t != "update_knowledge"],
    roles=["manager"],
    effect="forbid",
)
CUSTOMER_GRANT = ["update_user_details", "create_new_case", "register_new_interaction"]
ALL_WRITES = USER_GROUP_TOOLS + READ_ONLY_TOOLS + OTHER_WRITES + AGENT_GRANT
rule(
    "r_customer_grant",
    "hard",
    "remind",
    ["customer-portal-user:3", "customer-portal-user:4", "customer-portal-user:5", "customer-portal-user:7"],
    "role_permission",
    quote=T("customer-portal-user:4"),
    tools=[t for t in ALL_WRITES if t not in CUSTOMER_GRANT],
    roles=["customer"],
    effect="forbid",
)
rule(
    "r_customer_internal",
    "hard",
    "remind",
    ["customer-portal-user:9"],
    "role_permission",
    quote=T("customer-portal-user:9"),
    tools=[
        "list_user_groups",
        "list_group_members",
        "find_user_group",
        "check_user_membership",
        "find_sla_definitions",
        "find_case_slas",
        "find_stage_wise_breached_case_sla_counts",
        "total_sum_of_target_mins_per_priority",
        "average_target_mins_per_priority",
    ],
    roles=["customer"],
    effect="forbid",
)
rule(
    "v_customer_own_account",
    "judgment",
    "remind",
    ["customer-portal-user:8"],
    "verify",
    why="Whether a record belongs to the customer's own account needs the logged-in user's account and the records "
    "read; no argument of these tools carries the logged-in user's account.",
    tools=[
        "get_accounts",
        "find_contacts",
        "search_cases",
        "retrieve_installed_products",
        "find_contracts",
        "find_entitlements",
        "find_interactions",
        "create_new_case",
        "update_user_details",
    ],
    statement="Customer (Portal User): " + T("customer-portal-user:8") + " " + T("customer-portal-user:3"),
)

# registering a case
rule(
    "r_case_contact_account",
    "hard",
    "block_once",
    ["1:1"],
    "membership",
    quote=T("1:1"),
    tool="create_new_case",
    arg="contact_id",
    group_arg="account_id",
)
rule(
    "r_case_short_description",
    "hard",
    "deny",
    ["1:3"],
    "required_args",
    quote=T("1:3"),
    tool="create_new_case",
    args=["short_description"],
)
rule(
    "r_case_channel", "hard", "deny", ["1:5"], "required_args", quote=T("1:5"), tool="create_new_case", args=["channel"]
)
rule(
    "v_case_product",
    "judgment",
    "remind",
    ["1:4"],
    "verify",
    why="The text accepts either product_id or installed_product_id; required_args needs every listed argument.",
    tools=["create_new_case"],
    statement="Registering a Customer Case: " + T("1:4"),
)
rule(
    "r_case_state_new",
    "hard",
    "remind",
    ["1:7"],
    "allowed_values",
    quote=T("1:7"),
    tool="create_new_case",
    arg="state",
    values=["new"],
)
rule(
    "v_product_account",
    "judgment",
    "remind",
    ["1:8", "9:4"],
    "verify",
    why="Needs the account of the product or installed product record, which no argument of the call carries.",
    tools=["create_new_case", "update_case"],
    statement=T("1:8") + " " + T("9:4"),
)

# assigning
for tool, arg in (("create_new_case", "assigned_to"), ("update_case", "assigned_to"), ("assign_case_to_user", "assigned_to_user_id")):
    short = tool.split("_")[0]
    rule(
        f"r_assignee_active_{short}",
        "hard",
        "block_once",
        ["2:5"],
        "reference_status",
        quote=T("2:5"),
        tool=tool,
        arg=arg,
        field="active",
        allowed=[True],
    )
    rule(
        f"r_assignee_role_{short}",
        "hard",
        "block_once",
        ["2:7"],
        "reference_status",
        quote="assigned_to must reference a user with role agent or manager",
        tool=tool,
        arg=arg,
        field="role",
        allowed=["agent", "manager"],
    )
for tool in ("create_new_case", "update_case"):
    rule(
        f"r_assignee_member_{tool.split('_')[0]}",
        "hard",
        "block_once",
        ["2:6", "2:7"],
        "membership",
        quote=T("2:6"),
        tool=tool,
        arg="assigned_to",
        group_arg="assignment_group_id",
    )
rule(
    "v_assignee_member_assign",
    "judgment",
    "remind",
    ["2:6", "2:7"],
    "verify",
    why="assign_case_to_user does not carry the assignment group; the group is a field of the case record.",
    tools=["assign_case_to_user"],
    statement=T("2:7"),
)

# lifecycle
EDGES = {
    "new": ["in_progress", "pending", "resolved", "canceled"],
    "in_progress": ["pending", "resolved", "canceled"],
    "pending": ["in_progress", "resolved", "canceled"],
    "resolved": ["closed", "new", "canceled"],
    "closed": [],
    "canceled": [],
}
rule(
    "r_case_transition",
    "hard",
    "deny",
    ["4:2", "4:3", "4:4", "4:5", "4:6", "3:7", "3:8", "4:10", "11:3"],
    "transition",
    quote=T("3:8"),
    tool="update_case",
    arg="state",
    id_arg="case_id",
    edges=EDGES,
)
rule(
    "r_closed_on",
    "hard",
    "remind",
    ["4:9", "11:6"],
    "required_args",
    quote=T("11:6"),
    tool="update_case",
    args=["closed_on"],
    when={"state": ["closed"]},
)
rule(
    "v_acting_user",
    "judgment",
    "remind",
    ["4:8", "10:1"],
    "verify",
    why="Needs the logged-in user and the case's owner, assignee and group; no argument carries the acting user.",
    tools=["update_case", "assign_case_to_user", "set_case_assignment_group", "search_cases", "link_case_knowledge"],
    statement=T("4:8") + " " + T("10:1"),
)

# installed products / products
for tool in ("create_new_case", "update_case"):
    short = tool.split("_")[0]
    rule(
        f"r_ip_in_use_{short}",
        "hard",
        "remind",
        ["6:2"],
        "reference_status",
        quote=T("6:2"),
        tool=tool,
        arg="installed_product_id",
        field="status",
        allowed=["in_use"],
    )
    rule(
        f"r_ip_account_{short}",
        "hard",
        "block_once",
        ["6:3", "9:4"],
        "membership",
        quote=T("6:3"),
        tool=tool,
        arg="installed_product_id",
        group_arg="account_id",
    )
    rule(
        f"r_product_active_{short}",
        "hard",
        "block_once",
        ["9:3"],
        "reference_status",
        quote=T("9:3"),
        tool=tool,
        arg="product_id",
        field="lifecycle_state",
        allowed=["active"],
    )
rule(
    "r_ip_not_retired_repair",
    "hard",
    "remind",
    ["6:4"],
    "reference_status",
    quote=T("6:4"),
    tool="create_new_case",
    arg="installed_product_id",
    field="status",
    allowed=["in_use", "in_stock"],
)
rule(
    "r_product_active_installed",
    "hard",
    "block_once",
    ["9:3"],
    "reference_status",
    quote=T("9:3"),
    tool="register_new_installed_product",
    arg="product_id",
    field="lifecycle_state",
    allowed=["active"],
)
rule(
    "v_ip_product_match",
    "judgment",
    "remind",
    ["6:5", "9:4"],
    "verify",
    why="Needs the product of the installed product record; the call carries only its id.",
    tools=["create_new_case", "update_case"],
    statement=T("6:5"),
)

# knowledge
rule(
    "r_kb_published",
    "hard",
    "block_once",
    ["7:2"],
    "reference_status",
    quote=T("7:2"),
    tool="link_case_knowledge",
    arg="knowledge_id",
    field="state",
    allowed=["published"],
)
rule(
    "r_kb_used_as",
    "hard",
    "deny",
    ["7:6"],
    "allowed_values",
    quote="usage = suggested, applied, resolution",
    tool="link_case_knowledge",
    arg="used_as",
    values=["suggested", "applied", "resolution"],
)
rule(
    "v_kb_visibility",
    "judgment",
    "remind",
    ["7:4"],
    "verify",
    why="Needs the role of the person who will see the article and the article's visibility, read from records.",
    tools=["retrieve_knowledge", "link_case_knowledge"],
    statement="Visibility rules apply: internal = agents only; external = customers can view.",
)
rule(
    "d_kb_link",
    "hard",
    "remind",
    [IK + "10"],
    "duty",
    quote=T(IK + "10"),
    trigger={"tool": "create_knowledge"},
    then={"tool": "link_case_knowledge"},
)
rule(
    "d_sla_align",
    "hard",
    "remind",
    [IK + "11"],
    "duty",
    quote=T(IK + "11"),
    trigger={"tool": "update_case", "when": {"state": ["in_progress"]}},
    then={"tool": "link_new_case_sla"},
)
rule(
    "d_sla_pause",
    "hard",
    "remind",
    ["service-levels-timelines:4"],
    "duty",
    quote="when case state is pending, pause applicable SLAs",
    trigger={"tool": "update_case", "when": {"state": ["pending"]}},
    then={"tool": "update_case_sla_details", "when": {"stage": ["paused"]}},
    unless=[{"condition": "the sla_definition of the case_sla has pause_on_pending = false"}],
)

# escalation
rule(
    "r_escalation_reason",
    "hard",
    "deny",
    ["8:7"],
    "required_args",
    quote=T("8:7"),
    tool="update_case",
    args=["escalation_reason"],
    when={"escalation": [True]},
)

# free-form text limits
LIMIT = r"^[\s\S]{30,120}$"
for rid, tool, arg, level in (
    ("r_len_case_desc_create", "create_new_case", "short_description", "deny"),
    ("r_len_case_desc_update", "update_case", "short_description", "deny"),
    ("r_len_kb_title_create", "create_knowledge", "title", "deny"),
    ("r_len_kb_title_update", "update_knowledge", "title", "deny"),
    ("r_len_kb_body", "create_knowledge", "body", "remind"),
):
    rule(rid, "hard", level, [IK + "19"], "format", quote=T(IK + "19"), tool=tool, arg=arg, pattern=LIMIT)

# enumerations
ENUM_VALUES = {}
for sid, pairs in ENUM_STMTS.items():
    vals = [v.strip() for v in T(sid).split(":", 1)[1].split(",")]
    for tool, arg in pairs:
        rule(
            f"r_enum_{tool}_{arg}",
            "hard",
            "deny",
            [sid, IK + "5"],
            "allowed_values",
            quote=T(sid),
            tool=tool,
            arg=arg,
            values=vals,
        )

# ---------------------------------------------------------------- procedures
procedures = [
    {
        "id": "1",
        "name": "Registering a Customer Case",
        "category": "Core Operations",
        "src": "§1",
        "applies_when": "helping them register cases",
        "inputs": [
            {"fact": "the reporting contact and its account", "source": "find_contacts / find_contact_by_portal_user"},
            {"fact": "issue description (short_description)", "source": "the request"},
            {"fact": "product or installed product involved", "source": "find_product / retrieve_installed_products"},
            {"fact": "contact channel (channel)", "source": "the request"},
            {"fact": "priority", "source": "the request; default moderate"},
            {"fact": "entitlement for the product", "source": "find_entitlements"},
        ],
        "decisions": [
            {
                "id": "priority_given",
                "rule": "Priority (if not provided → default = moderate)",
                "then": "use the priority given",
                "else": "priority = moderate",
            },
            {
                "id": "asked_to_investigate",
                "rule": "When a new case is created and is asked to be investigated",
                "then": "perform a knowledge base search",
                "else": "no search is required",
            },
        ],
        "steps": [
            {"id": P("1:1")},
            {"id": P("1:3")},
            {"id": P("1:4")},
            {"id": P("1:5")},
            {"id": P("1:6")},
            {"id": P("1:8")},
            {"id": P(IK + "8")},
            {"id": P("1:7"), "action": "create_new_case"},
            {"id": P(IK + "7"), "action": "retrieve_knowledge", "condition": "is asked to be investigated"},
        ],
        "links": [],
    },
    {
        "id": "5",
        "name": "Entitlement Validation",
        "category": "Core Operations",
        "src": "§5",
        "applies_when": "Before applying entitlement",
        "inputs": [
            {"fact": "the entitlement (active, product_id, max_cases_per_month)", "source": "find_entitlements"},
            {"fact": "the contract and its validity", "source": "find_contracts"},
            {"fact": "the case product", "source": "the case record (search_cases)"},
        ],
        "decisions": [
            {
                "id": "entitlement_valid",
                "rule": "Check it is active and within contract validity.",
                "then": "apply the entitlement",
                "else": "inform the user",
            },
            {
                "id": "account_wide",
                "rule": "unless entitlement is account-wide",
                "then": "no product match is needed",
                "else": "the entitlement product must match the case product",
            },
        ],
        "steps": [
            {"id": P(IK + "8")},
            {"id": P("5:2")},
            {"id": P("5:3")},
            {"id": P("5:4")},
            {"id": P("5:5"), "action": "reply", "condition": "If entitlement is invalid"},
        ],
        "links": [],
    },
    {
        "id": "7",
        "name": "Linking Knowledge Articles",
        "category": "Core Operations",
        "src": "§7",
        "applies_when": "When linking knowledge",
        "inputs": [
            {"fact": "the article state and visibility", "source": "retrieve_knowledge"},
            {"fact": "how the article was found and whether it resolves the case", "source": "the case work"},
        ],
        "decisions": [
            {
                "id": "found_by_automated_search",
                "rule": "When the knowledge is found through automated search",
                "then": "used_as = suggested",
                "else": "see useful_to_resolve",
            },
            {
                "id": "useful_to_resolve",
                "rule": "If the knowledge is found to be useful to resolve the case or is being created after case "
                "resolution",
                "then": "used_as = resolution",
                "else": "used_as = applied",
            },
        ],
        "steps": [
            {"id": P("7:2")},
            {"id": P(IK + "13"), "action": "link_case_knowledge", "condition": "found through automated search"},
            {
                "id": P(IK + "14"),
                "action": "link_case_knowledge",
                "condition": "found to be useful to resolve the case or is being created after case resolution",
            },
            {"id": P(IK + "15"), "action": "link_case_knowledge", "condition": "In other cases"},
            {"id": P("7:6"), "action": "link_case_knowledge"},
        ],
        "notes": [T("7:7")],
        "links": [],
    },
    {
        "id": "8",
        "name": "Escalations",
        "category": "Core Operations",
        "src": "§8",
        "applies_when": "Escalations may be raised when: SLA breach risk exists, or Customer explicitly requests "
        "escalation, or High business risk/impact.",
        "inputs": [
            {"fact": "the reason for the escalation", "source": "the request or the case record"},
        ],
        "decisions": [],
        "steps": [
            {"id": P("8:6"), "action": "update_case"},
            {"id": P("8:7"), "action": "update_case"},
            {"id": P("8:8")},
        ],
        "notes": [T("8:9") + " " + T("8:10")],
        "links": [],
    },
    {
        "id": "kb-close",
        "name": "Knowledge Related Policies",
        "category": "Knowledge",
        "src": "Knowledge Related Policies",
        "applies_when": "If no relevant knowledge is found and case is being closed",
        "inputs": [{"fact": "whether relevant knowledge exists", "source": "retrieve_knowledge"}],
        "decisions": [
            {
                "id": "relevant_knowledge_found",
                "rule": "If no relevant knowledge is found and case is being closed",
                "then": "link the knowledge that was found",
                "else": "create a new knowledge article and link it",
            }
        ],
        "steps": [
            {"id": P(IK + "9"), "action": "create_knowledge", "condition": "no relevant knowledge is found"},
            {"id": P(IK + "10"), "action": "link_case_knowledge"},
        ],
        "links": [],
    },
]

# ---------------------------------------------------------------- obligations


def ob(oid, proc, kind, tools, match, values, section, quote, when=None):
    o = {
        "id": oid,
        "origin": "package",
        "scope": {"procedure": proc} if proc else {},
        "effect": {"kind": kind},
        "values": values,
        "check": "code",
        "level": "observe",
        "source": {"section": section, "quote": quote},
    }
    if tools:
        o["effect"]["tools"] = tools
    if match:
        o["effect"]["match"] = match
    if when:
        o["scope"]["when"] = when
    return o


obligations = [
    ob(
        "ob_1_priority",
        "1",
        "write",
        ["create_new_case"],
        {"priority": {"pattern": "{priority}"}},
        {"priority": {"from": "literal", "value": "moderate"}},
        "1",
        T("1:6"),
        when={"priority_given": "no"},
    ),
    ob(
        "ob_1_state",
        "1",
        "write",
        ["create_new_case"],
        {"state": {"pattern": "{state}"}},
        {"state": {"from": "literal", "value": "new"}},
        "1",
        T("1:7"),
    ),
    ob("ob_5_inform", "5", "reply", None, None, {}, "5", T("5:5"), when={"entitlement_valid": "no"}),
    ob(
        "ob_7_suggested",
        "7",
        "write",
        ["link_case_knowledge"],
        {"used_as": {"pattern": "{used_as}"}},
        {"used_as": {"from": "literal", "value": "suggested"}},
        "interactions-knowledge",
        T(IK + "13"),
        when={"found_by_automated_search": "yes"},
    ),
    ob(
        "ob_7_resolution",
        "7",
        "write",
        ["link_case_knowledge"],
        {"used_as": {"pattern": "{used_as}"}},
        {"used_as": {"from": "literal", "value": "resolution"}},
        "interactions-knowledge",
        T(IK + "14"),
        when={"useful_to_resolve": "yes"},
    ),
    ob(
        "ob_7_applied",
        "7",
        "write",
        ["link_case_knowledge"],
        {"used_as": {"pattern": "{used_as}"}},
        {"used_as": {"from": "literal", "value": "applied"}},
        "interactions-knowledge",
        T(IK + "15"),
        when={"found_by_automated_search": "no", "useful_to_resolve": "no"},
    ),
    ob(
        "ob_8_escalation",
        "8",
        "write",
        ["update_case"],
        {"escalation": {"pattern": "{escalation}"}},
        {"escalation": {"from": "literal", "value": True}},
        "8",
        T("8:6"),
    ),
    ob(
        "ob_kb_create",
        "kb-close",
        "write",
        ["create_knowledge"],
        None,
        {},
        "interactions-knowledge",
        T(IK + "9"),
        when={"relevant_knowledge_found": "no"},
    ),
    ob(
        "ob_kb_link",
        "kb-close",
        "write",
        ["link_case_knowledge"],
        {"used_as": {"pattern": "{used_as}"}},
        {"used_as": {"from": "literal", "value": "resolution"}},
        "interactions-knowledge",
        T(IK + "10"),
        when={"relevant_knowledge_found": "no"},
    ),
]

# ---------------------------------------------------------------- global
global_ = {
    "global_rules": [
        {"id": "G-context", "src": "Preamble", "rule": T("preamble:3")},
        {"id": "G-assume", "src": "Preamble", "rule": T("preamble:4")},
        {"id": "G-violation", "src": "General Instructions", "rule": T("general-instructions:1")},
        {"id": "G-sequential", "src": "General Instructions", "rule": T("general-instructions:2")},
        {"id": "G-system", "src": "General Instructions", "rule": T("general-instructions:3")},
        {
            "id": "G-no-ask",
            "src": "General Instructions",
            "rule": T("general-instructions:4") + " " + T("general-instructions:5"),
        },
        {"id": "G-security", "src": "§10", "rule": T("10:1") + " " + T("10:2")},
        {"id": "G-validate", "src": "§11", "rule": "Always validate existence and integrity of: " + T("11:2")},
        {"id": "G-lifecycle", "src": "§3", "rule": T("3:7") + " " + T("3:8")},
        {
            "id": "G-assign",
            "src": "§2",
            "rule": T("2:7"),
            "attach_when": "assign",
        },
        {"id": "G-enum", "src": "Predefined Lists (Enumerations)", "rule": T(IK + "5").lstrip("> ").strip()},
        {"id": "G-length", "src": "Free form text policies", "rule": T(IK + "19")},
        {"id": "G-sla-pause", "src": "Service Levels & Timelines", "rule": T("service-levels-timelines:4")},
        {"id": "G-sla-align", "src": "Knowledge Related Policies", "rule": T(IK + "11")},
        {"id": "G-kb-use", "src": "Knowledge Related Policies", "rule": T(IK + "16")},
    ],
    "templates": {
        "Case Short Description": {
            "number": "Case Short Description",
            "name": "Case Short Description",
            "slots": ["Product name"],
            "text": '"Product: " + Product name + ", Issue: is not working as expected."',
        },
        "KB title": {
            "number": "KB title",
            "name": "KB title",
            "slots": [],
            "text": "Issue Resolution related to , step-by-step guide",
        },
        "KB content/body": {
            "number": "KB content/body",
            "name": "KB content/body",
            "slots": [],
            "text": "This kind of issues are tackled by Assignment Group: , Assigned to: . Steps to resolve the issue: "
            ", Suggested Priority: .",
        },
        "Escalation reason": {
            "number": "Escalation reason",
            "name": "Escalation reason",
            "slots": [],
            "text": "The case could not be completed on time/exceeds the time limit or has priority beyond the defined "
            "list of priorities.",
        },
    },
    "definitions": [
        {"term": "max_cases_per_month = 0", "meaning": "means unlimited", "source": {"statement": P("5:4")}},
        {"term": "internal", "meaning": "internal = agents only", "source": {"statement": P("7:4")}},
        {
            "term": "external",
            "meaning": "external = customers can view",
            "source": {"statement": P("7:5")},
        },
        {
            "term": "escalation",
            "meaning": "There is no separate escalation record. Escalation is tracked within the case.",
            "source": {"statement": P("8:10")},
        },
    ],
}

links = [
    {"type": "refers_to", "src": P("10:2"), "dst": P("10:1"), "quote": "outside these permissions"},
    {"type": "refers_to", "src": P("11:3"), "dst": "policy:4", "quote": "State transitions follow lifecycle rules."},
    {"type": "refers_to", "src": P(IK + "5"), "dst": "policy:predefined-lists-enumerations", "quote": "reject any value outside the list"},
    {"type": "depends_on", "src": P("manager:2"), "dst": "policy:agent", "quote": "Has agent privileges plus:"},
    {"type": "exception_of", "src": P("5:3"), "dst": P("5:3"), "quote": "unless entitlement is account-wide"},
]
links = links[:4]  # the account-wide exception is inside one statement: kept as a decision, not a link

coverage = []

Q = []


def q(sids, question, rule_ids=None, open_values=None):
    item = {"statement_ids": [P(s) for s in sids], "question": question, "default_level": "remind"}
    if rule_ids:
        item["rule_ids"] = rule_ids
    if open_values:
        item["open_values"] = open_values
    Q.append(item)


q(
    ["agent:4", "agent:5", "agent:6", "agent:7", IK + "9", IK + "11", "service-levels-timelines:4"],
    "The agent grant list does not include creating knowledge, linking or updating case SLAs, or sending "
    "notifications, but the Knowledge Related Policies and SLA pause rule ask for knowledge creation and SLA "
    "alignment. May a user with role agent (or manager) create knowledge articles and create or update case_sla "
    "records, and send notifications?",
    rule_ids=["r_agent_grant", "r_manager_grant", "d_kb_link", "d_sla_align", "d_sla_pause"],
)
q(
    ["manager:3", "manager:4", "agent:7", "8:6"],
    "Only the manager list says 'Can reassign cases across groups and users' and 'Can escalate cases and override "
    "case prioritization'. May a user with role agent set escalation = true, change priority, or reassign a case to "
    "another group?",
    rule_ids=["r_agent_grant", "r_manager_grant"],
)
q(
    ["customer-portal-user:3", "customer-portal-user:4", "customer-portal-user:7", "customer-portal-user:9"],
    "For a customer (portal user): is every write outside 'update their own profile', 'create new cases' and "
    "'initiate interactions' forbidden; and in 'users, groups, SLAs, contracts of other customers', does 'of other "
    "customers' qualify only contracts or every item?",
    rule_ids=["r_customer_grant", "r_customer_internal"],
)
q(
    ["4:6", "3:9"],
    "Section 4 lists 'canceled' with no source state. From which states may a case be moved to canceled (the "
    "package allows new, in_progress, pending and resolved)?",
    rule_ids=["r_case_transition"],
)
q(
    ["6:2", "6:4"],
    "Section 6 says installed products must be 'active / in_use', but also only forbids 'retired / repair' for new "
    "cases. May an installed product with status in_stock be attached to a case?",
    rule_ids=["r_ip_in_use_create", "r_ip_in_use_update", "r_ip_not_retired_repair"],
)
q(
    ["4:9", "11:5", "11:6"],
    "No tool takes sys_updated_on, and closed_on is an optional argument of update_case. Does the system set these "
    "timestamps, or must the assistant pass closed_on when it closes a case?",
    rule_ids=["r_closed_on"],
)
q(
    ["8:8"],
    "'Ensure justification is logged in case notes': no tool writes case notes or work notes. Where must the "
    "escalation justification be recorded?",
)
q(
    [IK + "18", IK + "23", "case-management:4"],
    "The free-form text rules treat escalation reason as text of 30–120 characters, but customer_case."
    "escalation_reason accepts only urgency, vip, impact, breach_risk, customer_request. Which applies?",
)
q(
    [IK + "19", IK + "22"],
    "The 30–120 character limit applies to the knowledge body, but the KB content/body pattern alone is about 110 "
    "characters before it is filled in. Does the limit apply to the body?",
    rule_ids=["r_len_kb_body"],
)
q(
    [IK + "20", IK + "21", IK + "22"],
    "The short description, KB title and KB body patterns have empty places (for example 'related to ,'). What "
    "values go there, and must the agent use these patterns exactly or only as examples ('It can be something "
    "like')?",
)
q(
    [IK + "13", IK + "14", IK + "15"],
    "An article found through automated search that is also useful to resolve the case: link it as suggested or as "
    "resolution?",
)
q(
    ["5:1", "5:5", IK + "8"],
    "Which action 'applies' an entitlement (no tool takes an entitlement id for a case), and when the entitlement "
    "is invalid, must the assistant stop registering the case or register it and inform the user?",
)
q(
    ["1:7"],
    "'Default state = new': may a case be created in another state when the request gives one?",
    rule_ids=["r_case_state_new"],
)
q(
    ["10:1", "4:8", "administrator:1", "manager:3"],
    "Does the rule 'Users may only view or update cases they own, are assigned to, or are in the assigned group' "
    "also limit administrators (full access) and managers (reassign across groups)?",
    rule_ids=["v_acting_user"],
)

draft = {
    "modality": modality,
    "rules": rules,
    "procedures": procedures,
    "obligations": obligations,
    "global": global_,
    "links": links,
    "coverage": coverage,
    "policy_questions": Q,
}
json.dump(draft, open(os.path.join(HERE, "draft.json"), "w"), indent=1, ensure_ascii=False)
print(len(rules), "rules", len(procedures), "procedures", len(obligations), "obligations", len(Q), "questions")
