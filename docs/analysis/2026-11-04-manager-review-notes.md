# Manager review, 2026-11-04: speaker notes

Deck: `docs/analysis/2026-11-04-manager-review-deck.html`. Keys: right and left arrows move, `F` is full screen.

## Time plan (60 minutes)

| Part | Slides | Minutes |
|---|---|---|
| 1 Why it is hard | 1–5 | 6 |
| 2 How the methods work, with real cases | 6–20 | 24 |
| 3 What we measured | 21–28 | 9 |
| 4 The design | 29–33 | 6 |
| 5 Plan and help | 34–38 | 5 |
| Discussion and decisions | back to 38 | 10 |

If time is short, skip slides 18, 26 and 31 first. Slides 39–42 are backup.

## What to say

### Part 1: Why it is hard

**Slide 1. No single method fits every case.**
We took the published method families from the October deck and tested them on CUGA. The proven gain is the small model with the full policy system: 23.8% to 42.7% on 35 new tasks, with 24 tasks better and 6 worse. A check before each action gave a strong model +25, but only on 3 tasks we tuned on, and the same full policy system cost a strong model about 6 points, so we need one design that combines the parts that worked.

**Slide 2. The hour.**
Last time we reviewed the published work. Today I show how each method works, what we measured on CUGA, the design that came out of it, and where we need help. I keep 12 minutes for decisions.

**Slide 3. Top models still fail these tasks.**
These are the best published results. Each task set has its own measure, so compare them only loosely. On business-rule tasks, one broken rule scores the whole task zero.

**Slide 4. Four shapes.**
This is why one method does not fit all. The same policy system meets long documents, rules hidden in emails and sheets, step-by-step manuals and short rule lists. The airline example comes back on the next slides.

**Slide 5. Four real violations.**
These are real CUGA runs without any policy checks, so the problem is concrete. In the HR case, the notice came from another manager, and the rule needs written authorization from two named people. The same mistake happened in every run without a check. I will come back to the HR and payment cases.

### Part 2: How the methods work, with real cases

**Slide 6. When each method acts.**
These are the October families, placed by the moment they act: before the run, while the agent reads, when it acts, and at the end of the task. The next slides take them in this order, each with a real case. We did not test the two other families, security by design and training the model.

**Slide 7. Compile rules.**
A model reads the policy once and writes a rule that code runs. The answer is cheap and the same every time. Our best rule set caught 104 of 182 rule-breaking tests with 1 wrong block in 165 allowed tests. The rest needs someone to read meaning. We also tried the first step of ToolGuard: the same catches as ours (43 of 54), with about 3 times the false flags (34 vs 12 of 49), so we dropped it.

**Slide 8. Real rules and real blocks.**
These come from decision tests on one IT service policy. The mid model wrote the tests from the policy text without seeing our rules. Each row shows the policy text, the action and the exact answer from the code. Over the whole test set: 104 of 182 rule-breaking cases caught (84 by rules, 20 by the tool schema), 1 wrong block in 165 allowed cases. On 182 saved runs, the rules gave 11 blocks on failed runs and 2 on passed runs.

**Slide 9. Policy as text.**
This is the default, and the agent decides alone. It helped the small model, 30.0% to 45.6%, but that guidance was written from the same tasks, so it is not a clean result. Parlant's numbers are from its own test suite.

**Slide 10. Procedure graphs.**
The manual becomes steps with branches. The published gains are large, but they are the authors' numbers on flow-type tasks. On CUGA, giving the agent the SOP as a graph it can query gave no gain on the one task we tried: the agent already had the knowledge. The step tracker helped telecom and hurt airline.

**Slide 11. How the agent queried the SOP.**
This is a real run. The graph has procedures, templates and must-not rules, and the agent calls it through tools. It asked for procedure 12.1 and got the rule back in text. Later it acted against that rule. The score stayed at 16 of 22 in all 3 runs with the queries and all 3 runs without. This is the evidence for "knowledge alone does not change decisions".

**Slide 12. The step tracker on telecom.**
A small model reads the SOP and the conversation before each agent reply and writes this note. It only reminds; it never blocks. Same task, same model: without the note, the agent tried many fixes, never mentioned roaming and transferred the customer. With the note, it found the toggle. This is one good case: over all 40 tasks it was 9 better, 3 worse, which could be chance.

**Slide 13. The step tracker on airline rules.**
This is the same tracker on a policy that is a list of rules. It turned a rule into a pending check and did not show the exception on a nearby line of the same policy. The agent refused. Alone, the agent changed the cabin, the passenger and the bags, and passed. Over 20 tasks: 17 to 11 passed, 0 better, 6 worse, which is significant. This is why the design routes by policy shape.

**Slide 14. Runtime monitors.**
A fixed layer sits between the agent and its tools and no model decides. Cedar did exactly what the rule file said, 372 of 372. The errors came from reading the text into rules: the automatic build missed the 3 permission rules that the careful rule file has.

**Slide 15. A role table row becomes a rule.**
One model call reads a table row and lists the write tools it allows. Code then writes the Cedar rule. The engine was exact: 372 of 372. But the IT service graders expect managers to update records that the table forbids. As a block, this hit 20 of 93 passed runs. No engine can settle that, so role rules only remind until the policy owner answers.

**Slide 16. Model checkers.**
A second model reads the action, the policy and the data, and can block. This gave our largest gain, with a strong model as the checker. In the first pilot, all 5 blocks were wrong because the checker invented a hold code, so a block now needs a quote from the case data.

**Slide 17. The real block message.**
The agent saw exactly this text as the tool error. The evidence must be a quote from the case data, not from the SOP. In 2 of 3 runs the ticket was created before the block came on the next action, so this check is not perfect. After the block, the agent stopped and asked the two people for authorization. Names in this text are from the benchmark task; they are not real people.

**Slide 18. Narrow questions.**
Instead of asking a model "is this action fine?", code asks one narrow question and takes the decision itself. The published method is JevAct, and the small model is Kev-4B. The cost is about $0.000002 per question. Against the same system without it, broken rules fell from 44 to 34 with about the same score (41.4% vs 42.7%). CUGA alone broke 37.

**Slide 19. After the run.**
Checking the finished work can catch what never happened, but it depends on precision. A second model reading a whole run was right only 17.5% to 38.5% of the time. Wrong items make the agent change correct work. This led to required work, slide 32.

**Slide 20. Each method has a role.**
Each family did one job well, so each one got a role instead of one winner. Compiled rules catch 97 to 104 of 182 rule-breaking test cases, which is about half, so the other half needs a model. The "no gain" for graphs was measured on one task (16 of 22 in every run), and wrong items at the end of a run cost 7 to 13 points on IT service tasks and 10 of 153 items on long handbook tasks. The IT number is rough: −13.2 against a baseline from earlier that day, −6.9 against one from later that day; neither ran at the same time.

### Part 3: What we measured

**Slide 21. Task sets and models.**
Each task set has a different policy shape. No method ran on all three models, so some cells in the design are still a hypothesis.

**Slide 22. The same method helps one model and hurts another.**
Every bar is against the same model alone: solid bars are new tasks, light bars are tasks we tuned on or had seen. The telecom bar is light because we had looked at that task set before freezing the design. The step tracker went from 51 to 61 of 80 runs on telecom, but from 17 to 11 of 20 on airline, because it showed rules without their exceptions. The step-by-step loop's −7.8 comes from 2 rounds on the 3 tasks: its questions came from a small model, which marked real work as an exception, so the strong agent skipped that work.

**Slide 23. Small model.**
This is the proven result. On the first set, the stricter score that counts a broken rule as zero also went from 12.9% to 31.8%. The second set points the same way, but with 31 tasks it could be chance.

**Slide 24. The $32,500 payment.**
This is one new task with the small model, and it shows all the parts together. Search found the CFO's rules in mail. Alone, the agent never read them. With the system, it saw the rule and skipped the payment. The check also blocked an email, with this text: "POLICY CHECK: gmail_send_email was not called. It may break these rules". That check was wrong: it demanded the [PRIORITY] flag for 60 days late on an invoice only 23 days late (today in the task is 2026-02-07, due date 2026-01-15). It did no harm here, and it is one reason the design computes dates in code. Alone scored 33% and 29% in the two runs; with the system 100% in both.

**Slide 25. Real mistakes.**
These are real cases. In the HR task, the same trap failed in all 8 runs without the check: the agent had the rule open and offboarded anyway. With the check, it was blocked and it stopped. The medical date was computed by code, because both the agent and the checker got it wrong by hand. These numbers are the latest version. Counting all rounds of the check, it is 219 to 283 of 336 items, +19 points (our recount of changes 100–102). This is on tasks we tuned on, so it needs new tasks.

**Slide 26. Check vs knowledge.**
The check over the plain SOP gave most of the gain, so the graph is not the main part. The baselines differ between rounds (100 and 109), so compare these only roughly. The same check with a small model as checker gave no real gain: 2 better, 2 worse, 5 the same.

**Slide 27. Three harms.**
Each harm is measured. The −30 is significant. For the strong model, the −5.8 on score alone could be chance (8 better, 13 worse), but rules broken went from 1 to 24. Example: on one training task, alone it passed every check; with the system it emailed 2 people who should get no email and used the wrong session date. The checklist harm is rough, because no baseline ran at the same time. With only missing items, at the same time, the result is +1.0. These results set the rules of the design.

**Slide 28. Five lessons.**
The +25 is the check together with the procedure graph; the graph alone gave no gain on the one task we tried, and the check over the raw text alone went from 109 to 133 of 153, so most of the gain is the check. With a small model as the checker, the same setup went only from 49 to 54 of 153. "372 of 372" means the rule engine's decisions equal the rule file on every role and tool pair; "missed 3 of 3" means the automatic build found none of the 3 role rules in the careful rule file that Claude wrote.

### Part 4: The design

**Slide 29. Three checks.**
Read the diagram left to right: policies are built into one policy file, or found during work; three checks decide; CUGA acts. Dashed blue boxes are new in the latest plan. Numbers if asked: hard rules gave 1 wrong block in 165 test cases; the judgment check took 100 to 139 of 153 items on 3 tuned tasks; required work is designed, not yet built. This slide assumes a good policy file, built once by Claude for now; rules found during work apply only in that session, and a rule from an untrusted source cannot change a trusted rule. The 165 test cases are allowed actions on one IT service policy, written by the mid model from the policy text without seeing our rules. Agent strength sets how much of this control we turn on.

**Slide 30. One real case.**
This is the HR case from slide 25. The block and the agent's reaction happened in our runs (slide 17). The hard-rule step and the required-work step show how the design would handle the same case; they did not run in that test. The last box matters: it never asks for work that was blocked, because a general "do every output" turn once made an agent submit work that was on hold.

**Slide 31. Exact values.**
Naming what failed gives about +4 to +6. Adding the expected value gives much more. Both of those bars use grader answers to find what failed, so they are upper limits and can never be in a product. Our own checklist reached only +3.5 and +1.0. This is why required work carries values with a known source.

**Slide 32. Required work.**
A check at an action cannot see work that never happened. Each item says what must exist, where it comes from and how code recognizes it. We test on saved runs first, and an item goes live only with false alarms at most 10% and catches at least 30%. With names only, expect at most about +4 to +6 points; anything above that depends on how many values we can derive.

**Slide 33. Control levels.**
This follows the lesson that a strong agent needs less control. Hard rules hold at levels 1 to 3. Risky actions get level 3 checks with any model. The defaults are a hypothesis, and the level switch is not built yet.

### Part 5: Plan and help

**Slide 34. What is proven.**
Only the small model gain is proven: +18.9 on 35 tasks. The second set of 31 new tasks went the same way, +8.8 with 14 tasks better and 6 worse, but that could be chance, as could telecom with 9 tasks better and 3 worse. The +25 needs the unseen handbook tasks before we can call it proven.

**Slide 35. Plan.**
No new experiments until the base is stable. Step 0 is in progress. The plan runs only code tests, checks on saved runs and 1-task test runs, for at most $25. Slide 42 lists the ten checks if asked.

**Slide 36. Next questions.**
This is a proposal. We decide the list when the base is stable. Question 1 is the most important, and it needs the unseen tasks from Surge.

**Slide 37. Three work areas, 3 people for 1 month.**
The architecture is the same as slide 29, colored by work area: blue is proof, brown is product, dark grey is policies, and light boxes need no extra people. The estimate is 3 people for 1 month. One person covers policies today; proof and product need help. Proof means showing the gains hold on new tasks. Product means moving the policy layer from a local branch into CUGA. The 1-month figure is an estimate, not a measured number.

**Slide 38. Four decisions.**
First, the stability work runs no new experiments: only unit tests, checks on saved runs and 1-task test runs, for at most $25. Second, the small model as checker gave 2 runs better, 2 worse and 5 the same, so we ask to allow a stronger checker for a small agent, which changes the earlier "small open models only" decision. Third, we have only 3 public handbook tasks, and we have a short draft request to Surge, for evaluation use only.

### Backup (show only if asked)

**Slide 39. Test rules.**
Most of these rules exist because a result turned out to be wrong. The +13.8 went away when both setups ran at the same time. Counting per task changed a telecom result from looking significant to could be chance. Choosing the best round would have overstated the gain: +20.3 pooled to +14.2.

**Slide 40. Routes.**
This brings back the four shapes from slide 4. Only the "rules in data" route has evidence on new tasks. The rule-list route is not built.

**Slide 41. Changes to CUGA.**
These four changes are the part of the work that is already public, and all four are waiting for review. The first one is the base for every policy check.

**Slide 42. Ten checks.**
Use it if asked what "stable" means. These are G1 to G10 in the plan.

## Plain terms and their internal names

| On the slide | Internal name | Source |
|---|---|---|
| full policy system | B4T-F | `changes.md` 91, 93, 111; `best_profiles.json` |
| check before each action, judgment check | write gate, must-not gate (GW = graph tools + gate; GR = gate over raw SOP) | `changes.md` 99–103, 110 |
| checker, model checker | verifier, gate model | `changes.md` 99, 110; design section 6 |
| new tasks | held-out | `changes.md` 87, 93, 111 |
| tasks we tuned on, tuned | in-sample | `changes.md` 102, 110; `best_profiles.json` |
| significant | p < 0.05, sign test per task (+18.9: p = 0.001) | `changes.md` 93 |
| could be chance | p ≥ 0.05 (+8.8: p = 0.115; +12.5: p = 0.146) | `changes.md` 111; `best_profiles.json` |
| small model | gpt-oss-120b | `best_profiles.json` |
| mid model | DeepSeek-V4-Pro | `best_profiles.json` |
| strong model | Gemini 3.8 Flash | `best_profiles.json` |
| business-rule tasks | AutomationBench | `changes.md` 93, 111 |
| second set | AutomationBench held-out2 (`policy_types_holdout2.json`) | `changes.md` 111; `best_profiles.json` |
| long handbook tasks | HANDBOOK, 3 public tasks (Crestwood, CareIG, Vanguard) | `changes.md` 102, 110 |
| telecom support tasks | τ² Telecom | `changes.md` 86; `best_profiles.json` |
| airline rule tasks | τ² airline | `changes.md` 87 |
| IT service tasks | ITSM | `changes.md` 112–118 |
| step tracker | SOP tracker (T) | `changes.md` 86, 87 |
| step-by-step loop | SOP loop + procedure guide (L) | `best_profiles.json`; design section 8 |
| required work | obligations, obligation ledger | design section 5 |
| hard rules, judgment rules | rule classes | design section 4 |
| policy file | policy package | design section 4 |
| rules found during work | online intake and discovery, session overlay | design sections 4, 8 |
| how much control | control levels 0–3 | design section 7 |
| rule engine | Cedar | `changes.md` 112 |
| role rules | `role_permission` rules | `changes.md` 105 |
| 3 of 3 permission rules | role rules in the gold build, written by Claude; the automatic pipeline had 0 before the repair | `changes.md` 105; research notes section 3 |
| points | percentage points of partial score or items passed, against CUGA alone (A, A-F) | `changes.md` 93, 102, 111 |

Design = `docs/superpowers/specs/2026-11-04-policy-system-design.md`. Research notes = `docs/analysis/2026-11-04-graph-and-rule-testing-research.md`. `changes.md` and `best_profiles.json` are in `benchmarks/policy_eval/`.


**New diagram terms and their internal names**

| On the slide | Internal name |
|---|---|
| Offline build | Claude skill (`skill/SKILL.md`), later `builder.py` + `procedure_compiler.py` |
| Found during work | online intake (`intake.py`) |
| Search for rules | policy discovery |
| One policy file | policy package (design section 4) |
| Required work | obligations (design section 5) |
| Priorities | `authority_rank`, `effective_date`, priority classes, policy questions |
| Find the procedure | router and expander (design section 11) |
| Yes/no model, narrow questions | Kev-4B (`decisions.py`); published method: JevAct |
| HR, Medical, Insurance tasks | Crestwood, CareIG, Vanguard |
| Multi-app tasks | AppWorld (`docs/analysis/2026-10-15-playbooks-gpt-oss.html`) |
| Business-rule, banking knowledge, enterprise operations and long handbook leaderboards | AutomationBench-AA, τ³ banking_knowledge, EnterpriseOps-Gym, HANDBOOK.md (`2026-10-20-policy-benchmarks.md`) |
| Strong checker | judgment gate (`store_gate.py`) |
| Agent steps | CUGA lifecycle hooks |
| Guides | procedure guide, SOP loop, SOP tracker, navigator |
| One configuration | policy config (`policy_config.py`) |
| Control level | level switch (`levels.py`) |
| Tests on new tasks | one runner (`policy_eval/harness/`), replay on saved runs, held-out sets |

## Likely questions

**What is in each work area?**

| Area | Specific work | Where it is in the plan or design |
|---|---|---|
| Proof (needs help) | Test design and statistics for new-task runs; best control level per model | Design section 7; after the stability gate |
| Proof | Stronger checker for a small agent | Design section 14, decision 1 |
| Proof | Accuracy bar for required-work follow-ups (false alarms ≤ 10%, catches ≥ 30%) | Plan Task 4.3 |
| Proof | A person reviews rule labels: today no person has reviewed the reference rules or the decision tests | `gold/README.md`; plan Task 3.2 |
| Product (needs help) | Review and move the runtime, one configuration and one way to run into CUGA | Plan Tasks 2.1–2.3, 5.1 |
| Product | Audit log with rule, evidence and version | Plan Task 2.4 |
| Product | Automatic build of the policy file, to replace the Claude skill | Plan Tasks 3.1, 3.5 |
| Policies (covered) | Policy files for all task sets; airline and retail have none yet | Plan Tasks 3.3, 3.4 |
| Policies | Required-work check | Plan Tasks 4.1–4.3 |
| Policies | Rule lists with their exceptions | Plan Task 5.3 |

**How firm is 3 people for 1 month?** It is an estimate, not a measured number. Check it after the first week.


**What exactly is in the "full policy system"?**
Four parts on top of the policy layer:
- It finds rules in the business data.
- When two rules conflict, the newer rule wins.
- A small yes/no model checks each write.
- A checklist of required work is checked at the end.

(`changes.md` 90, 91, 93.)

**Why is the +25 not proven?**
It is 3 public tasks, and we tuned on them. Claude built the graphs by hand from these SOPs, and we added the date windows, the data window and the attached global rules while looking at these tasks. It was better in 9 of 9 comparisons, 100 to 139 of 153, but it needs tasks we have not seen. (`changes.md` 102.)

**Is building the policy file really solved?**
Yes, as a working assumption: we do this job with Claude for now, and the research question is the runtime method. One caveat: the IT service tasks' graders expect managers to update records that the policy's own role table forbids. When role rules could block, 20 of 93 passed runs got a block, so role rules only remind until the policy owner decides. (Design sections 1 and 14; `changes.md` 114; research notes section 3.)

**Why not use GraphRAG or ToolGuard?**
GraphRAG tools build graphs of entities and relations; none models step order, conditions or exceptions. ToolGuard's first step gave the same catches as ours (43 of 54) with 3 times the false flags, 34 vs 12 of 49. Its second step was not run. We stopped after 30 of 42 tools. (Research notes sections 1 and 3; `changes.md` 115.)

**What does "+4 to +6 vs +16 to +34" mean?**
+4 to +6 is telling the agent which check failed: +6.4 on business-rule tasks and +3.9 on IT service tasks. +16 to +34 is also giving the expected value: +34.1 and +15.9. The second number used grader answers, so it is an upper bound, not a forecast. (Overnight log, "Names-only oracle".)

**Is the −6 significant?** (added: the sources do not state this directly)
No. On score alone it could be chance: 8 tasks better, 13 worse, sign test about p = 0.38 in a recount of the result files. The stronger sign is rules broken, 24 vs 1 (report on the result files), and the score that counts a broken rule as zero fell 17.3 points. The −30 on airline is significant (p = 0.031). (`best_profiles.json`; design section 2; `automationbench/results/pg_*`.)

**Were the telecom tasks really new?** (added: `best_profiles.json` differs from the slide label)
Not fully. They were not used to tune the method, but `best_profiles.json` says the split was seen before the method was frozen. This is one more reason the slide lists it as "Promising".
