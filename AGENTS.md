# RailAccess AI — Execution Plan

## Mission

Build a hosted, validator-first decision-support tool for NEBULA X 2026 Problem Statement 1: **Railway Track Access Optimisation**. The product creates safe, complete and low-penalty weekly possession schedules for a dual-line network, explains every trade-off, and re-plans after a disruption.

The source of truth is the [official PS1 specification](https://github.com/aochinwen/NebulaX-Hackathon-ProblemStatement/blob/main/PS1/PS1_README.md), not generic maintenance-scheduling assumptions.

## Official contract

- Import eight CSVs: `01_LINES`, `02_STATIONS`, `03_SECTORS`, `04_LOCATION_SUPPLY`, `05_BUFFER_LOCATION`, `06_PARAMETERS`, `07_PROJECT_DETAILS`, and `08_ACTIVITY_DETAILS`.
- Schedule **every** activity's complete `total_accesses`; never drop, omit or silently truncate work.
- Produce three CSVs for each scenario: `SCHEDULE_ACCESS.csv`, `SCHEDULE_OCCUPANCY.csv`, and `RESULTS.csv`.
- Support Scenario A (strict supply), B (strict schedule) and C (balanced trade-off).
- The hosted web app must accept an undisclosed eight-CSV instance, run the solver, visualise the result and export the outputs.
- The organiser validator is the final feasibility authority. Do not call a candidate feasible until it has zero hard violations there.

## Domain facts and corrections

- This is a discrete planning problem in **weeks** and `access_night` slots—not a continuous train-timetabling problem. Prefer binary/integer assignment variables over a premature `IntervalVar` model.
- There is no engineer, contractor-choice or crew-roster allocation input. Contracts and activity data are fixed.
- `ECLO` means **early closure / late opening**, increasing one access yield to 1.5. It is not an electrical-operator resource; do not invent an ECLO staff-capacity constraint.
- A weekly access cap is a cap on distinct allowed `access_night` values per contract/type/week, not a continuous-hours budget.
- `co_share_group` represents a legal shared possession at the same location/week. Model the published `PM` / `PC` / `C` mix rules exactly; do not replace them with a vague compatibility matrix.
- Use the official objective weights: do not tune or invent new Scenario C weights.

## Non-negotiable hard rules

1. Workload conservation and planned-start dates.
2. Location closures, safety buffers and capacity.
3. `Live` mirroring onto the opposite bound and the H01–H02 cross-line exception.
4. Legal possession mixes and valid co-sharing only.
5. Weekly access-night caps and contract workfront limits.
6. Scenario-specific ECLO restrictions, including Scenario C's two-week continuous ECLO window per line.

## Product thesis

**RailAccess Copilot** turns a contested demand book into a proven-safe possession schedule, identifies bottlenecks, and lets a works controller test a disruption without rebuilding the plan manually.

The differentiator is not “an LLM makes a schedule.” It is a validated optimiser with a useful, trustworthy copilot interface.

## Architecture and stack

```text
React + TypeScript UI
        |
        v
FastAPI service
  ├── CSV schema/import validation
  ├── topology, buffers and closure expansion
  ├── custom rule evaluator and score calculator
  ├── CP-SAT schedule model and locked-work recovery
  ├── official-validator adapter
  ├── CSV export service
  └── Vertex AI Gemini tool handlers
        |
        v
Docker → Cloud Run public URL
```

| Layer | Use |
| --- | --- |
| UI | React, TypeScript, Vite, Tailwind, shadcn/ui, custom SVG/Gantt, Recharts |
| API/data | Python 3.12, FastAPI, Pydantic, Pandas |
| Optimisation | Custom domain model and rule evaluator; OR-Tools CP-SAT as the scheduling authority |
| AI | Vertex AI Gemini with strict function schemas |
| Hosting | Docker and one Cloud Run service |
| Tests | Pytest plus public-instance validator regression tests |

Avoid GPUs, Kubernetes, BigQuery, microservices, vector databases and persistent storage in the MVP. Use Cloud Storage/Firestore only if a real requirement emerges.

## Solver design

### Shared preprocessing

1. Parse and cross-reference all official CSVs.
2. Expand each activity into required `SEC` and `PLAT` locations.
3. Compute its buffer closure footprint, `Live` mirror footprint and interchange effects.
4. Generate legal candidate placements: week, access night, ECLO eligibility and possession bundle/co-share options.
5. Fail input validation loudly, with row/column-level error messages.

### Single CP-SAT scheduling model

CP-SAT is the only component that decides a final schedule. The custom domain layer supplies its legal candidate placements, constraints, objective terms and explanations; it does not independently accept or reject a finished timetable.

Model the discrete decision to allocate each required access sequence to a week, access night, ECLO state and legal possession/co-sharing arrangement. Encode every hard rule in the model, then optimise the exact published objective for Scenario A, B or C.

Use CP-SAT status correctly: only `FEASIBLE` or `OPTIMAL` candidates may proceed to the organiser validator. A time-limited `UNKNOWN` result is not a schedule.

### Recovery with locked work

- Convert confirmed placements into hard locks.
- Apply a validated supply or urgent-work change.
- Re-run the same CP-SAT model with an additional schedule-difference objective to minimise unnecessary movement.
- Never use soft penalties to hide hard-rule breaches. Invalid candidates are rejected, not merely scored poorly.

## Build order — optimised for heavy Codex use

Codex should accelerate scaffolding, boilerplate, tests, parsing, UI components and deployment. Humans must still verify every rule against the specification and validator; plausible generated scheduling logic is not enough.

### Phase 0 — foundation (first 1–2 hours)

- Create the Python/React/Docker skeleton and pinned dependencies.
- Add official public data under a clearly marked sample-data path.
- Define Pydantic models, one canonical in-memory schedule format and CSV-output contracts.
- Locate and invoke the organiser validator. If it is not actually supplied in the repository, ask a mentor immediately; this is a blocker for trustworthy iteration.

### Phase 1 — constraint model and validator loop (highest priority)

- Implement import validation, topology expansion and one rule at a time.
- Create minimal fixtures for each hard-rule failure.
- Build a small CP-SAT feasibility model against fixture data; confirm its outputs match the canonical `Schedule` contract.
- Generate correctly shaped exports and run them through the validator as soon as the organiser tool is available.

### Phase 2 — primary CP-SAT solver

- Implement every hard rule and exact Scenario A objective in one CP-SAT model; get a valid public-instance A result.
- Add Scenario B's zero-overrun requirement, excess-capacity and ECLO objective to the same model.
- Add Scenario C's combined score, one-excess-night tolerance and ECLO continuity window to the same model.
- Add regression tests and validator checks for all three scenarios before adding a second search strategy.

### Phase 3 — controller experience

- Build file upload, scenario picker, run state, downloads and validator-report panel.
- Build a dark, high-contrast two-line network/timeline showing possessions, buffers, co-shares and hotspots.
- Add an activity drill-down: blocker, alternatives, score effect and affected locations.

### Phase 4 — recovery, AI and deployment

- Implement disruption re-planning by locking confirmed work in CP-SAT and minimising schedule churn.
- Add grounded Gemini tools only after solver outputs are stable.
- Deploy the one-container application to Cloud Run and rehearse hidden-instance upload.

## AI to implement now

Implement only tool-grounded, non-authoritative AI:

| Feature | Gemini role | Deterministic tool / guardrail |
| --- | --- | --- |
| Explain a delay or conflict | Turn evidence into plain English | `explain_activity()` returns rules, locations, score impact and alternatives |
| Capacity-risk query | Summarise structured hotspot data | `get_capacity_hotspots()` |
| What-if request | Convert text into a proposed structured change | Validate preview; user confirms; then `simulate_disruption()` runs solver |
| Handover brief | Write a concise shift summary | `summarise_plan()` only sees validated result JSON |

Never use Gemini to assign priorities, locations, access nights, ECLO, buffers or co-share groups; declare feasibility; or apply a schedule change without confirmation. Do not build duration prediction—this dataset lacks suitable historical actual-duration labels.

## Side-prize strategy

### Most Unique

Build the **Possession Recovery Sandbox**: a planner reduces a location's supply, locks selected approved work, and receives a validated recovery schedule with a visible “change budget.” This is a real operational capability, not a cosmetic AI chat feature.

### Best Aesthetics

Use a deliberate “night railway control room” design:

- a two-line schematic plus linked week timeline;
- clear visual grammar for `Live`, buffer, `PM`, `PC`, `C`, ECLO, delay and hotspot;
- restrained dark surfaces, accessible contrast and colour-blind-safe status cues;
- animation only when comparing original and recovered schedules; and
- one-click drill-down from a red hotspot to a human-readable reason.

Do a static visual pass after the solver/export path works. Do not let UI polish delay validator feasibility.

### Most Popular

Make the first 20 seconds of the demo legible without domain knowledge:

1. show a congested night;
2. trigger an access disruption;
3. show the validated recovery and unchanged work preserved;
4. let the copilot explain the decision in one sentence.

Use a memorable project name, a clean landing screen, a short visual video and a shareable before/after screenshot for Devpost. A working, beautiful demo is more vote-worthy than a feature list.

## Demo script

1. Upload eight CSVs; choose Scenario C.
2. Run and show zero hard validator violations.
3. Explore an H01–H02 `Live` closure and its mirrored impact.
4. Show legal co-sharing that resolves a capacity bottleneck.
5. Reduce supply at one hotspot; lock confirmed work; re-optimise.
6. Compare original and recovered plans: changes, delay, ECLO, capacity and score.
7. Ask the copilot for a handover summary and download the validated CSV set.

## Team-of-four task allocation and decision ownership

Split the team by the decisions that require human judgement, not merely by folders or programming language. Codex can rapidly implement an agreed contract; it cannot safely resolve an ambiguous rail operating rule, choose a user-facing trade-off, or decide what should be trusted in a live controller workflow.

### First team decision session — before parallel implementation

Spend the first 30–45 minutes together and record the answers in `docs/decision-log.md`:

1. Confirm the exact validator command, its availability and the public-instance baseline result.
2. Agree the canonical objects: `InputInstance`, `Placement`, `Schedule`, `ValidationReport`, `ScenarioChange` and `ScheduleDiff`.
3. Build a rule matrix: official rule → input columns → derived state → validator tag → unit-test fixture → owning person.
4. Agree the MVP boundary: validated A/B/C schedule, upload/export, timeline, recovery sandbox and grounded explanations. Everything else is optional.
5. Confirm the submission repository requirement with the organisers (the published documents currently conflict on GitHub versus GitLab).

No one should begin a large implementation until the canonical objects and rule matrix are written down. Schema changes after this point require the relevant owners' agreement.

### Role 1 — Frontend engineer and controller-experience owner

**Human decision authority:** Decide what a 2AM works controller must see, understand and approve. Own the interaction design and the Best Aesthetics / Most Popular strategy.

| Owns | Deliverables | Must decide before coding proceeds |
| --- | --- | --- |
| User journey | One-page controller workflow and demo storyboard | What the controller can change, lock, inspect and approve |
| UI system | Design tokens, visual grammar, reusable components | Colour/label treatment for `Live`, buffer, PM/PC/C, ECLO, delay, hotspot and validation state |
| Dashboard | Upload, scenario picker, timeline, hotspot/drill-down, comparison and download views | The smallest view that makes a solver result trustworthy rather than overwhelming |
| Pitch assets | Before/after recovery visual, landing screen, demo/video sequence | The first 20 seconds that make the value obvious to a non-expert voter |

Build against versioned mock `Schedule`, `ValidationReport` and `ScheduleDiff` JSON while the solver is being written. The frontend consumes the documented API; it does not recreate rail rules in TypeScript.

### Role 2 — Backend domain, rules and validator engineer

**Human decision authority:** Translate the specification into the canonical data contract and deterministic domain logic. Resolve genuine rule ambiguity with mentors and prevent invented assumptions from entering either backend.

| Owns | Deliverables | Must decide before coding proceeds |
| --- | --- | --- |
| Input/domain layer | Pydantic models, CSV parser, topology and closure expansion | Exact data semantics for buffers, `Live` mirroring, H01–H02, legal mixes, access caps, workfronts and ECLO |
| Rule evidence | `docs/rule-matrix.md`, `docs/data-contract.md`, minimal failure fixtures | Official rule → data fields → derived state → validator tag → unit test mapping |
| Validator/exports | Validator adapter, score parser, required CSV writers | What counts as feasible and how every validator tag maps to API/UI evidence |

This engineer owns the deterministic domain library, but not CP-SAT variable/search design. Every hard-rule interpretation needs a fixture and should be checked against the organiser validator as soon as it is available.

### Role 3 — Backend optimisation and recovery engineer

**Human decision authority:** Design the discrete CP-SAT formulation and recovery behaviour, using only the canonical inputs and rules supplied by Role 2.

| Owns | Deliverables | Must decide before coding proceeds |
| --- | --- | --- |
| Primary solver | Public-instance schedules for A, then B and C | CP-SAT variables, legal candidate/bundling representation and co-sharing encoding |
| Objective layer | Exact A/B/C objective implementation | Model decomposition, time limits and tie-breakers that do not change official weights |
| Recovery solver | Locked-work and minimal-churn re-optimisation | What counts as a meaningful change and how `ScheduleDiff` is computed |

Use one CP-SAT model as the scheduling authority. Custom code prepares the domain-specific inputs and interprets outputs; it does not compete as a separate final scheduler. Never alter domain rules to make the model convenient; raise ambiguity to Role 2.

### Role 4 — Integration, platform and AI engineer

**Human decision authority:** Own cross-component contracts, the end-to-end run path, Cloud Run deployment and the safe scope of Gemini. This role begins at foundation, continuously integrates small slices, and must not become a final-hours merge-only role.

| Owns | Deliverables | Must decide before coding proceeds |
| --- | --- | --- |
| Integration contract | FastAPI routes, versioned API schemas, generated/mock frontend client | Request, result, error and async-run formats shared by Roles 1–3 |
| Run path | Upload orchestration, solver invocation, status, download flow, Docker and Cloud Run | Timeout/error behaviour, no-persistence default and hidden-instance handling |
| Gemini copilot | Tool schemas and grounded response templates | Permitted tools, confirmation point for scenario changes and evidence each answer must cite |
| Quality gates | One-command local run, smoke/E2E test and deploy checklist | When a component is integration-ready and when a deployment is demo-safe |

Gemini may explain a validated result or propose a `ScenarioChange`; it may not set scheduling fields, declare feasibility or execute a change before the user sees and confirms the structured preview. Roles 2 and 4 jointly approve this guardrail.

### Parallelisation plan

| Stage | Role 1 | Role 2 | Role 3 | Role 4 |
| --- | --- | --- | --- | --- |
| Foundation | Controller flow + visual grammar | Rule matrix, data contract and validator probe | CP-SAT model sketch | Skeleton, API contract, mocks and local run |
| First vertical slice | Timeline with fixture data | Import, exports and hard-rule fixtures | Scenario A feasible schedule | Upload, solver-run and validator-report API |
| Complete solver | Hotspot and activity drill-down | A/B/C acceptance tests + validator evidence | B/C objectives and recovery solver | Continuous E2E integration tests |
| Differentiation | Before/after comparison UX | Validate disruption rules | Minimal-churn re-plan | Gemini tools, Docker and Cloud Run |
| Final demo | Pitch, video and visual polish | Validator sign-off | Score/performance sign-off | Hosted hidden-instance rehearsal |

### Integration rules

- Treat the shared schemas as an API. Role 4 owns their integration; Roles 2 and 3 approve semantic changes, and Role 1 receives updated mocks immediately.
- Every hard-rule implementation needs a test fixture from Role 2 and a validator check before merging.
- Role 3 may use solver-specific internal structures, but exported schedules must pass through the canonical `Schedule` object.
- Role 1 must display validator facts and score components; never infer validity from a chart alone.
- Role 4 must keep Gemini behind tool calls; raw model prose is never a scheduling input or a feasibility result.
- For a conflict, use this precedence: official specification → organiser validator/mentor clarification → rule matrix → implementation convenience.

### Daily decision checkpoints

Run a 10-minute checkpoint at each integration point:

1. **Feasibility:** Do we have zero hard violations on the public instance? If not, all optional work pauses.
2. **Contract:** Did any input, output or API schema change? Update the decision log and mocks immediately.
3. **Usability:** Can a teammate explain one schedule decision from the current UI without reading code?
4. **Prize fit:** Does the recovery sandbox visibly preserve unaffected work, and does the UI make that obvious?
5. **Deployment:** Can a clean machine/container run the app with only documented commands?

## Submission checklist

- [ ] Public schedules for A, B and C have zero hard validator violations.
- [ ] Every activity is fully scheduled.
- [ ] Hosted Cloud Run app accepts a fresh hidden eight-CSV instance.
- [ ] Exports exactly match the required schemas.
- [ ] README includes setup, data handling, stack, architecture and demo instructions.
- [ ] Repository URL requirement (GitHub vs GitLab) is confirmed with organisers.
- [ ] Hosted URL, 2–3 minute video, write-up and ZIP are prepared.
