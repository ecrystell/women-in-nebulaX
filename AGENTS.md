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
  ├── constructive scheduler + local repair / CP-SAT
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
| Optimisation | Custom heuristic and rule engine; OR-Tools CP-SAT for local repair/improvement |
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

### Constructive solver

Schedule the least-flexible work first, breaking ties by:

1. `Live` work / widest closure footprint;
2. contract priority and deadline slack;
3. workload still outstanding; and
4. capacity scarcity at required locations.

Choose candidates by hard-feasibility first, then the exact official scenario penalty, then future-capacity preservation. Bundle compatible `PC`/`C` work only where the formal mix rule permits it.

### Improvement and recovery

- Identify high-cost locations/weeks and activities causing delay.
- Destroy only the affected neighbourhood and repair it with CP-SAT or bounded local search.
- Include a schedule-stability penalty during disruption re-planning: preserve locked work and minimise changed unaffected assignments.
- Never use soft penalties to hide hard-rule breaches. Invalid candidates are rejected, not merely scored poorly.

## Build order — optimised for heavy Codex use

Codex should accelerate scaffolding, boilerplate, tests, parsing, UI components and deployment. Humans must still verify every rule against the specification and validator; plausible generated scheduling logic is not enough.

### Phase 0 — foundation (first 1–2 hours)

- Create the Python/React/Docker skeleton and pinned dependencies.
- Add official public data under a clearly marked sample-data path.
- Define Pydantic models, one canonical in-memory schedule format and CSV-output contracts.
- Locate and invoke the organiser validator. If it is not actually supplied in the repository, ask a mentor immediately; this is a blocker for trustworthy iteration.

### Phase 1 — vertical feasibility slice (highest priority)

- Implement import validation, topology expansion and one rule at a time.
- Create minimal fixtures for each hard-rule failure.
- Generate correctly shaped exports and run them through the validator.
- Get a valid public-instance Scenario A schedule before investing in a polished UI.

### Phase 2 — complete competition solver

- Implement exact A scoring and hard rules.
- Add Scenario B's zero-overrun requirement, excess-capacity and ECLO objective.
- Add Scenario C's combined score, one-excess-night tolerance and ECLO continuity window.
- Add constructive scheduling, repair and regression tests for all three scenarios.

### Phase 3 — controller experience

- Build file upload, scenario picker, run state, downloads and validator-report panel.
- Build a dark, high-contrast two-line network/timeline showing possessions, buffers, co-shares and hotspots.
- Add an activity drill-down: blocker, alternatives, score effect and affected locations.

### Phase 4 — differentiation and deployment

- Implement disruption re-planning with locked work and minimal churn.
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

### Role 1 — Operations, rules and validator lead

**Human decision authority:** Interpret the specification, identify genuine ambiguities, decide which mentor questions are necessary, and protect the product from unsafe or invented assumptions.

| Owns | Deliverables | Must decide before coding proceeds |
| --- | --- | --- |
| Rule matrix and data dictionary | `docs/rule-matrix.md`, `docs/data-contract.md`, minimal CSV fixtures | Exact interpretation of buffers, `Live` mirroring, H01–H02 behaviour, legal mixes, access caps, workfronts and ECLO |
| Validator evidence | Repeatable validator runner and public-instance baseline | What counts as feasible and how each validator tag maps to a UI explanation |
| Scenario policy | Exact A/B/C score calculations and acceptance tests | No invented costs, capacities or priorities |

This person signs off hard-constraint behaviour. They do not need to write every solver feature, but they should create a failing test before the team claims a rule is implemented.

### Role 2 — Optimisation and recovery lead

**Human decision authority:** Choose the schedule representation, search strategy, candidate ordering and repair neighbourhoods while preserving the operations lead's rule contract.

| Owns | Deliverables | Must decide before coding proceeds |
| --- | --- | --- |
| Baseline solver | Complete public-instance schedule for A, then B and C | Candidate placement/bundling representation and how co-sharing is constructed |
| Objective implementation | Exact scenario score calculator and solver objective | Tie-breakers that preserve future flexibility without altering official score weights |
| Recovery sandbox | Locked-work semantics, change budget and minimal-churn objective | What counts as a meaningful disruption and how schedule change is measured |

Use a custom constructive solver first, then targeted CP-SAT/local repair. Never alter domain rules to make a solver convenient; send ambiguities back to Role 1.

### Role 3 — Product, controller workflow and visual-design lead

**Human decision authority:** Decide what a 2AM works controller must see, understand and approve. Own the interaction design and the Best Aesthetics / Most Popular strategy.

| Owns | Deliverables | Must decide before coding proceeds |
| --- | --- | --- |
| User journey | One-page controller workflow and demo storyboard | What the controller can change, lock, inspect and approve |
| UI system | Design tokens, visual grammar, reusable components | Colour/label treatment for `Live`, buffer, PM/PC/C, ECLO, delay, hotspot and validation state |
| Dashboard | Upload, scenario picker, timeline, hotspot/drill-down, comparison and download views | The smallest view that makes a solver result trustworthy rather than overwhelming |
| Pitch assets | Before/after recovery visual, landing screen, demo/video sequence | The first 20 seconds that make the value obvious to a non-expert voter |

Build against stable mock `Schedule` and `ValidationReport` JSON while the solver is being written. Do not wait for the final solver to create the visual system.

### Role 4 — Platform, data integration and AI-safety lead

**Human decision authority:** Own system boundaries, API contracts, upload/export behaviour, deployment choices, and the safe scope of Gemini interactions.

| Owns | Deliverables | Must decide before coding proceeds |
| --- | --- | --- |
| Application contract | Pydantic schemas, FastAPI routes, frontend API client | Versioned data and error formats shared by UI and solver |
| Integration | CSV upload, schema errors, output downloads, Docker and Cloud Run | Whether any organiser data persists; default is no persistence |
| Gemini copilot | Tool schemas and grounded response templates | Permitted tool calls, confirmation point for scenario changes, evidence each answer must cite |
| End-to-end quality | One-command local run, smoke test and deploy checklist | Timeout/error handling and hidden-instance upload failure behaviour |

Gemini may explain validated output or propose a `ScenarioChange`; it may not set scheduling fields, declare feasibility or execute a change before the user sees and confirms the structured preview. Role 4 and Role 1 jointly approve this guardrail.

### Parallelisation plan

| Stage | Role 1 | Role 2 | Role 3 | Role 4 |
| --- | --- | --- | --- | --- |
| Foundation | Rule matrix + validator probe | Candidate model sketch | Controller flow + visual grammar | Skeleton, canonical schemas and local run |
| First vertical slice | Hard-rule fixtures | Scenario A valid schedule | Timeline with fixture data | Upload, export and validator API |
| Complete solver | A/B/C acceptance tests | B/C + repair implementation | Hotspot and activity drill-down | End-to-end integration tests |
| Differentiation | Validate disruption rules | Minimal-churn re-plan | Before/after comparison UX | Gemini tools, Docker and Cloud Run |
| Final demo | Validator sign-off | Score/performance sign-off | Pitch, video and visual polish | Hosted hidden-instance rehearsal |

### Integration rules

- Treat the shared schemas as an API. Role 4 owns their implementation; Roles 1 and 2 must approve semantic changes.
- Every hard-rule implementation needs a test fixture from Role 1 and a validator check before merging.
- Role 2 may use solver-specific internal structures, but exported schedules must pass through the shared canonical `Schedule` object.
- Role 3 must display validator facts and score components; never infer validity from a chart alone.
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
