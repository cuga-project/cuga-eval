# Experiment profiles

Variants of a best profile, made for one measured question. They are not best profiles, so they have no entry in
`best_profiles.json` and no case in `golden_hooks.json`. Run one with `--profile experiments/<name>`.

| Profile | Variant of | Question |
|---|---|---|
| `automationbench-b4tf-f1` | `automationbench-gptoss-b4tf` | Follow-ups say they are an automated check (`followups.voice: check`); pre-registered in `docs/analysis/2026-11-05-followup-fixes-preregistration.md` |
| `automationbench-b4tf-f2` | `automationbench-gptoss-b4tf` | Follow-ups ask for the source before an action (`followups.evidence: on`); same pre-registration |
| `automationbench-b4tf-f12` | `automationbench-gptoss-b4tf` | Both of the above; same pre-registration |
| `automationbench-b4tf-remsys` | `automationbench-gptoss-b4tf` | Reminders in the system prompt (`notes.reminders: system`); 2026-11-06 setup audit |
| `automationbench-b4tf-briefmsg` | `automationbench-gptoss-b4tf` | The brief as a message (`notes.brief: message`); 2026-11-06 setup audit |
| `automationbench-gptoss-b4tf-list` | `automationbench-gptoss-b4tf` | Read every record at the start instead of keyword searches (`sources.listing: true`); pre-registered in `docs/analysis/2026-11-08-listing-preregistration.md` |
