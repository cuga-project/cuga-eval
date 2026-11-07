"""Procedure graph of the Vanguard Shield Mutual SOP (HANDBOOK task insurance_vanguard_shield_mutual_9b2f7a29).

Built by Claude from the SOP text only (no workbook, PDFs, emails, rubric or tests read). §1 and §2.1/§2.4 are
structured by hand; the other procedures keep the SOP's bullet steps verbatim (extracted by code), templates are
extracted verbatim.

    python3 -I vanguard_graph.py <sop.txt> <out.json>
"""

import json
import re
import sys

GLOBAL_RULES = [
    {
        "id": "G-tools",
        "src": "§1.2",
        "rule": "Use only Email, Calendar, Slack, Shopify, Jira, Excel, Word, PowerPoint and PDF. Source data arrives as attachments on the Jira issues or Email threads each procedure cites. A missing expected attachment: follow that section's exception path (typically Jira escalation). No access to a required tool: create a Jira ticket in the IT-Support queue immediately.",
    },
    {
        "id": "G-queue-assignee",
        "src": "§1.3",
        "rule": "Queue Assignee: route by role using the pinned issue 'Queue Roles & Assignees' on the target queue board. Missing or blank: create a Jira IT-Support ticket 'Missing Queue Assignee – [Queue Name] – [Role]' and Slack ops-support.",
    },
    {
        "id": "G-materiality",
        "src": "§1.3",
        "attach_when": r"\$5,000|threshold|exceeding",
        "rule": "Materiality Override: if a queue's pinned issue has a 'Materiality Override' section with a different dollar threshold, that Jira-posted threshold governs over the SOP's printed threshold. Check it before applying a dollar threshold.",
    },
    {
        "id": "G-fields",
        "src": "§1.3",
        "rule": "Jira custom fields (Reporting Manager, Department Head, Billing Contact Email, Rate Table Source) have fallback paths when blank (see the procedure).",
    },
    {
        "id": "G-files",
        "src": "§1.4",
        "rule": "Output file names follow the procedure's pattern; otherwise [Deliverable Type][Identifier][Date YYYY-MM-DD].[ext]; no spaces (use underscores).",
    },
    {
        "id": "G-codes",
        "src": "Appendix C",
        "rule": "Status codes: FIN-100 Cleared & Posted (reconciliation complete, outcome documented on Jira); FIN-201 Vendor AP Hold; TRE-900 High-Risk Exception; UND-304 Audit Variance; CLM-440 Subro Potential; CLM-999 SIU Hold; CLM-910 Identity Verification Hold; CLM-920 Complex Beneficiary Hold.",
    },
]

P = []


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
    "2.1",
    "Reconciling Intercompany Suspense",
    "Finance & Accounting",
    "Month-end intercompany suspense reconciliation (Jira OPS-FIN-SUSPENSE-[YYYY-MM]).",
    [
        "1. Workbook: from Jira OPS-FIN-SUSPENSE-[YYYY-MM] download the suspense workbook; save a local working copy with a month identifier (§1.4).",
        "2. Split by Amount: (a) items exceeding $5,000, (b) items ≤ $5,000 — unless a Materiality Override on the queue's pinned issue sets another threshold (§1.3).",
        "3. Items ≤ threshold, per line: (a) open the linked Jira sub-task or the PDF on the month-close issue matching the transaction ID AND amount; (b) confirm the GL code from the invoice text and the Excel line description; (c) record the tie-out in the workbook: Support Found (Y/N), Support Location / Invoice; (d) support found → Jira comment on the line's sub-task with transaction ID, target GL and status FIN-100 Cleared & Posted. No support or unclear coding → Exception handling.",
        "4. GL conflict (invoice GL ≠ Excel line GL): do not resolve it yourself; record both codes in the tie-out columns and mark Conflict? = Y; Jira comment on the sub-task: \"GL conflict: Invoice shows [code A], Excel line shows [code B] — requesting Controller clarification.\"; then Exception handling.",
        "5. Items > threshold: verify approval in Slack finance-approvals with search: has:link [Exact Dollar Amount] (the manager approval message).",
        "6. Locate the PDF invoice on the matching sub-task or linked issue for the transaction ID.",
        "7. Items > threshold with approval and support: Jira comment on the sub-task with the GL code from the PDF; transition/label FIN-100 Cleared & Posted after approval.",
        "8. Exception handling (PDF missing, Slack approval not found for > threshold, GL coding undeterminable, or GL conflict): create a Jira ticket in FIN-Exceptions; paste Template B-1 into the description; assign to the Finance Controller named on the FIN-Exceptions board's pinned issue (§1.3 Queue Assignee); in comments note the Jira issue keys and Slack searches used and what evidence was missing or conflicting.",
        "9. Deliver the local reconciliation workbook with the tie-out columns for every line.",
    ],
    inputs=[
        {
            "fact": "suspense lines (transaction ID, amount, GL in description)",
            "source": "suspense workbook from OPS-FIN-SUSPENSE-[YYYY-MM]",
        },
        {
            "fact": "invoice PDF per transaction (ID, amount, GL)",
            "source": "Jira sub-tasks / month-close attachments",
        },
        {
            "fact": "manager approval for items > threshold",
            "source": "Slack finance-approvals (has:link [Exact Dollar Amount])",
        },
        {"fact": "threshold override, Finance Controller", "source": "FIN-Exceptions board pinned issue"},
    ],
    decisions=[
        {
            "id": "threshold",
            "rule": "Amount > $5,000 (or the pinned Materiality Override) → approval required",
            "then": "steps 5-7",
            "else": "step 3",
        },
        {
            "id": "support",
            "rule": "a PDF matching transaction ID and amount exists",
            "else": "exception (B-1)",
        },
        {
            "id": "gl_conflict",
            "rule": "invoice GL = Excel line GL",
            "else": "Conflict? = Y, conflict comment, exception (B-1); never pick one yourself",
        },
    ],
    must_not=[
        "Do not mark a line FIN-100 Cleared & Posted without matching support (PDF with the same transaction ID and amount).",
        "Do not clear an item above the threshold without the Slack manager approval.",
        "Do not resolve a GL conflict yourself (no choosing the invoice or the Excel code).",
    ],
    links=[
        {
            "type": "next",
            "to": "2.4",
            "when": "after §2.1 is complete for the month (or OPS-FIN-MONTH-[YYYY-MM] is complete)",
        }
    ],
    deadlines=["Clear and document by the 5th business day of the month."],
)

proc(
    "2.4",
    "Month-end Finance Summary Deck (PowerPoint)",
    "Finance & Accounting",
    "After completing §2.1 for the calendar month (or when OPS-FIN-MONTH-[YYYY-MM] is marked complete).",
    [
        "Build the month-summary PowerPoint (name per §1.4 with year-month). Slide 1 title: \"Vanguard Shield | Finance month-end | [Month YYYY]\"; analyst name. Slide 2 suspense: lines cleared to FIN-100 (count), open exceptions (count), up to five Jira keys only (no dollar amounts unless the parent issue allows). Slide 3 exceptions: remaining FIN-Exceptions keys and next action.",
        "Attach the deck to Jira OPS-FIN-MONTH-[YYYY-MM] (or the month-close parent named there).",
    ],
    must_not=["Do not put dollar amounts on the slides unless the parent issue explicitly allows it."],
)


def sections(text):
    out, cur = [], None
    for line in text.split("\n"):
        m = re.match(r"^##\s+(\d+\.\d+)\s+(.*)$", line)
        if m:
            cur = {"id": m.group(1), "name": m.group(2).strip(), "lines": []}
            out.append(cur)
            continue
        if line.startswith("#"):
            cur = None
            continue
        if cur is not None and line.strip() and line.strip() != "-":
            cur["lines"].append(line.strip().lstrip("- ").strip())
    return out


def templates(text):
    out, cur = {}, None
    for line in text.split("\n"):
        m = re.match(r"^##\s+(?:Memo\s+)?Template\s+([A-D]-\d+):?\s*(.*)$", line)
        if m:
            cur = m.group(1)
            out[cur] = {"number": cur, "name": m.group(2).strip(), "lines": []}
            continue
        if line.startswith("#"):
            cur = None
            continue
        if cur:
            out[cur]["lines"].append(line)
    for t in out.values():
        body = "\n".join(t.pop("lines")).replace("- \n", "- ").strip()
        t["text"], t["slots"] = body, sorted(set(re.findall(r"\[[^\]\n]+\]", body)))
    return out


def main() -> None:
    text = open(sys.argv[1]).read()
    done = {p["id"] for p in P}
    for s in sections(text):
        if s["id"] in done or s["id"].startswith("1.") or not s["lines"]:
            continue
        obj = next((x for x in s["lines"] if x.lower().startswith("objective")), s["lines"][0])
        proc(s["id"], s["name"], "SOP", obj, [x for x in s["lines"] if x is not obj])
    P.sort(key=lambda p: [int(x) for x in p["id"].split(".")])
    graph = {
        "id": "VanguardShield_SOP",
        "version": "claude_v1",
        "built_by": "Claude from the SOP text only (no workbook, PDFs, emails, rubric or tests read); §1, §2.1, §2.4 by hand, other procedures verbatim",
        "global_rules": GLOBAL_RULES,
        "procedures": P,
        "templates": templates(text),
        "routing": {},
        "calendar": {"workdays": [0, 1, 2, 3, 4], "holidays": []},
    }
    json.dump(graph, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    print(len(P), "procedures,", len(graph["templates"]), "templates")


if __name__ == "__main__":
    main()
