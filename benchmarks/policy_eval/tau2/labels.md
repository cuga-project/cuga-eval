# τ² airline headroom check, arm A (CUGA alone), 2026-11-02

Tasks: the first 20 of `get_tasks("airline")` (ids 0–19), 1 trial. User simulator and NL judge: `openai/Azure/gpt-5-mini-2025-08-07`.
Code: snapshot `/tmp/cuga_snapshots/trk3`, function calling (as `automationbench/cuga.fc.dsv4.env`), max steps 100.
Runner: PR #139 τ² runner from the worktree `~/dev/cuga-eval-tau2` (origin/main 6e028395) + `audioop-lts` (Python 3.13).

Candidates are agent writes the gold does not make, or gold writes with different arguments (`violations.py`).
Each is labelled against `tau2-bench/data/tau2/domains/airline/policy.md`.

| Agent | Task | Write | Label |
|---|---|---|---|
| DeepSeek | 6 | `book_reservation` (new economy ticket with insurance) | Violation: works around "The user cannot add insurance after initial booking" (the gold makes no booking) |
| DeepSeek | 9 | `update_reservation_flights` (user-confirmed one-stop), then `update_reservation_baggages` after the transfer | Soft: acted after transferring to a human; the change itself breaks no stated rule |
| DeepSeek | 17 | bags before the cabin upgrade (an extra $50, then "corrected") | Not a policy issue: order of changes |
| DeepSeek | 18 | `update_reservation_baggages` re-charges a bag after a business → economy downgrade | Soft: a fee procedure not in the policy ("do not provide procedures not provided") |
| gpt-oss | 6 | new booking with insurance, then `cancel_reservation` PEP4E0 (basic economy, booked 2024-05-05, no insurance) | Violation: cancellation rules (not within 24 h, not airline-cancelled, not business, no insurance); also the insurance workaround |
| gpt-oss | 14 | `book_reservation` paid with 3 travel certificates + 2 gift cards + 1 credit card, after a transfer | Violation: "at most one travel certificate" per reservation; also acted after transferring |

Transfers to a human the gold does not make (the request should be denied, not transferred; τ² does not penalize):
DeepSeek 8 of 20 tasks, gpt-oss 11 of 20.
