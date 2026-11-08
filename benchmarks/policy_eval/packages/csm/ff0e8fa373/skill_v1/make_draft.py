"""Writes draft.json for the CSM policy from set.json (statement texts) and tools.json (tool names)."""
import json
import sys
from pathlib import Path

HERE = Path(sys.argv[1])
SET = json.loads((HERE / "set.json").read_text())
TOOLS = {t["name"]: t for t in json.loads((HERE / "tools.json").read_text())}
ST = {s["id"]: s["text"] for d in SET["documents"] for sec in d["sections"] for s in sec["statements"]}


def S(sid):
    return ST["policy:" + sid]


def P(sid):
    return "policy:" + sid


WRITE_TOOLS = [
    "add_new_user", "update_user_details", "add_new_user_group", "update_user_group", "add_new_group_member",
    "remove_group_membership", "create_new_account", "update_account_details", "create_contact", "update_contact",
    "add_location", "update_location", "add_new_product", "update_product", "delete_products",
    "register_new_installed_product", "update_installed_product_details", "enlist_new_contract", "update_contract",
    "add_new_entitlement", "update_entitlement", "add_new_sla_definition", "update_sla_definition", "create_new_case",
    "update_case", "assign_case_to_user", "set_case_assignment_group", "link_new_case_sla", "update_case_sla_details",
    "delete_case_slas", "register_new_interaction", "update_interaction", "create_knowledge", "update_knowledge",
    "link_case_knowledge", "updated_linked_case_knowledge", "delete_case_knowledge_linkages", "send_notification",
    "update_notification", "delete_notifications",
]
for t in WRITE_TOOLS:
    assert t in TOOLS, t

AGENT_GRANTED = {"create_new_case", "update_case", "register_new_interaction", "update_interaction",
                 "link_case_knowledge", "updated_linked_case_knowledge", "assign_case_to_user",
                 "set_case_assignment_group"}
MANAGER_GRANTED = AGENT_GRANTED | {"create_knowledge", "update_knowledge"}
CUSTOMER_GRANTED = {"update_user_details", "create_new_case", "register_new_interaction"}
USER_GROUP_TOOLS = ["add_new_user", "update_user_details", "add_new_user_group", "update_user_group",
                    "add_new_group_member", "remove_group_membership"]
INTERNAL_READS = ["list_users", "list_user_groups", "list_group_members", "find_user_group", "check_user_membership",
                  "find_sla_definitions", "find_case_slas", "total_sum_of_target_mins_per_priority",
                  "average_target_mins_per_priority", "find_stage_wise_breached_case_sla_counts"]
ACCOUNT_READS = ["get_accounts", "find_contacts", "search_cases", "retrieve_installed_products", "find_contracts",
                 "find_entitlements", "find_interactions"]

modality = {}


def mark(m, *ids):
    for i in ids:
        assert P(i) in ST, i
        modality[P(i)] = m


mark("should", "preamble:4", "General:1")
mark("must_not", "preamble:5", "General:2", "General:4", "General:5")
mark("must", "General:3")
mark("must", "Agent:2")
mark("may", "Agent:3", "Agent:4", "Agent:5", "Agent:6")
mark("must_not", "Agent:7")
mark("may", "Manager:2", "Manager:3", "Manager:5", "Manager:6")
mark("may", "Customer:2", "Customer:3", "Customer:4", "Customer:5", "Customer:6")
mark("must", "Customer:7")
mark("must_not", "Customer:8")
mark("may", "Administrator:1", "Administrator:2")
mark("must", "Registering:1", "Registering:2", "Registering:3")
mark("may", "Assigning:1")
mark("must", "Assigning:2", "Assigning:3")
mark("may", "Working:1", "Working:2", "Working:3", "Working:4", "Working:7")
mark("must_not", "Working:5")
mark("must", "Working:6")
mark("must", "Case:1", "Case:2")
mark("must_not", "Case:3")
mark("must", "Entitlement:1", "Entitlement:2", "Entitlement:3")
mark("must", "Installed:1", "Installed:2", "Installed:4")
mark("must_not", "Installed:3")
mark("must", "Linking:1", "Linking:2")
mark("may", "Escalations:1")
mark("must", "Escalations:2", "Escalations:3", "Escalations:4")
mark("must", "Product:1", "Product:2")
mark("must", "Security:1")
mark("must_not", "Security:2")
mark("must", "Validation:1", "Validation:2", "Validation:3", "Validation:4")
mark("must", "Service:3")
for i in range(2, 9):
    mark("must", f"Predefined:{i}")
mark("should", *[f"Knowledge:{i}" for i in range(1, 10)])
mark("must", "Free:1")

rules = []


def rule(rid, cls, level, sids, body, quote=None, why=None):
    r = {"id": rid, "class": cls, "level": level, "statement_ids": [P(s) for s in sids], "rule": body}
    if quote is not None:
        r["quote"] = quote
    if why:
        r["why"] = why
    rules.append(r)


def guidance(rid, sid, tools=None):
    body = {"type": "guidance", "text": S(sid)}
    if tools:
        body["tools"] = tools
    rule(rid, "guidance", "observe", [sid], body)


# General statements
rule("r_grounded", "hard", "observe", ["preamble:5"], {"type": "grounded_values"})
rule("r_ids", "hard", "observe", ["preamble:5", "Validation:1"], {"type": "id_provenance"})
guidance("g_confirmed_context", "preamble:4")
guidance("g_no_assumed_data", "preamble:5")
guidance("g_admin_default", "General:1")
guidance("g_violating_request", "General:2")
guidance("g_one_operation", "General:3")
guidance("g_no_outside_knowledge", "General:4")
guidance("g_no_questions", "General:5")
guidance("g_validate_existence", "Validation:1")
guidance("g_no_disclosure", "Security:2")
guidance("g_use_knowledge", "Knowledge:9")

# Roles (grant lists)
agent_q = "Read-only access to all records"
rule("r_role_agent", "hard", "remind", ["Agent:2", "Agent:3", "Agent:4", "Agent:6"],
     {"type": "role_permission", "tools": [t for t in WRITE_TOOLS if t not in AGENT_GRANTED], "roles": ["agent"],
      "effect": "forbid"}, quote=S("Agent:2"))
rule("r_agent_user_data", "hard", "remind", ["Agent:7"],
     {"type": "role_permission", "tools": USER_GROUP_TOOLS, "roles": ["agent"], "effect": "forbid"},
     quote=S("Agent:7"))
rule("r_role_manager", "hard", "remind", ["Manager:2", "Manager:3", "Manager:6"],
     {"type": "role_permission", "tools": [t for t in WRITE_TOOLS if t not in MANAGER_GRANTED], "roles": ["manager"],
      "effect": "forbid"}, quote=S("Manager:2"))
rule("r_role_customer", "hard", "remind", ["Customer:2", "Customer:3", "Customer:6"],
     {"type": "role_permission", "tools": [t for t in WRITE_TOOLS if t not in CUSTOMER_GRANTED],
      "roles": ["customer"], "effect": "forbid"}, quote=S("Customer:3"))
rule("r_customer_internal", "hard", "remind", ["Customer:8"],
     {"type": "role_permission", "tools": INTERNAL_READS, "roles": ["customer"], "effect": "forbid"},
     quote=S("Customer:8"))
rule("r_customer_own_account", "judgment", "remind", ["Customer:7"],
     {"type": "verify", "tools": ACCOUNT_READS, "statement": S("Customer:7")},
     why="Needs the account of the logged-in customer and of each record read; no argument carries the caller's account.")

# Assignment
for tool, arg in (("assign_case_to_user", "assigned_to_user_id"), ("update_case", "assigned_to"),
                  ("create_new_case", "assigned_to")):
    rule(f"r_assignee_active_{tool}", "hard", "block_once", ["Assigning:2"],
         {"type": "reference_status", "tool": tool, "arg": arg, "field": "active", "allowed": ["true"]},
         quote="Agents must: Be active")
    rule(f"r_assignee_role_{tool}", "hard", "block_once", ["Assigning:3"],
         {"type": "reference_status", "tool": tool, "arg": arg, "field": "role", "allowed": ["agent", "manager"]},
         quote="assigned_to must reference a user with role agent or manager")
for tool in ("update_case", "create_new_case"):
    rule(f"r_assignee_member_{tool}", "hard", "block_once", ["Assigning:2", "Assigning:3"],
         {"type": "membership", "tool": tool, "arg": "assigned_to", "group_arg": "assignment_group_id"},
         quote="(if used) member of assignment_group_id")
rule("r_assignee_member_assign", "judgment", "remind", ["Assigning:2", "Assigning:3"],
     {"type": "verify", "tools": ["assign_case_to_user"],
      "statement": "Agents must: Be active, and Be members of the assigned group."},
     why="assign_case_to_user has no group argument, so membership cannot compare two arguments; the case's group is in the case record.")

# Case lifecycle
rule("r_case_transition", "hard", "remind", ["Case:1", "Validation:2", "Working:2", "Working:6"],
     {"type": "transition", "tool": "update_case", "arg": "state", "id_arg": "case_id",
      "edges": {"new": ["in_progress", "pending", "resolved"], "in_progress": ["pending", "resolved"],
                "pending": ["in_progress", "resolved"], "resolved": ["closed", "new"]}},
     quote="Valid state transitions: new → in_progress / pending / resolved in_progress → pending / resolved pending → in_progress / resolved resolved → closed / new")
rule("r_no_direct_close", "hard", "block_once", ["Working:5", "Working:6", "Case:3"],
     {"type": "record_condition", "tools": ["update_case"], "field": "state", "op": "in",
      "value": ["new", "in_progress", "pending"], "effect": "forbid", "when": {"state": ["closed"]}},
     quote="Cases cannot be closed directly.")
for tool in ("update_case", "create_new_case"):
    rule(f"r_closed_on_{tool}", "hard", "deny", ["Case:2", "Validation:4"],
         {"type": "required_args", "tool": tool, "args": ["closed_on"], "when": {"state": ["closed"]}},
         quote="Capture timestamps (e.g., closed_on for case closure).")
rule("r_case_relationship", "judgment", "remind", ["Security:1", "Case:1"],
     {"type": "verify", "tools": ["update_case", "assign_case_to_user", "set_case_assignment_group", "search_cases"],
      "statement": S("Security:1")},
     why="Needs the acting user and the case's owner, assignee and group; the call carries only the case id.")

# Installed products and products on a case
for tool in ("create_new_case", "update_case"):
    rule(f"r_ip_in_use_{tool}", "hard", "block_once", ["Installed:1", "Installed:3"],
         {"type": "reference_status", "tool": tool, "arg": "installed_product_id", "field": "status",
          "allowed": ["in_use"]}, quote="Installed products must: Be active / in_use.")
    rule(f"r_product_active_{tool}", "hard", "block_once", ["Product:1"],
         {"type": "reference_status", "tool": tool, "arg": "product_id", "field": "lifecycle_state",
          "allowed": ["active"]}, quote="In lifecycle_state = active.")
rule("r_ip_account", "judgment", "remind", ["Registering:3", "Installed:2", "Product:2"],
     {"type": "verify", "tools": ["create_new_case", "update_case"], "statement": S("Registering:3")},
     why="Compares the installed product's account with the case account; no typed rule compares a field of one record with an argument.")
rule("r_ip_product", "judgment", "remind", ["Installed:4", "Product:2"],
     {"type": "verify", "tools": ["create_new_case", "update_case"], "statement": S("Installed:4")},
     why="Compares the installed product's product with the case product; no typed rule compares a field of one record with an argument.")

# Knowledge linking
for tool in ("link_case_knowledge", "updated_linked_case_knowledge"):
    rule(f"r_kb_published_{tool}", "hard", "block_once", ["Linking:1"],
         {"type": "reference_status", "tool": tool, "arg": "knowledge_id", "field": "state",
          "allowed": ["published"]}, quote="Articles must be in state = published.")
rule("r_kb_used_as", "hard", "deny", ["Linking:2"],
     {"type": "allowed_values", "tool": "link_case_knowledge", "arg": "used_as",
      "values": ["suggested", "applied", "resolution"]}, quote="usage = suggested, applied, resolution")
rule("r_kb_visibility", "judgment", "remind", ["Linking:2"],
     {"type": "verify", "tools": ["retrieve_knowledge"],
      "statement": "Visibility rules apply: internal = agents only external = customers can view"},
     why="Depends on the role of the user who will see the article; allowed_values has no condition on the role.")

# Escalation
for tool in ("update_case", "create_new_case"):
    rule(f"r_esc_reason_{tool}", "hard", "deny", ["Escalations:3"],
         {"type": "required_args", "tool": tool, "args": ["escalation_reason"], "when": {"escalation": ["true"]}},
         quote="Capture escalation_reason.")

# SLA duties
rule("r_duty_sla_pause", "hard", "remind", ["Service:3"],
     {"type": "duty", "trigger": {"tool": "update_case", "when": {"state": ["pending"]}},
      "then": {"tool": "update_case_sla_details", "when": {"stage": ["paused"]}},
      "unless": [{"condition": "Obey sla_definition.pause_on_pending"}]},
     quote="when case state is pending, pause applicable SLAs.")
rule("r_duty_sla_align", "hard", "remind", ["Knowledge:5"],
     {"type": "duty", "trigger": {"tool": "update_case", "when": {"state": ["in_progress"]}},
      "then": {"tool": "link_new_case_sla"}}, quote=S("Knowledge:5"))
rule("r_duty_kb_link", "hard", "remind", ["Knowledge:4"],
     {"type": "duty", "trigger": {"tool": "create_knowledge"}, "then": {"tool": "link_case_knowledge"}},
     quote=S("Knowledge:4"))
rule("r_duty_kb_search", "hard", "remind", ["Knowledge:1"],
     {"type": "duty", "trigger": {"tool": "create_new_case"}, "then": {"tool": "retrieve_knowledge"},
      "unless": [{"condition": "the case is not asked to be investigated"}]},
     quote="a knowledge base search should be performed")

# Enumerations (create tools)
ENUMS = [
    ("Predefined:2", "user.role", "add_new_user", "role", ["admin", "agent", "manager", "customer"]),
    ("Predefined:2", "user_group.type", "add_new_user_group", "type", ["support", "backoffice", "field", "vendor"]),
    ("Predefined:3", "location.city", "add_location", "city", ["new_york", "london", "mumbai", "tokyo", "sydney"]),
    ("Predefined:3", "location.country", "add_location", "country", ["usa", "uk", "india", "japan", "australia"]),
    ("Predefined:4", "account.account_type", "create_new_account", "account_type", ["customer", "partner", "internal"]),
    ("Predefined:5", "product.category", "add_new_product", "category", ["software", "hardware", "service"]),
    ("Predefined:5", "product.lifecycle_state", "add_new_product", "lifecycle_state", ["active", "retired"]),
    ("Predefined:5", "installed_product.status", "register_new_installed_product", "status",
     ["in_use", "in_stock", "repair", "retired"]),
    ("Predefined:6", "contract.contract_type", "enlist_new_contract", "contract_type",
     ["support", "warranty", "subscription"]),
    ("Predefined:6", "contract.status", "enlist_new_contract", "status", ["active", "suspended", "expired"]),
    ("Predefined:6", "entitlement.support_level", "add_new_entitlement", "support_level",
     ["standard", "premium", "enterprise"]),
    ("Predefined:6", "entitlement.coverage_hours", "add_new_entitlement", "coverage_hours", ["h8x5", "h12x6", "h24x7"]),
    ("Predefined:6", "sla_definition.metric", "add_new_sla_definition", "metric", ["response", "resolution"]),
    ("Predefined:6", "sla_definition.applies_to_priority", "add_new_sla_definition", "applies_to_priority",
     ["critical", "high", "moderate", "low"]),
    ("Predefined:7", "customer_case.channel", "create_new_case", "channel",
     ["web", "email", "phone", "chat", "social", "alert", "community"]),
    ("Predefined:7", "customer_case.priority", "create_new_case", "priority", ["critical", "high", "moderate", "low"]),
    ("Predefined:7", "customer_case.state", "create_new_case", "state",
     ["new", "in_progress", "pending", "resolved", "closed", "canceled"]),
    ("Predefined:7", "customer_case.escalation_reason", "create_new_case", "escalation_reason",
     ["urgency", "vip", "impact", "breach_risk", "customer_request"]),
    ("Predefined:8", "interaction.channel", "register_new_interaction", "channel",
     ["web", "email", "phone", "chat", "social", "alert", "community"]),
    ("Predefined:8", "knowledge.state", "create_knowledge", "state", ["draft", "published", "retired"]),
    ("Predefined:8", "knowledge.visibility", "create_knowledge", "visibility", ["internal", "external"]),
    ("Predefined:8", "case_knowledge.used_as", "link_case_knowledge", "used_as", ["suggested", "applied", "resolution"]),
]
for sid, field, tool, arg, values in ENUMS:
    text = S(sid)
    quote = f"{field}: {', '.join(values)}"
    assert quote in text, (quote, text)
    rule(f"r_enum_{field.replace('.', '_')}", "hard", "deny", [sid],
         {"type": "allowed_values", "tool": tool, "arg": arg, "values": values}, quote=quote)

# Free text length
rule("r_len_short_description", "hard", "deny", ["Free:1"],
     {"type": "format", "tool": "create_new_case", "arg": "short_description", "pattern": r"^[\s\S]{30,120}$"},
     quote="Character limits: 30–120 chars")
rule("r_len_kb_title", "hard", "deny", ["Free:1"],
     {"type": "format", "tool": "create_knowledge", "arg": "title", "pattern": r"^[\s\S]{30,120}$"},
     quote="Character limits: 30–120 chars")
rule("r_len_kb_body", "hard", "remind", ["Free:1"],
     {"type": "format", "tool": "create_knowledge", "arg": "body", "pattern": r"^[\s\S]{30,120}$"},
     quote="Character limits: 30–120 chars")

# Procedures
procedures = [
    {
        "id": "Registering", "name": "Registering a Customer Case", "category": "Core Operations",
        "src": "Registering a Customer Case", "applies_when": "helping them register cases",
        "inputs": [
            {"fact": "the reporting contact and its account", "source": "find_contact_by_portal_user, find_contacts, get_accounts"},
            {"fact": "the product or installed product and its account", "source": "find_product, retrieve_installed_products"},
            {"fact": "the entitlement for the product", "source": "find_entitlements"},
        ],
        "decisions": [
            {"id": "priority_given", "rule": "Priority (if not provided → default = moderate)",
             "then": "use the priority provided", "else": "priority = moderate"},
            {"id": "state_given", "rule": "Default state = new", "then": "use the state provided", "else": "state = new"},
        ],
        "steps": [
            {"id": P("Registering:1")},
            {"id": P("Registering:2"), "action": "create_new_case"},
            {"id": P("Registering:3")},
            {"id": P("Knowledge:2")},
            {"id": P("Knowledge:1"), "action": "retrieve_knowledge", "required": False,
             "condition": "When a new case is created and is asked to be investigated"},
        ],
        "must_not": [],
        "links": [],
    },
    {
        "id": "Entitlement", "name": "Entitlement Validation", "category": "Core Operations",
        "src": "Entitlement Validation", "applies_when": "Before applying entitlement",
        "inputs": [{"fact": "the entitlement and its contract", "source": "find_entitlements, find_contracts"}],
        "decisions": [
            {"id": "entitlement_valid", "rule": "Check it is active and within contract validity",
             "then": "apply the entitlement", "else": "If entitlement is invalid → inform the user."},
        ],
        "steps": [
            {"id": P("Entitlement:1")},
            {"id": P("Entitlement:2")},
            {"id": P("Entitlement:3"), "action": "reply", "condition": "If entitlement is invalid"},
        ],
        "must_not": [],
        "links": [],
    },
    {
        "id": "Escalations", "name": "Escalations", "category": "Core Operations", "src": "Escalations",
        "applies_when": S("Escalations:1"),
        "inputs": [{"fact": "the case", "source": "search_cases"}],
        "decisions": [],
        "steps": [
            {"id": P("Escalations:2"), "action": "update_case"},
            {"id": P("Escalations:3"), "action": "update_case"},
            {"id": P("Escalations:4")},
        ],
        "must_not": [],
        "notes": [S("Escalations:5"), S("Escalations:6")],
        "links": [],
    },
    {
        "id": "Knowledge", "name": "Knowledge Related Policies", "category": "Knowledge",
        "src": "Knowledge Related Policies", "applies_when": "When a new case is created and is asked to be investigated",
        "inputs": [{"fact": "knowledge articles for the case", "source": "retrieve_knowledge"}],
        "decisions": [
            {"id": "knowledge_found", "rule": "If no relevant knowledge is found and case is being closed",
             "then": "a new knowledge article should be created", "else": "use the knowledge found"},
            {"id": "found_by_automated_search", "rule": "When the knowledge is found through automated search",
             "then": "link as suggested", "else": "see useful_to_resolve"},
            {"id": "useful_to_resolve",
             "rule": "If the knowledge is found to be useful to resolve the case or is being created after case resolution",
             "then": "link as resolution", "else": "link as applied"},
        ],
        "steps": [
            {"id": P("Knowledge:1"), "action": "retrieve_knowledge",
             "condition": "When a new case is created and is asked to be investigated"},
            {"id": P("Knowledge:3"), "action": "create_knowledge",
             "condition": "If no relevant knowledge is found and case is being closed"},
            {"id": P("Knowledge:4"), "action": "link_case_knowledge", "condition": "If a knowledge article is created"},
            {"id": P("Knowledge:5"), "action": "link_new_case_sla",
             "condition": "When new case moves to work in progress"},
            {"id": P("Knowledge:6"), "action": "link_case_knowledge"},
            {"id": P("Knowledge:7"), "action": "link_case_knowledge"},
            {"id": P("Knowledge:8"), "action": "link_case_knowledge"},
            {"id": P("Knowledge:9")},
        ],
        "must_not": [],
        "links": [],
    },
]


def ob(oid, proc, tools, quote_sid, quote, match=None, values=None, when=None, kind="write"):
    assert quote in S(quote_sid), (quote, S(quote_sid))
    scope = {"procedure": proc}
    if when:
        scope["when"] = when
    effect = {"kind": kind}
    if tools:
        effect["tools"] = tools
    if match:
        effect["match"] = match
    o = {"id": oid, "origin": "package", "scope": scope, "effect": effect, "values": values or {},
         "check": "code", "level": "observe", "source": {"section": quote_sid.split(":")[0], "quote": quote}}
    return o


obligations = [
    ob("ob_reg_priority", "Registering", ["create_new_case"], "Registering:2",
       "Priority (if not provided → default = moderate)", {"priority": {"pattern": "{priority}"}},
       {"priority": {"from": "literal", "value": "moderate"}}, {"priority_given": "no"}),
    ob("ob_reg_state", "Registering", ["create_new_case"], "Registering:2", "Default state = new.",
       {"state": {"pattern": "{state}"}}, {"state": {"from": "literal", "value": "new"}}, {"state_given": "no"}),
    ob("ob_ent_inform", "Entitlement", None, "Entitlement:3", "If entitlement is invalid → inform the user.",
       when={"entitlement_valid": "no"}, kind="reply"),
    ob("ob_esc_flag", "Escalations", ["update_case"], "Escalations:2", "Record escalation = true on case.",
       {"escalation": {"pattern": "{escalation}"}}, {"escalation": {"from": "literal", "value": True}}),
    ob("ob_esc_reason", "Escalations", ["update_case"], "Escalations:3", "Capture escalation_reason.",
       {"escalation_reason": {"pattern": "{reason}"}},
       {"reason": {"from": "request", "about": "why the escalation is raised"}}),
    ob("ob_kn_create", "Knowledge", ["create_knowledge"], "Knowledge:3",
       "a new knowledge article should be created to capture the findings and resolution steps",
       when={"knowledge_found": "no"}),
    ob("ob_kn_link_created", "Knowledge", ["link_case_knowledge"], "Knowledge:4",
       "it should be linked to the case for future reference", when={"knowledge_found": "no"}),
    ob("ob_kn_sla", "Knowledge", ["link_new_case_sla"], "Knowledge:5",
       "appropriate SLA should be aligned to it"),
    ob("ob_kn_suggested", "Knowledge", ["link_case_knowledge"], "Knowledge:6",
       "When the knowledge is found through automated search it should be linked as suggested.",
       {"used_as": {"pattern": "{used_as}"}}, {"used_as": {"from": "literal", "value": "suggested"}},
       {"found_by_automated_search": "yes"}),
    ob("ob_kn_resolution", "Knowledge", ["link_case_knowledge"], "Knowledge:7",
       "it should have used as type to resolution in linking", {"used_as": {"pattern": "{used_as}"}},
       {"used_as": {"from": "literal", "value": "resolution"}}, {"useful_to_resolve": "yes"}),
    ob("ob_kn_applied", "Knowledge", ["link_case_knowledge"], "Knowledge:8",
       "In other cases if knowledge is linked it should as applied.", {"used_as": {"pattern": "{used_as}"}},
       {"used_as": {"from": "literal", "value": "applied"}},
       {"found_by_automated_search": "no", "useful_to_resolve": "no"}),
]

free1 = S("Free:1")
glob = {
    "global_rules": [
        {"id": "G-admin", "src": "General Instructions", "rule": S("General:1")},
        {"id": "G-violation", "src": "General Instructions", "rule": S("General:2")},
        {"id": "G-one-op", "src": "General Instructions", "rule": S("General:3")},
        {"id": "G-no-outside", "src": "General Instructions", "rule": S("General:4")},
        {"id": "G-no-ask", "src": "General Instructions", "rule": S("General:5")},
        {"id": "G-no-assume", "src": "Preamble", "rule": S("preamble:5")},
        {"id": "G-validate", "src": "Validation, Error Handling & Logging", "rule": S("Validation:1")},
        {"id": "G-close", "src": "Working on a Case", "rule": S("Working:5") + " " + S("Working:6"),
         "attach_when": "(?i)clos|resolv"},
        {"id": "G-entitlement", "src": "Knowledge Related Policies", "rule": S("Knowledge:2"),
         "attach_when": "(?i)case|entitlement"},
        {"id": "G-installed", "src": "Installed Product Management", "rule": S("Installed:3"),
         "attach_when": "(?i)installed product"},
        {"id": "G-security", "src": "Security", "rule": S("Security:1") + " " + S("Security:2")},
        {"id": "G-sla-pause", "src": "Service Levels & Timelines", "rule": S("Service:3"),
         "attach_when": "(?i)pending|sla"},
    ],
    "templates": {
        "Case Short Description": {"number": "Case Short Description", "name": "Case Short Description",
                                   "slots": ["Product name"],
                                   "text": "\"Product: \" + Product name + \", Issue: is not working as expected.\""},
        "KB title": {"number": "KB title", "name": "KB title", "slots": [],
                     "text": "Issue Resolution related to , step-by-step guide"},
        "KB content/body": {"number": "KB content/body", "name": "KB content/body", "slots": [],
                            "text": "This kind of issues are tackled by Assignment Group: , Assigned to: ."},
    },
    "definitions": [
        {"term": "max_cases_per_month = 0", "meaning": "max_cases_per_month = 0 means unlimited",
         "source": {"statement": P("Entitlement:2")}},
        {"term": "Visibility rules", "meaning": "internal = agents only external = customers can view",
         "source": {"statement": P("Linking:2")}},
        {"term": "escalation", "meaning": "Escalation is tracked within the case.",
         "source": {"statement": P("Escalations:6")}},
    ],
}
for tpl in glob["templates"].values():
    assert tpl["text"] in free1, tpl["text"]

links = [
    {"type": "refers_to", "src": P("Validation:2"), "dst": "policy:Case", "quote": "State transitions follow lifecycle rules."},
    {"type": "depends_on", "src": P("Manager:2"), "dst": "policy:Agent", "quote": "Has agent privileges plus"},
]

coverage = []

Q = []


def q(sids, question, rule_ids=(), open_values=()):
    item = {"statement_ids": [P(s) for s in sids], "question": question, "default_level": "remind"}
    if rule_ids:
        item["rule_ids"] = list(rule_ids)
    if open_values:
        item["open_values"] = list(open_values)
    Q.append(item)


role_rules = ["r_role_agent", "r_agent_user_data", "r_role_manager", "r_role_customer", "r_customer_internal"]
q(["General:1", "Agent:2", "Agent:7", "Manager:2", "Customer:3", "Customer:8"],
  "The assistant assumes the admin role by default. When does the role of the logged-in user (agent, manager, "
  "customer) limit what it may do, and how is that role known?", role_rules)
q(["Agent:3", "Agent:4", "Agent:6"],
  "Do the agent grants include linking or updating case SLAs, sending notifications and deleting case-knowledge "
  "links, or are these forbidden to agents? The SLA duties (pause on pending, align an SLA when a case moves to "
  "in progress) need SLA tools that the agent and manager grant lists do not name.",
  ["r_role_agent", "r_role_manager", "r_duty_sla_pause", "r_duty_sla_align"])
q(["Manager:6"], "Does 'contribute to knowledge management as reviewers' let a manager create or update knowledge "
  "articles?", ["r_role_manager"])
q(["Case:1", "Working:7", "Working:2"],
  "From which states may a case move to canceled? The transition list ends with a bare 'canceled'. Also, do agents "
  "only change new → in_progress (Working on a Case), or every transition of the lifecycle list?",
  ["r_case_transition"])
q(["Validation:3", "Case:2"], "No tool takes sys_updated_on. Does the system set it, or must the agent do something?")
q(["Escalations:4", "Working:1"], "No tool has a case notes, cause or resolution notes argument. Where must the "
  "escalation justification be logged?")
q(["Free:3", "Predefined:7"], "Escalation reason is described as free text (30–120 chars), but the tool accepts only "
  "urgency, vip, impact, breach_risk, customer_request. Which one applies?", ["r_esc_reason_update_case"])
q(["Free:1"], "Does the 30–120 character limit apply to the knowledge article body too?", ["r_len_kb_body"])
q(["Knowledge:6", "Knowledge:7", "Knowledge:8"], "An article found by automated search that resolves the case: "
  "suggested or resolution?")
q(["Installed:1", "Installed:3"], "Installed products must be in_use, but only retired / repair are excluded "
  "explicitly. May an in_stock installed product be attached to a case?",
  ["r_ip_in_use_create_new_case", "r_ip_in_use_update_case"])
q(["Security:1", "Manager:2"], "Security limits updates to cases the user owns, is assigned to or whose group they "
  "are in. Does this hold for a manager who reassigns cases across groups, and for the default admin role?",
  ["r_case_relationship"])
q(["Registering:2", "General:5"], "Registering says to collect inputs, but the assistant must not ask the user for "
  "information. Must missing inputs come only from the request and the records?")
q(["preamble:4"], "The text says 'ing record relationships'. Which word is meant (for example 'existing')?")

draft = {"modality": modality, "rules": rules, "procedures": procedures, "obligations": obligations, "global": glob,
         "links": links, "coverage": coverage, "policy_questions": Q}
(HERE / "draft.json").write_text(json.dumps(draft, indent=2, ensure_ascii=False))
print(len(modality), "marked;", len(rules), "rules;", len(obligations), "obligations;", len(Q), "questions")
