# Create a new issue (upstream)

1. Create the issue with the GitHub CLI (`gh issue create`).
2. Open it against the **origin** upstream (use that remote / repository—not a fork-only default).
3. Labels: run `gh label list` for that upstream repository. Only use names that appear in that output. Prefer `--label enhancement` when filing a feature (matches the template intent). Add other applicable labels. Do not invent label names.
4. Use title prefix `[Feature]:` (consistent with `.github/ISSUE_TEMPLATE/feature_request.yml`).
5. Write the body using the same sections as that template:
   - **Feature Request** — what to add
   - **Motivation / Problem** — why it matters
   - **Use Case** — who benefits and how
   - **Proposed Solution** — how it could work
   - **Alternatives Considered** (if any)
   - **Priority** — Low / Medium / High / Critical
   - **Additional Context** (links, examples)
   Incorporate the user's message and any selected editor/context so the issue is concrete and complete.
6. Do not add "Made with Cursor" or similar promotional footers to the issue.
