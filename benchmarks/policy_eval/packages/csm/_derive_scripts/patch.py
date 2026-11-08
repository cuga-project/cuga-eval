"""Apply the per-version changes to draft.remap.json and write draft.json. Usage: patch.py <version>"""
import json, sys
from pathlib import Path

ROOT = Path("/tmp/csm_pkg")
V = sys.argv[1]
DIR = ROOT / "derived" / V
D = json.loads((DIR / "draft.remap.json").read_text())
ST = {s["id"]: s["text"] for d in json.loads((DIR / "set.json").read_text())["documents"]
      for sec in d["sections"] for s in sec["statements"]}


def P(s):
    return "policy:" + s


def S(s):
    return ST[P(s)]


def sub(sid, part):
    assert part in S(sid), (sid, part, S(sid))
    return part


def mark(m, *sids):
    for s in sids:
        assert P(s) in ST, s
        D["modality"][P(s)] = m


def unmark(*sids):
    for s in sids:
        D["modality"].pop(P(s), None)


def R(rid):
    return next(r for r in D["rules"] if r["id"] == rid)


def drop_rule(rid):
    n = len(D["rules"])
    D["rules"] = [r for r in D["rules"] if r["id"] != rid]
    assert len(D["rules"]) == n - 1, rid


def rule(rid, cls, level, sids, body, quote=None, why=None):
    r = {"id": rid, "class": cls, "level": level, "statement_ids": [P(s) for s in sids], "rule": body}
    if quote:
        r["quote"] = quote
    if why:
        r["why"] = why
    D["rules"].append(r)


def proc(pid):
    return next(p for p in D["procedures"] if p["id"] == pid)


def grule(gid):
    return next(g for g in D["global"]["global_rules"] if g["id"] == gid)


def add_grule(gid, src, text, attach=None):
    g = {"id": gid, "src": src, "rule": text}
    if attach:
        g["attach_when"] = attach
    D["global"]["global_rules"].append(g)


def ob(oid, scope, kind, tools, quote, match=None, values=None, section=None):
    o = {"id": oid, "origin": "package", "scope": scope, "effect": {"kind": kind}, "values": values or {},
         "check": "code", "level": "observe", "source": {"section": section, "quote": quote}}
    if tools:
        o["effect"]["tools"] = tools
    if match:
        o["effect"]["match"] = match
    D["obligations"].append(o)
    return o


def O(oid):
    return next(o for o in D["obligations"] if o["id"] == oid)


def q(sids, question, rule_ids=None, open_values=None):
    item = {"statement_ids": [P(s) for s in sids], "question": question, "default_level": "remind"}
    if rule_ids:
        item["rule_ids"] = rule_ids
    if open_values:
        item["open_values"] = open_values
    D["policy_questions"].append(item)


def drop_q(pred):
    n = len(D["policy_questions"])
    D["policy_questions"] = [x for x in D["policy_questions"] if not pred(x)]
    assert len(D["policy_questions"]) < n


def Q(pred):
    return next(x for x in D["policy_questions"] if pred(x))


# ------------------------------------------------------------------ ff0e8fa373 family helpers
def ff_typo_fixed():  # 'ing record relationships' became 'existing': the question is answered by the text
    drop_q(lambda x: "ing record relationships" in x["question"])


def ff_channel_default(part, value):
    p = proc("Registering")
    p["decisions"].insert(0, {"id": "channel_given", "rule": sub("Registering:2", part),
                              "then": "use the channel provided", "else": f"channel = {value}"})
    ob("ob_reg_channel", {"procedure": "Registering", "when": {"channel_given": "no"}}, "write", ["create_new_case"],
       sub("Registering:2", part), {"channel": {"pattern": "{channel}"}},
       {"channel": {"from": "literal", "value": value}}, "Registering")


def ff_entitlement_after_assignment():
    title = "Entitlement Validation (Required after case assignment)"
    p = proc("Entitlement")
    p["name"] = title
    add_grule("G-entitlement-after-assign", title, title, "(?i)assign")
    for tool in ("assign_case_to_user", "set_case_assignment_group"):
        rule(f"r_duty_entitlement_after_{tool}", "hard", "remind", ["Entitlement:1"],
             {"type": "duty", "trigger": {"tool": tool}, "then": {"tool": "find_entitlements"}},
             quote=S("Entitlement:1"))
    rule("r_duty_entitlement_after_update_case", "hard", "remind", ["Entitlement:1"],
         {"type": "duty", "trigger": {"tool": "update_case", "when": {"assigned_to": ["*"]}},
          "then": {"tool": "find_entitlements"}}, quote=S("Entitlement:1"))


def ff_primary_contact():
    mark("must", "Validation:5")
    rule("v_primary_contact", "judgment", "remind", ["Validation:5"],
         {"type": "verify", "tools": ["create_contact", "update_contact"], "statement": S("Validation:5")},
         why="Needs the other contacts of the account and their is_primary flags; the call carries only this "
             "contact's flag, and no typed rule counts records.")
    add_grule("G-primary-contact", "Validation, Error Handling & Logging", S("Validation:5"), "(?i)contact")


def ff_lengths(lo, hi):
    quote = sub("Free:1", f"Character limits: {lo}–{hi} chars")
    for rid in ("r_len_short_description", "r_len_kb_title", "r_len_kb_body"):
        R(rid)["quote"] = quote
        R(rid)["rule"]["pattern"] = r"^[\s\S]{%d,%d}$" % (lo, hi)
    x = Q(lambda x: x.get("rule_ids") == ["r_len_kb_body"])
    x["question"] = x["question"].replace("30–120", f"{lo}–{hi}")
    x = Q(lambda x: "Escalation reason is described as free text" in x["question"])
    x["question"] = x["question"].replace("30–120", f"{lo}–{hi}")


def ff_short_description_template(text):
    D["global"]["templates"]["Case Short Description"]["text"] = text


def ff_kb_templates(title, body, title_slots, body_slots):
    t = D["global"]["templates"]
    t["KB title"].update({"text": title, "slots": title_slots})
    t["KB content/body"].update({"text": body, "slots": body_slots})


def ff_role_sentence():  # preamble:2 now names the assistant's role
    add_grule("G-role", "Preamble", S("preamble:2"))
    x = Q(lambda x: "assumes the admin role by default" in x["question"])
    x["statement_ids"].insert(0, P("preamble:2"))


def ff_reopen():  # Case:4: closed case reopened by setting state new
    mark("may", "Case:4")
    r = R("r_case_transition")
    r["rule"]["edges"]["closed"] = ["new"]
    r["statement_ids"].append(P("Case:4"))
    D["procedures"].append({
        "id": "Reopen", "name": "Case Lifecycle Management: reopening a case", "category": "Core Operations",
        "src": "Case Lifecycle Management", "applies_when": "When a resolved issue occurs again",
        "inputs": [{"fact": "the closed case and its reopen_count", "source": "search_cases"}],
        "decisions": [], "steps": [{"id": P("Case:4"), "action": "update_case"}], "must_not": [], "links": []})
    ob("ob_reopen", {"procedure": "Reopen"}, "write", ["update_case"],
       sub("Case:4", "the closed case can be reopened by setting the state to new, increasing the reopen_count by 1"),
       {"state": {"pattern": "{state}"}, "reopen_count": {"pattern": "{reopen_count}"}},
       {"state": {"from": "literal", "value": "new"},
        "reopen_count": {"from": "computed", "fn": "the case's current reopen_count plus 1"}}, "Case")
    q(["Case:4", "Case:1"], "Reopening sets a closed case to new, but the list of valid state transitions has no "
      "transition out of closed. Is closed → new allowed only when a resolved issue occurs again?",
      ["r_case_transition"])


def ff_assign_add_to_group():
    mark("must", "Assigning:1")
    D["procedures"].append({
        "id": "Assigning", "name": "Assigning a Case", "category": "Core Operations", "src": "Assigning a Case",
        "applies_when": "A case may be assigned to",
        "inputs": [{"fact": "the user's active flag, role and group memberships",
                    "source": "list_users, check_user_membership"}],
        "decisions": [{"id": "assignee_in_group", "rule": sub("Assigning:1", "A user (assigned_to) within that group"),
                       "then": "assign the user", "else": "add him to the group, then assign"}],
        "steps": [{"id": P("Assigning:1")}, {"id": P("Assigning:2")}, {"id": P("Assigning:3")}],
        "must_not": [], "links": []})
    ob("ob_assign_add_member", {"procedure": "Assigning", "when": {"assignee_in_group": "no"}}, "write",
       ["add_new_group_member"], sub("Assigning:1", "within that group (if not add him to the group)"),
       {"group_id": {"pattern": "{group}"}, "user_id": {"pattern": "{user}"}},
       {"group": {"from": "case_fact", "field": "assignment_group_id", "record": "the case"},
        "user": {"from": "request", "about": "the user the case is assigned to"}}, "Assigning")
    add_grule("G-assign-add", "Assigning a Case", S("Assigning:1"), "(?i)assign")


def ff_employee_leaves(sid):
    mark("must", sid)
    D["procedures"].append({
        "id": "Employee-leaves", "name": "When an employee leaves", "category": "Administration",
        "src": "Knowledge Related Policies", "applies_when": "When an employee leaves",
        "inputs": [{"fact": "the user and the user's group memberships", "source": "list_users, list_group_members"}],
        "decisions": [], "steps": [{"id": P(sid)}], "must_not": [], "links": []})
    ob("ob_leave_deactivate", {"procedure": "Employee-leaves"}, "write", ["update_user_details"],
       sub(sid, "deactivate their account"), {"active": {"pattern": "{active}"}},
       {"active": {"from": "literal", "value": False}}, "Knowledge")
    ob("ob_leave_remove", {"procedure": "Employee-leaves"}, "write", ["remove_group_membership"],
       sub(sid, "remove them from their"), None, None, "Knowledge")


def ff_kb_link_pending():  # Registering:3 'Once case linked to a knowledge article marked the state = "pending".'
    mark("must", "Registering:3")
    rule("r_duty_kb_pending", "hard", "remind", ["Registering:3"],
         {"type": "duty", "trigger": {"tool": "link_case_knowledge"},
          "then": {"tool": "update_case", "when": {"state": ["pending"]}}}, quote=S("Registering:3"))
    p = proc("Registering")
    p["decisions"].append({"id": "kb_linked", "rule": sub("Registering:3", "Once case linked to a knowledge article"),
                           "then": "state = pending", "else": "no change"})
    i = next(k for k, s in enumerate(p["steps"]) if s["id"] == P("Registering:4"))
    p["steps"].insert(i, {"id": P("Registering:3"), "action": "update_case",
                          "condition": "Once case linked to a knowledge article"})
    ob("ob_reg_pending", {"procedure": "Registering", "when": {"kb_linked": "yes"}}, "write", ["update_case"],
       S("Registering:3"), {"state": {"pattern": "{state}"}}, {"state": {"from": "literal", "value": "pending"}},
       "Registering")


# ------------------------------------------------------------------ 445d515155 family helpers
def gi_merge():  # general-instructions:4 and :5 are one statement now
    unmark("general-instructions:5")
    drop_rule("g_reason")
    grule("G-no-ask")["rule"] = S("general-instructions:4")
    D["modality"][P("general-instructions:4")] = "must_not"


def no_reopen_edge():  # 'resolved → closed / new' became 'resolved → closed'
    e = R("r_case_transition")["rule"]["edges"]
    e["resolved"] = [s for s in e["resolved"] if s != "new"]


def gi_role(role_word, is_agent=False):
    add_grule("G-role", "Preamble", S("preamble:1"))
    rids = ["r_agent_user_group", "r_agent_read_only", "r_agent_grant", "r_manager_grant", "r_customer_grant"]
    if is_agent:
        q(["preamble:1", "agent:2", "agent:8"], "The preamble says the assistant is a Customer Service Management "
          "agent. Do the agent limits (read-only accounts, contacts, products, contracts and entitlements; no user, "
          "group or membership changes) apply to the assistant itself, whatever the logged-in user's role?", rids)
    else:
        q(["preamble:1", "administrator:1"], f"The preamble says the assistant is a Customer Service Management "
          f"{role_word}. Does the assistant then have full access, or do the role limits of the logged-in user "
          "(agent, manager, customer) still apply?", rids)


def ik_doubled_quotes():
    D["global"]["templates"]["Case Short Description"]["text"] = \
        '""Product: "" + Product name + "", Issue: is not working as expected.""'


def gi_assign_proc(active_fix):
    steps = [{"id": P("2:5")}, {"id": P("2:6")}, {"id": P("2:7")}]
    decisions = [{"id": "assignee_in_group", "rule": "Be members of the assigned group",
                  "then": "assign the user", "else": "add the user to that group before assignment"}]
    if active_fix:
        decisions.insert(0, {"id": "assignee_active", "rule": "Be active",
                             "then": "assign the user", "else": "mark them as active"})
    D["procedures"].append({
        "id": "2", "name": "Assigning a Case", "category": "Core Operations", "src": "§2",
        "applies_when": "A case may be assigned to",
        "inputs": [{"fact": "the user's active flag, role and group memberships",
                    "source": "list_users, check_user_membership"}],
        "decisions": decisions, "steps": steps, "must_not": [], "links": []})
    if active_fix:
        ob("ob_2_activate", {"procedure": "2", "when": {"assignee_active": "no"}}, "write", ["update_user_details"],
           S("2:5"), {"active": {"pattern": "{active}"}}, {"active": {"from": "literal", "value": True}}, "2")
    ob("ob_2_add_member", {"procedure": "2", "when": {"assignee_in_group": "no"}}, "write", ["add_new_group_member"],
       S("2:6"), {"group_id": {"pattern": "{group}"}, "user_id": {"pattern": "{user}"}},
       {"group": {"from": "case_fact", "field": "assignment_group_id", "record": "the case"},
        "user": {"from": "request", "about": "the user the case is assigned to"}}, "2")
    grule("G-assign")["rule"] = S("2:5") + " " + S("2:6") + " " + S("2:7")


# ------------------------------------------------------------------ versions
FF = {
    "b54b350f9a": None, "e68dfd3121": None, "c4241a91ec": None, "83b33e2475": None, "3f852d9a77": None,
    "8b2cc5b633": None, "7013944124": None, "958ed1f4e3": None, "be91daf5c0": None, "227d117974": None,
    "59f0b27436": None, "8cab4406c9": None, "1e895f5294": None, "4dc9c5c56a": None, "9cee36a8c4": None,
    "48c3bf0328": None,
}

if V == "b54b350f9a":
    mark("must", "Free:4")
    for tool in ("enlist_new_contract", "update_contract"):
        rule(f"r_price_rounded_{tool}", "hard", "deny", ["Free:4"],
             {"type": "format", "tool": tool, "arg": "contract_price", "pattern": r"^-?\d+$"},
             quote=sub("Free:4", "ensure it is rounded off if any decimal values are present"))
    add_grule("G-price", "Free form text policies", S("Free:4"), "(?i)contract")
elif V == "e68dfd3121":
    ff_typo_fixed()
    ff_channel_default("Contact channel (channel, if not provided → default = web)", "web")
elif V == "c4241a91ec":
    R("r_case_transition")["rule"]["edges"]["closed"] = ["in_progress"]
    R("r_case_transition")["quote"] = sub("Case:1", "Valid state transitions: new → in_progress / pending / resolved "
                                          "in_progress → pending / resolved pending → in_progress / resolved resolved"
                                          " → closed / new closed → in_progress")
elif V == "83b33e2475":
    add_grule("G-today", "Free form text policies", S("Free:4"))
elif V == "3f852d9a77":
    ff_typo_fixed()
    ff_entitlement_after_assignment()
    ff_primary_contact()
elif V == "8b2cc5b633":
    ff_typo_fixed()
    drop_rule("g_one_operation")
    D["modality"][P("General:3")] = "must_not"  # old General:3 was removed; its id now names the next statement
    D["global"]["global_rules"] = [g for g in D["global"]["global_rules"] if g["id"] != "G-one-op"]
elif V == "be91daf5c0":
    ff_typo_fixed()
elif V == "9cee36a8c4":
    pass  # only curly apostrophes became straight ones; texts were replaced by align.py
elif V == "227d117974":
    ff_short_description_template('""Product: "" + Product name + "", Issue: is not working as expected.""')
elif V == "59f0b27436":
    ff_typo_fixed()
    ff_channel_default("Contact channel (if not provided → default = email )", "email")
    ff_entitlement_after_assignment()
    ff_primary_contact()
    ff_lengths(30, 190)
    ff_short_description_template('""Product: "" + Product name + "", Issue: is not working as expected.""')
elif V == "1e895f5294":
    ff_typo_fixed()
    x = Q(lambda x: "Escalation reason is described as free text" in x["question"])
    x["question"] = ("The Free form text policies give an escalation reason text (\"The case could not be completed on "
                     "time...\"), but the tool accepts only urgency, vip, impact, breach_risk, customer_request. Which "
                     "one applies?")
elif V == "958ed1f4e3":
    mark("should", "Knowledge:11")
    quote = sub("Knowledge:11", "If a new knowledge is created, its visibility should be internal")
    rule("r_kb_new_internal", "hard", "remind", ["Knowledge:11"],
         {"type": "allowed_values", "tool": "create_knowledge", "arg": "visibility", "values": ["internal"]},
         quote=quote)
    proc("Knowledge")["steps"].append({"id": P("Knowledge:11"), "action": "create_knowledge"})
    ob("ob_kn_internal", {"procedure": "Knowledge"}, "write", ["create_knowledge"], quote,
       {"visibility": {"pattern": "{visibility}"}}, {"visibility": {"from": "literal", "value": "internal"}},
       "Knowledge")
elif V == "4dc9c5c56a":
    mark("must", "Case:4", "Escalations:7", "Knowledge:11")
    rule("g_pick_priority", "guidance", "observe", ["Case:4"], {"type": "guidance", "text": S("Case:4")})
    add_grule("G-pick-priority", "Case Lifecycle Management", S("Case:4"))
    p = proc("Escalations")
    p["decisions"].append({"id": "customer_escalates", "rule": sub("Escalations:7", "If customer escalates a case"),
                           "then": "escalation_reason = customer_request", "else": "capture the reason"})
    p["steps"].append({"id": P("Escalations:7"), "action": "update_case", "condition": "If customer escalates a case"})
    O("ob_esc_reason")["scope"]["when"] = {"customer_escalates": "no"}
    ob("ob_esc_customer", {"procedure": "Escalations", "when": {"customer_escalates": "yes"}}, "write",
       ["update_case"], S("Escalations:7"), {"escalation_reason": {"pattern": "{reason}"}},
       {"reason": {"from": "literal", "value": "customer_request"}}, "Escalations")
    rule("v_notify_external", "judgment", "remind", ["Knowledge:11"],
         {"type": "verify", "tools": ["send_notification"], "statement": S("Knowledge:11")},
         why="Needs the visibility of the article in knowledge_id and whether the recipient is a customer; a "
             "reference_status rule on visibility would also forbid internal articles in notifications to staff.")
    add_grule("G-notify-external", "Knowledge Related Policies", S("Knowledge:11"), "(?i)notif")
elif V == "7013944124":
    ff_role_sentence()
    x = Q(lambda x: "ing record relationships" in x["question"])
    x["question"] = "The text says 'exising record relationships'. Which word is meant (for example 'existing')?"
    # Registering:2: the default state depends on assignment
    p = proc("Registering")
    p["decisions"] = [d for d in p["decisions"] if d["id"] != "state_given"] + [
        {"id": "state_given", "rule": sub("Registering:2", "The default case state"), "then": "use the state provided",
         "else": "see assigned_at_creation"},
        {"id": "assigned_at_creation", "rule": sub("Registering:2", "when it is assigned to a group or user"),
         "then": "state = in_progress", "else": "state = new"}]
    D["obligations"] = [o for o in D["obligations"] if o["id"] != "ob_reg_state"]
    ob("ob_reg_state_new", {"procedure": "Registering", "when": {"state_given": "no", "assigned_at_creation": "no"}},
       "write", ["create_new_case"],
       sub("Registering:2", "The default case state must be set to new when it is not assigned to any group or user"),
       {"state": {"pattern": "{state}"}}, {"state": {"from": "literal", "value": "new"}}, "Registering")
    ob("ob_reg_state_in_progress",
       {"procedure": "Registering", "when": {"state_given": "no", "assigned_at_creation": "yes"}}, "write",
       ["create_new_case"], sub("Registering:2", "must be set to in_progress when it is assigned to a group or user"),
       {"state": {"pattern": "{state}"}}, {"state": {"from": "literal", "value": "in_progress"}}, "Registering")
    # Registering:4: an interaction with every new case
    mark("must", "Registering:4")
    rule("r_duty_interaction", "hard", "remind", ["Registering:4"],
         {"type": "duty", "trigger": {"tool": "create_new_case"}, "then": {"tool": "register_new_interaction"}},
         quote=S("Registering:4"))
    i = next(k for k, s in enumerate(p["steps"]) if s["id"] == P("Registering:2"))
    p["steps"].insert(i + 1, {"id": P("Registering:4"), "action": "register_new_interaction"})
    ob("ob_reg_interaction", {"procedure": "Registering"}, "write", ["register_new_interaction"],
       S("Registering:4"), None, None, "Registering")
    # Linking SLAs to Cases (new section)
    mark("must", "Linking:1")
    mark("should", "Linking:2")
    rule("r_sla_link_case_new", "hard", "block_once", ["Linking:1"],
         {"type": "record_condition", "tools": ["link_new_case_sla"], "field": "state", "op": "equals",
          "value": "new", "effect": "forbid"},
         quote=sub("Linking:1", "the case state must first be transitioned from new to in_progress before calling "
                                "link_new_case_sla"))
    D["procedures"].append({
        "id": "Linking", "name": "Linking SLAs to Cases", "category": "Core Operations",
        "src": "Linking SLAs to Cases", "applies_when": S("Linking:3"),
        "inputs": [{"fact": "the case state", "source": "search_cases"},
                   {"fact": "the SLA definition", "source": "find_sla_definitions"}],
        "decisions": [], "steps": [{"id": P("Linking:1")}, {"id": P("Linking:2"), "action": "link_new_case_sla"}],
        "must_not": [], "links": []})
    ob("ob_link_case_in_progress", {"procedure": "Linking"}, "write", ["update_case"],
       sub("Linking:1", "the case state must first be transitioned from new to in_progress"),
       {"state": {"pattern": "{state}"}}, {"state": {"from": "literal", "value": "in_progress"}}, "Linking")
    ob("ob_link_sla_stage", {"procedure": "Linking"}, "write", ["link_new_case_sla"],
       sub("Linking:2", "The SLA stage on the linked record should also be set to in_progress"),
       {"stage": {"pattern": "{stage}"}}, {"stage": {"from": "literal", "value": "in_progress"}}, "Linking")
    add_grule("G-sla-link", "Linking SLAs to Cases", S("Linking:1"), "(?i)sla")
    ff_assign_add_to_group()
    ff_reopen()
    ff_employee_leaves("Knowledge:11")
    ff_kb_templates("Issue Resolution related to <Product name>, step-by-step guide",
                    "This kind of issues are tackled by Assignment Group: <Group name>, Assigned to: "
                    "<person/group manager>. Steps to resolve the issue: <can be any steps related not related>, "
                    "Suggested Priority: <Priority>.",
                    ["Product name"], ["Group name", "person/group manager", "can be any steps related not related",
                                       "Priority"])
elif V in ("8cab4406c9", "48c3bf0328"):
    ff_role_sentence()
    ff_kb_link_pending()
    ff_reopen()
    ff_kb_templates("Issue Resolution related to Product name>, step-by-step guide",
                    "This kind of issues are tackled by Assignment Group: Group name>, Assigned to: "
                    "person/group manager>. Steps to resolve the issue: can be any steps related not related>, "
                    "Suggested Priority: Priority>.",
                    ["Product name"], ["Group name", "person/group manager", "can be any steps related not related",
                                       "Priority"])
    if V == "48c3bf0328":
        ff_assign_add_to_group()
        ff_employee_leaves("Knowledge:11")
# 445d515155 family
elif V in ("53312da006", "0e62b2d61a", "05d79a8381", "5c477d8f94", "0256df5630"):
    gi_merge()
    no_reopen_edge()
    word = {"53312da006": "admin", "05d79a8381": "agent", "5c477d8f94": "administrator",
            "0256df5630": "administrator"}.get(V)
    if word:
        gi_role(word, is_agent=word == "agent")
    if V == "5c477d8f94":
        ik_doubled_quotes()
        gi_assign_proc(active_fix=False)
        mark("must", "11:3", "geography:3", "geography:4")
        rule("g_validate_before_create", "guidance", "observe", ["11:3"], {"type": "guidance", "text": S("11:3")})
        grule("G-validate")["rule"] = "Always validate existence and integrity of: " + S("11:2") + " " + S("11:3")
        for tool in ("add_location", "update_location"):
            rule(f"r_plot_no_{tool}", "hard", "remind", ["geography:3"],
                 {"type": "format", "tool": tool, "arg": "plot_no", "pattern": r"^Plot \d+$"},
                 quote=S("geography:3"))
        ob("ob_location_name", {"when": {"location_name_given": "no"}}, "write", ["add_location"],
           S("geography:4"), None, None, "geography")
        q(["geography:3"], "location.plot_no is given as 'Plot ' with the example 'Plot 103'. Must it always be "
          "'Plot' followed by a number?", ["r_plot_no_add_location", "r_plot_no_update_location"])
        q(["geography:4"], "The default location name is 'User - ' with the example 'User 106 - Mumbai'. What goes "
          "after 'User' (a user id, a user number, the plot number?) and is the part after the dash the city?")
    if V == "0256df5630":
        ik_doubled_quotes()
        gi_assign_proc(active_fix=True)
        mark("must", "8:9", "8:12", "8:13")
        p = proc("8")
        i = next(k for k, s in enumerate(p["steps"]) if s["id"] == P("8:8"))
        p["steps"].insert(i + 1, {"id": P("8:9"), "action": "update_case"})
        p["steps"] += [{"id": P("8:12"), "action": "link_new_case_sla"},
                       {"id": P("8:13"), "action": "link_new_case_sla", "condition": "IF not in scope"}]
        p["decisions"].append({"id": "no_pause_sla_in_scope", "rule": "IF not in scope",
                               "then": "apply appropriate SLA definition",
                               "else": 'apply the "no pause on pending" Response SLA definition'})
        p["inputs"].append({"fact": "SLA definitions (metric, pause_on_pending)", "source": "find_sla_definitions"})
        ob("ob_8_priority", {"procedure": "8"}, "write", ["update_case"],
           sub("8:9", "Escalation triggered a two-level priority increase on the case"),
           {"priority": {"pattern": "{priority}"}},
           {"priority": {"from": "computed",
                         "fn": "two levels above the case's current priority in the order low, moderate, high, "
                               "critical (e.g., Moderate → Critical)"}}, "8")
        ob("ob_8_sla", {"procedure": "8", "when": {"no_pause_sla_in_scope": "no"}}, "write", ["link_new_case_sla"],
           sub("8:12", 'apply the appropriate "no pause on pending" Response SLA definition'),
           {"sla_def_id": {"pattern": "{sla}"}},
           {"sla": {"from": "case_fact", "field": "sla_def_id",
                    "record": "the sla_definition with metric = response and pause_on_pending = false"}}, "8")
        ob("ob_8_sla_other", {"procedure": "8", "when": {"no_pause_sla_in_scope": "yes"}}, "write",
           ["link_new_case_sla"], S("8:13"), None, None, "8")
        q(["8:9"], "Escalation raises the priority by two levels (Moderate → Critical). What is the new priority of a "
          "case that is already high or critical?", open_values=None)
        q(["8:12", "8:13"], "What does 'IF not in scope' mean for the \"no pause on pending\" Response SLA definition: "
          "no such definition exists, or the account's entitlement does not cover it? And what is the 'appropriate "
          "SLA definition' then?")
else:
    raise SystemExit("unknown version " + V)

(DIR / "draft.json").write_text(json.dumps(D, indent=1, ensure_ascii=False))
print("wrote", DIR / "draft.json")
