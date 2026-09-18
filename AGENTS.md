# RailAccess AI — Execution Plan

## Mission

Build a hosted decision-support tool for NEBULA X 2026 Problem Statement 1, Railway Track Access Optimisation. The tool must decide who gets access, on which weeks and nights, and at which possession locations for the dual-line Line Alpha / Line Beta network. It must schedule the complete workload, respect all safety and operating rules, explain the result, and support disruption re-planning.

The official source of truth is [`PS1_README.md`](PS1_README.md). Do not replace its rules with generic maintenance-scheduling assumptions. The reference validator's result is the final authority for competition feasibility and scoring; our own validator is the fast, deterministic development and user-facing preflight validator.

## Current implementation workstream

The active coding task is **Scenario A only**: implement the shared, extensible CP-SAT scheduling model, with Scenario A's strict nominal supply, no-ECLO policy, complete workload, physical/safety/possession/allocation constraints, and priority-weighted planned-completion overrun objective. Scenario B and C policy behaviour must not be implemented yet, but the model must expose a central scenario-policy extension point so they can be added without duplicating the model.

The solver must use the existing domain/ingestion/export/preflight contracts, read the planning horizon from `06_PARAMETERS.csv`, generate deterministic three-file Scenario A output, and integrate with the existing backend adapter boundary. The organiser validator is not present as a runnable package in this repository; local preflight results remain unverified until that validator is run.

### Implementation progress

- Added `backend/app/solver/` with a central Scenario A policy, topology/footprint preprocessing, CP-SAT model, independent score helper, API adapter, and CLI.
- The shared model allocates complete standard-night workload, enforces planned starts, predecessor finish-to-start ordering, weekly allocation/workfront caps, legal PM/PC/C possession groups, strict nominal supply, and Scenario A's no-ECLO policy.
- Internal closure slots cover buffer, Live opposite-bound, and Live H01–H02 cross-line footprints while retaining the published output distinction between base occupancy rows and hidden closure state.
- Latest generated public run completed with `OPTIMAL` CP-SAT status, 54 activities, 192 access rows, 928 occupancy rows, 14 contract results, weighted score `32.2`, and zero local preflight hard violations. This is not organiser-validator success.
- Generated outputs are written to `sample_submission/scenario_a/`; organiser reference fixtures remain under `data/public-instance/sample-submission/`.
- The production FastAPI app now uses the solver adapter; the existing generic `RunService()` default remains injectable for tests and non-solver callers.
- Solver, ingestion, export, preflight, and API tests pass in the disposable environment. The full suite has one unrelated public-fixture checksum failure because the current files under `data/public-instance/` do not match their checked-in `manifest.json` hashes; no fixture files were changed.
- Cross-group buffer ordering remains a documented authority limitation because the published output has no global night identifier. The solver uses internal closure slots and local preflight still reports the schedule as unverified until the organiser validator runs.
- Scenario B/C, ECLO selection, recovery locks, and LLM behaviour remain intentionally unimplemented for this workstream.

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

## Person 4 implementation roadmap and current state

This is the delivery checklist for the custom-validator, integration, and grounded-LLM work. It distinguishes code that exists today from work that depends on the Person 1/2 solver. A locally clean preflight means only **local checks passed**; it must remain `unverified` until the organiser website has accepted the exact three exported files.

### Completed foundation

| Item | Status | Evidence / boundary |
| --- | --- | --- |
| Versioned contracts | Complete | `/api/v1` Pydantic request/response models implement `InputInstance`, `Schedule`, `ValidationReport`, `ScenarioChange`, and `ScheduleDiff`. API errors carry a request ID, stable code, message, and field errors. |
| Eight-file intake | Complete | `POST /api/v1/runs` accepts exactly the eight official filenames, parses the typed CSV records synchronously, and returns actionable package/schema errors. Uploaded inputs exist only in process memory after parsing. |
| Run lifecycle | Complete shell | In-memory runs support `accepted`, `running`, `succeeded`, `failed`, and `blocked`. With no solver connected, a valid upload becomes `blocked` with `solver_unavailable`; it never receives an invented schedule. |
| Solver integration seam | Complete for Scenario A | `RunService` passes one canonical `PreparedInstance`, scenario, and optional confirmed `ScenarioChange` to `CpSatSolverAdapter`, which returns the canonical schedule. Scenario B/C return `blocked/scenario_unavailable`; they never fall back to A. |
| Scenario A API run gate | Complete | Scenario A solver input/topology failures return `failed/solver_input_invalid`; unexpected solver errors return `failed/solver_failed`. A candidate is locally preflighted before success. Hard findings retain schedule/report evidence but return `failed/preflight_failed`, create no exports, and download attempts return `409/preflight_not_clean`. |
| Shared preprocessing handoff | Complete | `app/domain/preprocessing.py` is the sole owner of routes, base/closure footprints, buffers, Live mirroring, H01–H02 crossover, planning calendar, and cross-file checks. Each API run prepares once and shares that representation with CP-SAT and local preflight. |
| Export integration | Complete for locally clean candidates | Only a zero-hard-violation local candidate produces the exact three CSV filenames and official column order through the existing exporter. The files are retained only in a temporary run directory; a clean result is still `unverified`. |
| Local custom preflight | Partially complete | `python -m app.validation.preflight` loads the eight inputs and three outputs and checks schema, workload, start dates, precedence, route occupancy, legal mixes, allocation, workfronts, A/B/C capacity/ECLO policies, result consistency, and score diagnostics. It always reports `unverified`. |
| R4.2A local validator evidence and fixture coverage | Complete | Local findings now carry activity/location/week context plus optional co-share group, derived footprint, and input values. Regression fixtures cover locally observable footprints, mix, capacity, allocation, workfront, scenario policy, cross-line Live ECLO evidence, and published local score components. No finding uses an invented organiser tag. |
| R4.4 organiser submission evidence workflow | Complete | Locally clean succeeded runs create an ephemeral ZIP with the three official CSVs and immutable checksum manifest. Structured manual organiser metadata is downloadable as evidence JSON, never uploaded as files, never committed for hidden instances, and never changes `unverified`/`feasible=null`. |
| Closure derivation | Partially complete | Buffer, Live opposite-bound, and H01/H02 cross-line footprints are derived. Cross-group closure ordering cannot yet be proven from the published three-output CSVs because there is no global possession-time ordering; do not invent one. |
| API/UI development support | Complete foundation | Typed TypeScript client, versioned mock schedule/report/diff payloads, health evidence, and loading/blocked/failed/unverified states exist for Person 3. |
| Recovery orchestration | Complete shell | A recovery request requires an explicit confirmation timestamp, a matching base schedule/scenario, and passes supply overrides plus locked placement keys to the solver adapter. |
| Regression and container checks | Complete for Scenario A gate | Pytest covers upload failures, lifecycle states, real Scenario A solving, B/C unavailability, solver-preprocessing failures, preflight gating, exports, recovery handoff, validator truthfulness, and local rule fixtures. Docker builds, API health, and the preflight command run against the vendored public sample. |
| Documentation | Complete foundation | The README documents the local preflight command. `docs/rule-matrix.md` records which local rules are implemented, partial, or organiser-dependent. |

### Remaining implementation roadmap

#### R4.2B — Organiser evidence and closure-order completion

**Dependency:** the shared preprocessing handoff and organiser clarification/reference-validator observations.

- Replace the current closure-order warning with deterministic checks once the legal global possession-time representation is agreed or observed from the organiser validator.
- Confirm exact organiser rule tags, report fields, completion-date semantics, and score calculations using recorded website submissions.
- Keep R4.2A's local evidence fixtures as regression coverage; do not upgrade their local rule names into organiser tags.
- Add only the remaining organiser-dependent fixtures: globally ordered buffer/Live/H01-H02 collision examples, official report shapes/tags, and score examples confirmed by recorded organiser submissions.
- Keep local status separate from organiser status: `unverified` is not `verified`; only organiser evidence may set `feasible=true` for competition claims.

**Done when:** organiser evidence confirms the unresolved closure timing, report/tag, and score semantics, or each remaining ambiguity is explicitly documented as uncheckable from the output CSVs.

#### R4.3 — Extend the run gate beyond Scenario A

**Dependency:** Person 2's `SolverAdapter` implementation and Person 1's preprocessing output.

- Integrate Person 2's Scenario B and C policies through the same adapter; unsupported scenarios must remain blocked until then.
- Record CP-SAT status and diagnostics in the run evidence; accept only `FEASIBLE` or `OPTIMAL` candidates from the solver.
- Add bounded solver timeout, safe exception handling, temporary-export cleanup, and explicit expired/restarted-run behaviour.
- Keep the existing local-preflight gate: hard-invalid candidates are diagnostic-only, never ready submissions.

**Scenario A done:** a real public-instance Scenario A run travels through one API path and produces a locally clean, unverified export set with reproducible evidence.

**Done when:** the same truthful run/evidence/export behaviour is implemented for B and C with their approved policies and solver diagnostics.

#### R4.4 — Organiser-website evidence workflow (complete)

**Dependency:** a locally clean real schedule and the team's five-attempt upload budget.

- Create packages only with a full `RAILACCESS_BUILD_COMMIT`; each contains scenario, run/schedule IDs, input/output checksums, local preflight report, and timestamp.
- Keep ZIPs, evidence metadata, and downloaded JSON inside the live run's temporary workspace only. The playbook contains a public-fixture-only five-attempt template.
- Record only structured website metadata (attempt, time, reported outcome, reference, digest, note). Do not upload screenshots, store raw reports, automate the website, or change validator truthfulness.

**Complete:** R4.4 packages are reproducible within the live process and visibly separate local preflight from user-recorded organiser metadata. Official report parsing and verified status remain organiser-dependent work.

#### R4.5 — Finish recovery integration

**Dependency:** Person 2's locked-work recovery model and `ScheduleDiff` implementation; Person 3's confirmation UI.

- Pass only confirmed supply overrides and locked placement keys to the recovery solver.
- Validate the recovered result with the same preflight and organiser-evidence lifecycle as a baseline run.
- Return deterministic `ScheduleDiff`, score deltas, completion deltas, preserved-work counts, and change-budget evidence.
- Test rejected drafts, invalid locks, no-candidate bases, solver failures, and no workload loss during recovery.

**Done when:** a controller-confirmed disruption yields a fresh, evidence-backed recovered schedule without silently moving locked work.

#### R4.6 — Add grounded LLM tools last

**Dependency:** stable schedule, validator, score, hotspot, and recovery evidence.

- Implement read-only structured tools: `explain_activity`, `get_capacity_hotspots`, and `summarise_plan`.
- Implement a what-if parser that creates only a draft `ScenarioChange`; the user must confirm it before the recovery API runs.
- Ground every response in run evidence and include the schedule/validation version used.
- Add prompt/tool tests proving the LLM cannot assign placements, alter rail-rule facts, declare feasibility, or execute a change.

**Done when:** LLM output is useful explanation around deterministic evidence, never a second scheduler or validator.

**R4.6 implementation status:** The read-only evidence/API/UI and Vertex
adapter are implemented. Production deployment remains gated on creating the
dedicated Cloud Run service identity and performing the public-fixture-only
smoke test; no hidden instance is used for deployment validation.

#### R4.7 — Deploy and rehearse

**Dependency:** real Scenario A/B/C schedules, stable UI, and validator evidence workflow.

- Add Cloud Run configuration, environment validation, production request limits/timeouts, health/readiness checks, and temporary-file cleanup.
- Run clean-machine Docker and API smoke tests.
- Rehearse a hidden-instance upload without retaining its data, plus the public A/B/C and recovery demo flows.
- Produce a release checklist covering validator evidence, exports, API/UI versions, demo assets, and rollback-safe deployment.

**Done when:** one container can accept a fresh eight-CSV instance, run the real solver, display truthful evidence, and export the selected scenario safely.

#### R4.8 — Bonus: typed disruption request parser

**Dependency:** R4.5 recovery integration, stable `ScenarioChange` validation, and the grounded-tool safeguards in R4.6.

- Add an LLM-backed, schema-constrained endpoint that translates a controller's hand-typed disruption request into a **draft** `ScenarioChange` (for example, a reduced location supply, a requested lock, or a stated rationale).
- Show the parsed fields, assumptions, unresolved references, and validation errors to the controller before any action is available.
- Resolve locations, weeks, activities, and placement keys only against the selected run's deterministic input/schedule evidence; reject ambiguous or unknown references rather than guessing.
- Require the controller to review and explicitly confirm the resulting `ScenarioChange`; only the existing recovery endpoint may dispatch a solver run.
- Do not allow the LLM to assign a placement, alter priorities or railway rules, claim feasibility, bypass locked-work checks, or execute a change itself.
- Add adversarial tests for ambiguous language, invented IDs, conflicting requests, missing confirmation, and attempts to coerce a feasibility claim or direct schedule mutation.

**Done when:** a controller can type a disruption in plain language, receive a transparent draft change for review, and safely pass only an explicitly confirmed, deterministic `ScenarioChange` to recovery.

### Person 4 sequencing and dependencies

1. **Now:** maintain the Scenario A API/preflight tests, agree the shared preprocessing interface, and prepare the organiser-evidence manifest format.
2. **After Person 1/2 Scenario B/C:** extend the real-solver run/export gate to those scenarios.
3. **After first organiser evidence:** close validator ambiguities and complete rule fixtures.
4. **After A/B/C and recovery are stable:** add grounded LLM tools and Cloud Run deployment.

Person 4 does **not** build a competing preprocessor or scheduler. Person 4 integrates and validates the canonical output from Persons 1/2, gives Person 3 stable evidence, and preserves the distinction between local preflight and organiser verification.
