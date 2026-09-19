# RailAccess AI — Execution Plan

## Mission

Build a hosted decision-support tool for NEBULA X 2026 Problem Statement 1, Railway Track Access Optimisation. The tool must decide who gets access, on which weeks and nights, and at which possession locations for the dual-line Line Alpha / Line Beta network. It must schedule the complete workload, respect all safety and operating rules, explain the result, and support disruption re-planning.

The official source of truth is [`PS1_README.md`](PS1_README.md). Do not replace its rules with generic maintenance-scheduling assumptions. The reference validator's result is the final authority for competition feasibility and scoring; our own validator is the fast, deterministic development and user-facing preflight validator.

## Official contract

- Import the eight instance CSVs: `01_LINES`, `02_STATIONS`, `03_SECTORS`, `04_LOCATION_SUPPLY`, `05_BUFFER_LOCATION`, `06_PARAMETERS`, `07_PROJECT_DETAILS`, and `08_ACTIVITY_DETAILS`.
- Schedule 100% of every activity's `total_accesses`. Never drop, omit, or silently truncate an activity.
- Produce exactly three files per scenario: `SCHEDULE_ACCESS.csv`, `SCHEDULE_OCCUPANCY.csv`, and `RESULTS.csv`.
- Run Scenarios A, B, and C independently. A `RESULTS.csv` must contain only one scenario.
- `SCHEDULE_ACCESS.csv` columns: `activity_id,access_seq,week,eclo,access_night`.
- `SCHEDULE_OCCUPANCY.csv` columns: `activity_id,week,location_id,co_share_group`.
- `RESULTS.csv` columns: `scenario,contract_number,simulated_completion_date,overrun_days`.
- The hosted web app must accept an undisclosed eight-CSV instance, run the solver, show validation and score evidence, and export the three files for the selected scenario.
- Every candidate must pass our validator before it is shown as feasible. Where the organiser/reference validator is available, a candidate is competition-feasible only after it has zero hard violations there too.

## PS1 domain facts

- This is a discrete planning problem in weeks and `access_night` slots, not continuous train timetabling. Use integer/binary assignment decisions.
- Each line has 10 stations: eight exclusive stations plus interchange hubs `H01` and `H02`. Work can occupy tunnel sectors (`SEC`) and platform sectors (`PLAT`) on either bound (`EB`/`WB`).
- A working section from `start_location_id` to `end_location_id` must book every required tunnel and platform location between book-in and book-out.
- In-house maintenance has priority and consumes the supply represented in `LOCATION_SUPPLY`; the scheduler allocates the remaining supply to contracted work.
- `Live`, `Non-live (Consist)`, and `Non-live (Others)` are work natures. Only `Live` and `Non-live (Consist)` carry exclusion buffers. `Non-live (Others)` carries no buffer.
- `Live` closure mirrors to the opposite bound. Only `Live` also crosses the interchange exception: a Live closure affecting `H01_H02` on one line closes the other line's `H01_H02` tunnel and the relevant `H01`/`H02` platforms. `PC`, `PM`, and `C` do not otherwise cross lines there.
- `PM` is a sole possession. A legal possession is one `PM` alone, one `PC` with up to three `C`, or up to four `C`. Co-sharing is valid only when activities share the same `(location_id, week, co_share_group)`.
- Same-group co-sharing is one possession and is exempt from buffers between its members. Different groups at the same location/week are separate possessions on separate nights and normal buffers apply.
- Standard access yields 1.0 work unit. `ECLO=1` yields 1.5 work units. ECLO is early closure / late opening, not a staffing or electrical-operator resource.
- `PROJECT_DETAILS.number_of_maximum_access_per_week` is the per-contract weekly cap on distinct `access_night` values. It is 2 for Live contracts and 3 for other contracts in the published setup, with the value fixed across the horizon.
- Workfronts limit the number of distinct activities of a contract/type that may use the same `access_night`. Predecessors are finish-to-start with zero lag in weeks: a successor must start in a strictly later week than the predecessor's last scheduled access week.
- `contract_priority` determines the overrun band: 1 → 100, 2 → 10, 3 → 1. `activity_priority` only nudges within that band: priority 1 → +0.3, priority 2 → +0.2, priority 3 → +0.0.

## Non-negotiable hard rules

1. **Workload conservation:** every activity is scheduled and its nightly yields sum to at least `total_accesses`.
2. **Planned start:** no activity starts before its `planned_start_date` / planned start week.
3. **Precedence:** predecessor finish-to-start ordering is enforced across contracts as well as within a contract; cycles are invalid input.
4. **Closures and buffers:** occupied locations close for the relevant night; buffers are expanded from `05_BUFFER_LOCATION`; buffers do not overlap incompatible possessions.
5. **Live mirroring and interchange:** apply opposite-bound mirroring and the Live-only H01–H02 cross-line exception exactly.
6. **Locations and legal mixes:** enforce location capacity and only the published PM/PC/C possession mixes.
7. **Co-sharing:** allow buffer exemption only for activities in the same legal possession group at the same location/week.
8. **Weekly allocation:** enforce the contract/type cap on distinct `access_night` values per week.
9. **Workfronts:** enforce concurrent activity limits per contract/type/night.
10. **Scenario rules:** enforce each scenario's ECLO, capacity, date, and ECLO-window restrictions below.

Never call a schedule feasible because it has a good objective score. Hard violations reject the candidate.

## Scenarios and exact objectives

All scores are penalties; lower is better.

### Scenario A — strict supply, flexible schedule

- `LOCATION_SUPPLY` capacity is rigid. Any excess capacity is a hard violation.
- ECLO is hard-forbidden. Every access must have `eclo=0`.
- Planned completion dates are flexible. Minimise priority-weighted overrun:

  `Score_A = Σ(contract_weight[tier] × (1 + activity_priority_nudge) × overrun_days)`

- There is no ECLO or excess-access-night lever in A.

### Scenario B — strict schedule, flexible supply

- Every activity/contract must meet its `planned_completion_date`; overrun is a hard violation and therefore zero for a feasible B schedule.
- Excess access above nominal `LOCATION_SUPPLY` is soft-scored rather than hard-failed.
- ECLO is allowed and soft-scored.
- There is no Scenario C two-week ECLO-window restriction in B.
- `Score_B = 7 × excess_access_nights_total + 5 × eclo_nights_total`.

### Scenario C — balanced / elastic trade-off

- Both planned-date overrun and excess access are allowed only within the published limits.
- Up to one excess access-night per location-week is allowed as a soft-scored elasticity; excess beyond that is a hard capacity violation.
- ECLO is allowed, but every ECLO access affecting a line must lie in one continuous span of at most two calendar weeks for that line. Alpha and Beta choose windows independently. A cross-line Live activity must fit both windows.
- `Score_C = priority_weighted_overrun + 7 × excess_access_nights_total + 5 × eclo_nights_total`.

Do not invent weights, tune the published coefficients, or reinterpret `activity_priority` as the contract tier. `priority_overrun` reporting is grouped by contract priority, while the weighted score applies the activity-priority nudge within that contract tier.

## Canonical architecture

```text
React + TypeScript UI (Person 3)
            |
            v
FastAPI integration layer (shared; Person 4 owns the boundary)
  ├── eight-CSV import and schema errors
  ├── Person 1/2 solver and recovery service
  ├── Person 4 custom validator and score calculator
  ├── CSV export service
  └── grounded LLM tool handlers (Person 4)
            |
            v
Docker → Cloud Run
```

Recommended stack: Python 3.12, FastAPI, Pydantic, Pandas, OR-Tools CP-SAT, React + TypeScript + Vite, Tailwind/shadcn/ui, custom SVG/Gantt, and Recharts. Use one container and no persistence by default. Avoid GPUs, Kubernetes, BigQuery, microservices, vector databases, and invented crew/engineer allocation models.

## Solver design — Persons 1 and 2 jointly own all solver logic

CP-SAT is the only component allowed to choose the final schedule. The custom domain layer generates legal data and evidence; it must not independently accept a timetable that CP-SAT did not produce.

### Shared solver pipeline

1. Parse and cross-reference all eight CSVs with row/column-level errors.
2. Validate dates, IDs, predecessor graph, line topology, bounds, capacities, and required columns.
3. Expand each activity into required `SEC` and `PLAT` locations.
4. Compute buffers, Live mirrors, H01–H02 effects, interchange effects, and legal co-sharing possibilities.
5. Generate legal candidate placements for week, access night, ECLO state, possession group, and required locations.
6. Build one CP-SAT model per scenario with workload, planned-start, precedence, closures, buffers, capacity, legal mixes, co-sharing, weekly caps, workfronts, ECLO, and scenario-specific objective/limits.
7. Accept only `FEASIBLE` or `OPTIMAL` CP-SAT results. A time-limited `UNKNOWN` result is not a schedule.
8. Convert the model result into the canonical `Schedule`, run Person 4's validator, calculate the published score, and export only validated outputs.

### Recovery with locked work

- Convert confirmed placements into hard locks.
- Apply a validated supply reduction, urgent activity, or other `ScenarioChange`.
- Re-run the same scenario model with a secondary schedule-difference objective to minimise unnecessary movement after satisfying the official objective and all hard rules.
- Return a `ScheduleDiff` showing unchanged work, moved accesses, new delay, ECLO changes, capacity changes, and the change budget.
- Never use a soft penalty to conceal a hard-rule breach.

## Build order

### Phase 0 — team contract

- Read this file and `PS1_README.md` together.
- Record the canonical objects in `docs/decision-log.md`: `InputInstance`, `Placement`, `Schedule`, `ValidationReport`, `ScenarioChange`, and `ScheduleDiff`.
- Build `docs/rule-matrix.md`: official rule → input columns → derived state → validator tag → fixture → owner.
- Confirm the reference-validator command and public-instance baseline. If it is unavailable, record that limitation; Person 4's validator must still be deterministic and evidence-based.
- Freeze the API/data contract before large parallel changes. Semantic schema changes require Persons 1, 2, 3, and 4 to agree.

### Phase 1 — vertical feasibility slice

- Persons 1/2 implement import, topology expansion, a small CP-SAT model, canonical schedule conversion, and Scenario A feasibility.
- Person 4 implements the custom validator checks and structured report for one rule at a time.
- Person 3 builds the upload/run/result shell against versioned mock JSON.
- Generate the three required CSVs and validate them on the public instance as soon as possible.

### Phase 2 — complete solver

- Implement every hard rule and the exact Scenario A objective.
- Add Scenario B's zero-overrun restriction, excess-capacity scoring, and ECLO cost.
- Add Scenario C's one-excess-night allowance and two-week per-line ECLO window.
- Add recovery with locked work and minimal churn.
- Add fixtures and regression tests for every rule and all three scenarios.

### Phase 3 — controller product

- Person 3 completes the dark, high-contrast control-room UI: upload, scenario picker, run state, validation evidence, score breakdown, two-line topology/timeline, possession/co-share/buffer/Live/ECLO legend, hotspots, activity drill-down, recovery comparison, and downloads.
- Person 4 wires the API boundary, validator report, exports, and grounded LLM tools.
- Persons 1/2 supply stable schedule, explanation, hotspot, and diff schemas; the frontend never re-implements rail rules.

### Phase 4 — integration and deployment

- Run clean-machine smoke/E2E tests for hidden-instance upload.
- Package one Docker/Cloud Run service.
- Rehearse the public-instance A/B/C runs and the disruption demo.
- Complete the GitLab repository, hosted URL, public test outputs, three-minute video, and setup documentation.

## Team roles and decision ownership

The division is by decision ownership. Persons 1 and 2 together own the entire solver, including domain interpretation, CP-SAT modelling, objectives, schedules, and recovery. Person 3 does not encode rail rules in TypeScript. Person 4's validator diagnoses and rejects schedules but never becomes a second competing scheduler.

### Person 1 — solver domain and hard-constraint owner

**Human decision authority:** Translate PS1 into the canonical domain model and legal placement space, with Person 2 reviewing every semantic decision.

| Owns | Deliverables | Must decide with Person 2 |
| --- | --- | --- |
| Input/domain model | Pydantic models, eight-CSV parser, topology, station/sector expansion | Exact meaning of every input field and derived object |
| Safety state | Buffers, closures, Live mirrors, H01–H02 exception, location footprints | Closure precedence and buffer/co-sharing semantics |
| Legal placements | Candidate weeks, nights, ECLO eligibility, possession bundles, co-share groups | Representation used by CP-SAT |
| Solver fixtures | Minimal valid/invalid instances for each hard rule | Expected model behaviour and acceptance criteria |

### Person 2 — CP-SAT, objectives, and recovery owner

**Human decision authority:** Turn Person 1's legal domain representation into the single authoritative optimiser and implement all scenario trade-offs without changing PS1 weights.

| Owns | Deliverables | Must decide with Person 1 |
| --- | --- | --- |
| Primary model | CP-SAT variables, constraints, legal possession/co-sharing encoding | Complete hard-rule coverage |
| Scenario objectives | Exact A/B/C feasibility limits and published penalty formulas | Correct treatment of capacity, ECLO, dates, and priorities |
| Schedule output | `Schedule` conversion, workload accounting, status handling | No partial or silently truncated result |
| Recovery | Locked work, disruption re-plan, minimal-churn objective, `ScheduleDiff` | Definition of preserved work and change budget |

Persons 1 and 2 jointly sign off on solver feasibility, objective calculations, performance, and public-instance A/B/C results.

### Person 3 — frontend, UI/UX, and controller experience owner

**Human decision authority:** Decide what a 2AM works controller must see, understand, inspect, lock, change, and approve.

| Owns | Deliverables | Must decide before implementation |
| --- | --- | --- |
| User journey | Upload → scenario → run → validate → inspect → recover → export flow | Smallest trustworthy controller workflow |
| UI system | Design tokens, accessible contrast, colour/label grammar for Live, buffers, PM/PC/C, ECLO, delay, hotspots | Visual treatment and interaction states |
| Visualisation | Two-line schematic, linked week timeline, occupancy/co-sharing, validation facts, score breakdown | What evidence is shown at a glance |
| Recovery UX | Lock approved work, apply disruption preview, show before/after and change budget | What must be confirmed before re-planning |
| Demo assets | Landing screen, activity drill-down, video flow, before/after screenshot | First 20 seconds of the demo |

Build only against versioned API/mock `Schedule`, `ValidationReport`, and `ScheduleDiff` objects. Display validator facts and score components; never infer feasibility from a chart.

### Person 4 — custom validator and LLM/integration owner

**Human decision authority:** Make validation deterministic and evidence-based, and keep all LLM behaviour grounded, non-authoritative, and confirmed before changes.

| Owns | Deliverables | Must decide before implementation |
| --- | --- | --- |
| Custom validator | Rule-by-rule checks, hard-violation tags, pinpoint details, scenario limits, score calculator | Mapping from PS1 rules to validator evidence |
| Output contract | CSV shape checks, `RESULTS.csv` checks, report schema, export adapter | What the UI may call feasible or downloadable |
| Integration boundary | FastAPI routes, upload orchestration, run status, errors, generated frontend client, Docker/Cloud Run glue | Timeouts, no-persistence behaviour, hidden-instance handling |
| Grounded LLM | Tool schemas and response templates for explanations, hotspots, what-if previews, handover briefs | Required evidence and confirmation points |
| Quality gates | Validator regression suite, API smoke/E2E tests, deploy checklist | When a release is demo-safe |

The custom validator is a deterministic checker, not a replacement scheduler. The LLM may explain validator/solver evidence or propose a structured change, but may not assign locations, weeks, access nights, ECLO, buffers, co-share groups, declare feasibility, or execute a schedule change without explicit user confirmation and a fresh solver/validator run.

## LLM scope

Implement only grounded, non-authoritative tools:

| Feature | LLM role | Deterministic guardrail |
| --- | --- | --- |
| Explain an activity/conflict | Turn evidence into plain English | `explain_activity()` returns rules, locations, score impact, and alternatives |
| Capacity-risk query | Summarise hotspots | `get_capacity_hotspots()` |
| What-if request | Convert text into a proposed structured change | Validate preview; require user confirmation; then `simulate_disruption()` runs CP-SAT and validation |
| Handover brief | Summarise a validated plan | `summarise_plan()` sees validated result JSON only |

Do not use the LLM for scheduling, feasibility declarations, rule interpretation, hidden state, or duration prediction.

## Product and demo priorities

The differentiator is a validated optimiser with a trustworthy controller experience. Prioritise feasibility before polish.

1. Upload eight CSVs and run Scenario C.
2. Show the schedule, zero hard violations, exact score components, and complete workload.
3. Inspect a Live H01–H02 closure and its mirrored/cross-line impact.
4. Show legal co-sharing resolving a bottleneck without pretending buffers disappear generally.
5. Reduce supply at a hotspot, lock approved work, and run recovery.
6. Compare original/recovered schedules: preserved work, changes, delay, ECLO, capacity, and score.
7. Ask the grounded copilot for a handover summary and export the validated three-file set.

## Integration rules and checkpoints

- The official specification takes precedence over implementation convenience. Mentor/reference-validator clarification takes precedence over an unresolved interpretation.
- Persons 1 and 2 approve semantic solver/schema changes; Person 3 consumes them; Person 4 owns the API and validation evidence.
- Every hard-rule implementation needs a fixture and a validator regression test.
- CP-SAT is the only final scheduler. The custom validator must never repair or rewrite a schedule.
- No UI or LLM component may call a schedule feasible without a current validation report.
- A `FEASIBLE` or `OPTIMAL` CP-SAT status is necessary but not sufficient; run the custom validator and, where available, the reference validator.
- At every integration checkpoint ask: do all activities have full workload, are all hard violations zero, did a schema change, can a teammate explain one decision from evidence, and can a clean machine run the app?

## Submission checklist

- [ ] Persons 1/2 produce complete public-instance schedules for A, B, and C.
- [ ] Custom validator reports zero hard violations for every submitted feasible schedule; reference-validator runs are recorded where available.
- [ ] Every activity receives its full `total_accesses`.
- [ ] Each scenario has exactly the three required CSV outputs with the published columns.
- [ ] Hosted app accepts a fresh hidden eight-CSV instance and exports results.
- [ ] UI shows schedule evidence, hard violations, score components, and recovery changes.
- [ ] Grounded LLM tools cannot mutate or declare feasibility without confirmation and re-validation.
- [ ] README documents setup, data handling, architecture, validation, and demo instructions.
- [ ] GitLab repository URL, hosted URL, three-minute video, public outputs, and ZIP/write-up are prepared.

## Current implementation status — 2026-09-19

This section records the current repository state and supersedes older phase/status language elsewhere in the repository. It does not supersede the official PS1 rules above.

### Solver implementation

- The OR-Tools CP-SAT solver is implemented in `backend/app/solver/cp_sat.py` and connected to the production FastAPI application in `backend/app/main.py`.
- The direct CLI is:

  `python -m app.solver.cp_sat --instance data/public-instance --scenario C --output solver_output/scenario_c --time-limit 120 --workers 8`

- CP-SAT decides access week, contract-local `access_night`, ECLO, completion, and exported occupancy groups. `UNKNOWN`, `INFEASIBLE`, and invalid post-solve schedules are rejected and are never exported.
- Workload is integer-scaled: standard access yields `2`, ECLO yields `3`, and each activity is constrained to deliver between `2 * total_accesses` and `2 * total_accesses + 1`. This permits only the unavoidable half-unit ECLO overshoot and prevents redundant access rows.
- Implemented hard constraints include planned start, at most one access per activity/week, cross-contract finish-to-start precedence, weekly access-night allocations, nightly workfronts, legal PM/PC/C mixes, derived route occupancy, buffer separation, Live mirroring, Live interchange effects, Scenario A ECLO/capacity policy, Scenario B planned-date policy, and Scenario C ECLO windows/capacity policy.
- The objective is lexicographic. The exact published score is integer-scaled and minimised first. Equal-score solutions then minimise recovery churn (when applicable), total accesses/possessions, and completion weeks. Published weights are unchanged.
- Recovery supply overrides are applied in both the solver and validator. Confirmed locked placements become hard constraints using their activity, sequence, week, access-night index, and ECLO value. `RunService` computes a `ScheduleDiff` after recovery.
- Current packing uses a conservative canonical possession strategy: activities sharing an occupied location/week are emitted in group `p1`, up to the legal four-member mix, while disjoint footprints whose derived closures touch are kept in different weeks. This avoids group-label symmetry and produces locally clean public schedules quickly.
- **Known solver limitation:** the canonical `p1` packing strategy does not yet explore the full legal space of multiple possession groups at one location/week. Consequently, Scenario B/C excess-capacity choices are not modelled generally, and a hidden instance that requires multiple groups could be falsely reported unsolved or receive a non-optimal score. Implementing efficient multi-possession packing without reintroducing prohibitive slot symmetry is the highest-priority remaining solver task.
- `FEASIBLE` solutions are accepted as the best solution found within the configured time limit, as allowed by the project contract. Current public scores are not proven global optima unless the CLI reports `OPTIMAL`.

### Validator implementation and corrected interpretation

- Deterministic local validation is implemented in `backend/app/validation/preflight.py`. It validates input references, exact output schemas, workload, start dates, precedence, topology, legal mixes, capacity, weekly allocation, workfronts, scenario ECLO/date policies, `RESULTS.csv`, and published score components.
- The official sample at `data/public-instance/sample-submission` is the local regression baseline. It currently reports **0 locally observable hard violations** and Scenario A score **48.3**.
- An earlier implementation incorrectly inferred cross-group concurrency from weekly occupancy rows and reported false-positive closure violations against the official sample. That inference was removed.
- `access_night` is a local accounting index for `(contract_number, activity_type, week)`, independent of location/sector. It must not be treated as a global physical-night identifier or forced to equal `co_share_group`. The official sample proves this: A003 and A007 share group `b1` at common locations in week 16 while using C001 access-night indices 3 and 1.
- Therefore the eight “co-shared activities have different `access_night`” issues reported by an external Claude review are **not** treated as violations. A temporary solver/validator constraint enforcing that assumption was removed and was never used to generate the retained outputs.
- The external Claude review also reported 113 closure conflicts using a strict inferred global-night/buffer model. Those findings are not locally authoritative because the three output CSVs do not expose global ordering for different possession groups and the model did not apply the published same-possession exemption in the same way as the sample. Do not add those conflicts as hard violations unless the organiser validator or a mentor confirms the missing timing semantics.
- The local validator derives base, buffer, mirrored, and interchange closure footprints for solver use, but it emits a warning rather than a hard decision for cross-group closure ordering. The organiser validator remains authoritative for this rule.
- Supplied `tested_data/scenario_a/result.txt` and `tested_data/scenario_c/result.txt` remain external calibration evidence. Tests assert that these traces are preserved and that the local validator does not pretend to reproduce unavailable global timing state.
- Organiser traces indicate that a Live H01–H02 isolation carries its configured buffer onto the other line around the interchange. `closure_locations()` and the solver include that conservative cross-line expansion. This interpretation remains pending direct organiser confirmation.
- Local reports always remain `unverified`; only an integrated organiser validator may set `verified` or declare competition feasibility.

### Current generated public outputs

The retained outputs are in `solver_output/scenario_a`, `solver_output/scenario_b`, and `solver_output/scenario_c`. All three contain exactly `SCHEDULE_ACCESS.csv`, `SCHEDULE_OCCUPANCY.csv`, and `RESULTS.csv` and currently pass all locally observable hard checks:

| Scenario | Local score | Access rows | Overrun days total | ECLO rows | Excess access-nights | Local hard violations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 131.6 | 192 | 42 | 0 | 0 | 0 |
| B | 50.0 | 187 | 0 | 10 | 0 | 0 |
| C | 44.5 | 190 | 21 | 4 | 0 | 0 |

These schedules were regenerated after the conservative Live interchange-buffer correction. They were not regenerated after removal of the temporary `access_night == co_share possession` experiment because that experiment was reverted and the current model again matches the model that produced these files.

### Test and verification status

- Current automated result: **28 tests passed** with `python -m pytest -q` and `PYTHONPATH=backend`.
- Python compilation succeeds with `python -m compileall -q backend`.
- The official organiser validator is not installed or callable in this workspace. The generated A/B/C outputs must be uploaded to it before any schedule is called competition-feasible.
- When organiser results arrive, preserve the raw report, compare every reported violation with the local evidence, and update the model only from confirmed semantics. Do not overfit inferred timing rules that make the published sample fail.
