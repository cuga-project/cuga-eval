# Problems across benchmarks, 2026-11-05: speaker notes

Deck: `docs/analysis/2026-11-05-problems-across-benchmarks-deck.html`. Keys: right and left arrows move, `F` is full screen.

Each example is used once and sits on its own policy type. The basic economy rule appears only on problem 6 and on the rule-list row of slide 18.

## Time plan (about 45 minutes, plus discussion)

| Part | Slides | Minutes |
|---|---|---|
| Where we start | 1–3 | 5 |
| Seven problems | 4–16 | 28 |
| The fix | 17–19 | 8 |
| Discussion | 19 or 17 | rest |

If time is short, show only the first slide of problems 3 and 5 and skip slides 9 and 13. Slides 20–21 are backup.

## What to say

**1. Top models fail.** These are the best public scores today. Each board has its own measure. Short policies are close to solved by top models. Long policies and large document sets are near half. The handbook board does not label its measure, and strict pass was 21.9% in June, so do not call this a clean trend.

**2. CUGA alone.** Same idea on our runs. Results move with the policy shape and the model. Each cell uses its own tasks and tool setup, and the scoring is ours, so compare loosely and do not compare with slide 1. The IT row is the same 10 tasks for all three models.

**3. Seven problems.** This is the map for the rest of the talk. A filled dot means we saw it in our runs. An empty dot means others report it or the task files show it. This is our reading, not a formal count. Evidence per cell is below.

**4. Problem 1, real case.** One new task, small model. Alone it scored 33% and 29% in the two runs. The rule was in mail and the agent never read it. On long handbooks, finding the procedure is not the weak part.

**5. Problem 1, answers.** 38 of 59 methods we reviewed work offline only, so a rule that arrives during work is outside most of the literature. +18.9 is significant (24 tasks better, 6 worse), but it measures the whole system, not search alone. On long documents, better search raised checklist recall offline from 24% to 47% but gave no gain live: strong 39 → 32, small 20 → 19 of 51 items.

**6. Problem 2, real case.** The agent had the rule open and still acted. The notice came from another manager. Names in the benchmark are not real people.

**7. Problem 2, answers.** The +16.9 paper is from our group, so say it is not independent, and it measures the whole harness, not the yes/no model alone. Most of our gain is the check, not the graph: 109 → 133 over plain text. The +25.5 is the latest version on 3 tasks we tuned on; all rounds together give +19 (219 → 283 of 336). With a small checker the gain is small: 2 better, 2 worse, 5 the same.

**8. Problem 3, real case.** The timer check failed in all 5 runs of the agent alone. An action check looks at actions; here there is no action. Up to 54 of 104 is a rough count: 27 need values in neither text, 17 are IDs or links, 6 are values from the task.

**9. Problem 3, answers.** Names alone give at most about +4 to +6. Both upper rows use grader answers, so they can never be in a product. The reminder rule passed the timer check in 4 of 4 runs, but the task still failed at 8 of 10 checks, and that task was used to fix the rule. Overall the effect is unknown: −4.9 against an earlier baseline, +1.0 and +1.4 against later runs on the same 20 tasks; it sent only 1 follow-up in those 20 runs. So required work is not solved. If asked: an older checklist is wired and is part of the +18.9 system; the new required-work design has a file format and validator, but nothing reads it at run time.

**10. Problem 4, real case.** The quote is the manual's text; the tracker's shorter note was "Check Roaming status (if user is abroad)". Same task with the step note passed. It found Data Roaming off and the customer turned it on. That is one good case. Over 40 tasks it could be chance.

**11. Problem 4, answers.** Published gains are large, but mostly on telecom, which says little about a new domain. Top public telecom scores are already high, so this matters most for smaller models. In our telecom runs the agent had the manual, not the benchmark's step workflow file.

**12. Problem 5, real cases.** Four parts of real policies, four different failures. This is the evidence for parsing by type. Say it plainly: today one build path reads every policy. It types each statement, not the policy as a whole.

**13. Problem 5, answers.** The engine did what the file says on every role and tool pair, so the errors come from reading the text. We stopped ToolGuard after step 1 on 30 of 42 tools; numbers cover the 21 finished tools.

**14. Problem 6, real case.** This is the same tracker that helped telecom. It helped a flow and hurt a rule list. The checklist number is rough: −13.2 against an earlier baseline, −6.9 against a later one, neither at the same time.

**15. Problem 6, answers.** Be careful here. On the same 31 new tasks the small agent gained 8.8 and the strong agent lost 5.8, and both could be chance. The strong agent's checks came from a small model, in this result and in the −7.8. With a strong checker it gained on handbook tasks, so the lesson is to match the checker to the agent, not simply to use less control. In the paper from our group, gain did not follow strength. The control levels are a hypothesis, and the switch is not built.

**16. Problem 7.** Say this openly: only one gain is proven on new tasks. The +13.8 came from comparing with a run from hours earlier. Same method twice differs on 19 of 35 tasks, so per-task noise is large.

**17. Where it stands.** Read only the status column. One proven, two promising, the rest designed or not proven.

**18. Parse by type.** This is the main change from how we work today. Only the rules-in-data route has evidence on new tasks. The rule-list route is not built; a policy file for airline exists since today, and nothing uses it yet. Role tables need one model call per row and only remind, so the engine is exact but the reading is not. Step 5 of the stabilization plan builds control levels and the rule-list route.

**19. Architecture.** Read left to right. Numbers on the boxes are the problems. Dashed boxes are not used at run time: route by type, required work, its check, and control level. The order of the checks and a swappable search are also not built: the check runs even after a hard rule has denied the action. The rest runs on a local branch. Four changes to CUGA are open for review, and #1107 has changes requested. The parts were measured separately; the whole design has never run as one system.

**20. Backup: stronger models.** The middle column is our reading. Law keeps logs, limits, an owner and a stop function whatever the model scores.

**21. Backup: sources.** Published numbers are the authors' or vendors' own.

## Evidence for the matrix (slide 3)

| Problem | Task set | Evidence | Source |
|---|---|---|---|
| 1 | Business rules | About 60% of runs open the rules app | `changes.md` 90 |
| 1 | Banking | 698 documents | `2026-10-20-policy-benchmarks.md` |
| 2 | Business rules | 19 of 64 runs break a rule with the rules shown | `ab-policy-types` result; `changes.md` 93 |
| 2 | Long handbook | 16 of 22 with the rule open | `changes.md` 100–102 |
| 2 | IT service | 11 blocks on failed saved runs | manager notes, slide 8 |
| 2 | Airline | 5% mid, 10% small runs break a rule | requirements tracker result |
| 2 | Banking | 83% of small-model failures | SOTA notes section 1 |
| 3 | Business rules | 4 of 5 mentions handled | pilot, 2026-10-31 |
| 3 | Long handbook | Required SOP step skipped: 5 items | `2026-11-02-overnight-log.md`, HANDBOOK step 1 |
| 3 | IT service | Up to 54 of 104 | `2026-11-02-overnight-log.md`, 10:40 |
| 3 | Banking | Must call `log_verification` | `2026-10-20-policy-examples.md` |
| 4 | Long handbook (○) | Ordered steps in the task files; the loop gain is on tuned tasks | `handbook-rounds` result |
| 4 | Telecom | 24 of 26 | `navigator_replay.py` result |
| 4 | Banking | "in the exact order listed" | `2026-10-20-policy-examples.md` |
| 5 | Business rules | One record per tool output | pilot, 2026-10-31 |
| 5 | Long handbook | Bulleted steps were not extracted at first | `handbook-rounds` result |
| 5 | IT service | 0 of 3 role rules | `changes.md` 105 |
| 5 | Telecom | Lists became procedures | `changes.md` 75 |
| 5 | Airline | Rule read without its exception | `changes.md` 87 |
| 5 | Banking | Contradictory documents | `2026-10-20-policy-examples.md` |
| 6 | Business rules | −5.8, rules broken 1 → 24 | `best_profiles.json` |
| 6 | Long handbook | −7.8 | `policy-gain-depends-on-model` result |
| 6 | IT service | −7 to −13; 20 of 93 | `changes.md` 114; manager notes |
| 6 | Airline | 17 → 11 of 20 | `changes.md` 87 |
| 6 | Multi-app | 19 fixed, 5 broken | `benchmarks/appworld/parallel_runs/20261014_201432` and `_201614` |
| 7 | Business rules, handbook, IT service, telecom | See slide 16 | `changes.md`; research report |
| 7 | Airline | One run per task on a test set now seen | `changes.md` 87 |
| 7 | Multi-app | Guidance written from the same tasks | SOTA notes section 1 |
| 7 | Banking (○) | Known grading issues | `2026-10-20-policy-benchmarks.md` |

## The timer task (slide 8)

Task `3e736be9`, `benchmarks/enterpriseops_gym/results`. Check `SLA paused`, DeepSeek-V4-Pro.

| Setup | Runs | Passed |
|---|---|---|
| Agent alone (`ds1u`, `ds4uA`, `itn_A`, `ito_A`, `itp_A`; `ds2u` reuses the `ds1u` run) | 5 | 0 |
| With the reminder rule (`ds2u` B, `ds4uB`, `ds4unb`, `itv2u`) | 4 | 4 |

The task still failed at 8 of 10 checks in those 4 runs. It was used to fix the rule (`changes.md` 47). The −4.9 overall is against an earlier baseline (`2026-11-02-overnight-log.md`); a recount on the same 20 tasks against later runs gives +1.0 (`ito_A`) and +1.4 (`itp_A`).

## Plain terms and their internal names

| On the slide | Internal name |
|---|---|
| Full system | B4T-F |
| Step tracker | SOP tracker |
| Step-by-step loop | SOP loop + procedure guide |
| Check before each action, strong checker | must-not write gate (`store_gate.py`) |
| Check of open steps at hand-off | SOP navigator |
| Required work | obligations |
| "When X, do Y" reminder | duty rule |
| Paper from our group | JevAct, arXiv 2610.38620 (lists a member of our team as author) |
| Yes/no model | Kev-4B |
| New tasks | held-out |
| Tasks we tuned on | in-sample |
| Passing all 3 or 4 runs | pass^3, pass^4 |
| Business rules, long handbook, IT service, telecom, airline, multi-app | AutomationBench, HANDBOOK.md, EnterpriseOps-Gym ITSM, τ² telecom, τ² airline, AppWorld |
