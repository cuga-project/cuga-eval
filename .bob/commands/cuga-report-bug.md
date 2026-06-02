# Report a bug (upstream issue)

1. Create the issue with the GitHub CLI (`gh issue create`).
2. Open it against the **origin** upstream (use that remote / repository—not a fork-only default).
3. Labels: run `gh label list` for that upstream repository (same scope as the issue, e.g. `--repo owner/name` if you are not using the default remote). Only use names that appear in that output. When you run `gh issue create`, pass `--label bug` when filing a bug, and repeat `--label <name>` for each other applicable label. Do not invent label names.
4. Use title prefix `[Bug]:` (consistent with `.github/ISSUE_TEMPLATE/bug_report.yml`).
5. Write the body using the same sections as that template:
   - **Bug Description**
   - **Steps to Reproduce**
   - **Expected Behavior**
   - **Actual Behavior**
   - **Environment** (OS, Python, cuga-eval / benchmark context, sibling `cuga-agent` checkout if relevant)
   - **Error Logs / Screenshots** (if any)
   - **Configuration** (redact secrets; benchmark `.env` paths only)
   - **Additional Context** (if any)
   Incorporate the user's message and any selected editor/context so the issue is concrete and reproducible.
6. Do not add "Made with Cursor" or similar promotional footers to the issue.
