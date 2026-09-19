# For Rails — Track 1 Railway Track Access Optimisation

An explainable, validator-first decision-support tool for planning nightly railway track possessions across a dual-line network. It assigns every contracted activity to access nights and locations, proves that safety rules are respected, and makes the schedule's trade-offs intelligible to a works controller.

Built for **NEBULA X Hackathon 2026 — Problem Statement 1**.

## The actual challenge

Every night, the period between the last and first train is contested by renewals, construction and maintenance work. We must decide **which activity receives track access, at which location, in which week and on which access night** across Line Alpha and Line Beta.

The solution is not just a calendar recommendation. It must:

- schedule **100% of the access workload** for every activity;
- obey all physical safety and possession rules;
- handle congestion by compressing and co-sharing work where legal, rather than dropping work or giving up; and
- export a schedule that passes the organisers' validator for all three planning scenarios.

The network contains tunnel sectors (`SEC`) and platform sectors (`PLAT`) on eastbound and westbound tracks. The two lines are independent except for special `Live`-work rules at the H01–H02 interchange.

## What For Rails does

1. Accepts the eight provided instance CSVs through a guided upload flow.
2. Builds a network and possession-impact model for every activity.
3. Finds a feasible, low-penalty schedule for Scenario A, B or C.
4. Shows a timeline, capacity hotspots, closures, buffers, co-sharing and workfront allocation.
5. Explains hard conflicts and the cost of every trade-off in plain language.
6. Exports the three required submission CSVs and runs the organiser validator as the final gate.
7. Re-optimises a scenario when a planner changes supply or introduces an urgent access request, while minimising unnecessary schedule churn.

## Input data

The app imports the official Track 1 data package directly:

| File | Purpose |
| --- | --- |
| `01_LINES.csv` | Line definitions |
| `02_STATIONS.csv` | Stations and interchanges |
| `03_SECTORS.csv` | Directed tunnel and platform network topology |
| `04_LOCATION_SUPPLY.csv` | Nominal capacity by location |
| `05_BUFFER_LOCATION.csv` | Closure and buffer expansion rules |
| `06_PARAMETERS.csv` | Planning-horizon parameters |
| `07_PROJECT_DETAILS.csv` | Contract type, priority, access cap, deadline and workfronts |
| `08_ACTIVITY_DETAILS.csv` | Activity section, workload, planned start and activity priority |

The importer validates schema and references before scheduling. It converts each activity's book-in/book-out section into the tunnel and platform locations it occupies, including the effects of buffers and `Live`-rail mirroring.

## Non-negotiable constraints

The solver and validator must never allow:

- incomplete workload: every activity's allocated access yield must meet `total_accesses`;
- work before an activity's planned start date;
- location capacity or safety-buffer breaches;
- `Live` work that fails to close the opposite bound, or the affected H01–H02 interchange locations on both lines;
- illegal possession mixes: one `PM` alone, or one `PC` with up to three `C`, or up to four `C` activities;
- misuse of co-sharing groups, which are the only allowed buffer exemption;
- a contract exceeding its weekly access-night allocation; or
- a contract exceeding its nightly workfront limit.

`ECLO` (early closure/late opening) increases nightly yield to 1.5 access units but has scenario-specific restrictions and commuter impact. In Scenario C, ECLO use on each line must stay within one continuous window of at most two weeks.

## Scenario-aware objectives

| Scenario | Hard policy | Optimisation target |
| --- | --- | --- |
| **A — Strict Supply** | No supply excess; ECLO prohibited | Minimise priority-weighted planned-completion overrun |
| **B — Strict Schedule** | No planned-completion overrun | Minimise excess access-nights and ECLO use |
| **C — Balanced** | At most one excess access-night per location-week; ECLO continuity rule | Balance priority-weighted overrun, excess access-nights and ECLO use |

Priority comes from the supplied contract and activity data. Contract priority sets the main delay-cost band (Priority 1, 2, 3); activity priority only adjusts cost within its contract's tier. The tool will show this score breakdown instead of hiding it behind a single “AI score.”

## Architecture

```text
8 official CSVs
      |
      v
Schema validation + topology/buffer expansion
      |
      +----> Conflict & capacity inspector
      |
      v
Scenario-specific constraint model
      |
      +----> Custom scoring + schedule-stability objectives
      |
      v
CP-SAT schedule model (single scheduling authority)
      |
      v
Validator gate ---> 3 required CSV exports ---> Planner dashboard
                          |
                          +--> Grounded AI explanations / what-if copilot
```

## Technical approach

### Optimisation

The core is deterministic and auditable:

- **Custom domain intelligence** parses the official data, expands each activity's required locations, applies buffers and `Live` mirroring, constructs legal co-sharing options, calculates exact scenario scores and produces reason-coded explanations.
- **OR-Tools CP-SAT** is the single scheduling authority. It chooses among legal placements while enforcing all hard rules and the selected Scenario A/B/C objective in one model.
- For disruption recovery, approved placements are locked and CP-SAT minimises schedule churn alongside the official scenario objective. This remains one consistent optimisation model, rather than a second heuristic with conflicting rules.
- The **organiser validator** is the final source of truth. A candidate is never presented as feasible until it passes validation.

The custom domain model makes CP-SAT railway-specific; the single solver authority reduces hidden-validator risk and makes the resulting plan easier to trust.

### AI: where it adds value safely

The official data already provides location, workload, possession type and priorities, so an LLM must **not** invent or finalise them. Instead, Gemini on Vertex AI is used for:

- grounded natural-language explanations of a solver result: “Why was A012 moved to Week 7?”;
- natural-language schedule queries and handover summaries;
- a what-if copilot that turns a planner instruction into a proposed scenario change, then requires confirmation and deterministic re-optimisation; and
- concise impact summaries: affected contracts, new overrun, ECLO use and capacity hotspots.

Every response is grounded in structured solver output. Gemini cannot directly allocate work, bypass a hard rule, or claim a plan is feasible.

### Hidden-instance and copilot handling

Hidden scheduling data stays in the live Cloud Run process only and is removed
after 30 minutes of inactivity, restart, revision rollout, or scale-down. A
per-run browser cookie protects runs, exports, packages, evidence and recovery
requests; a run ID alone is insufficient.

The read-only copilot sends only one selected deterministic evidence envelope to
Gemini: an activity explanation, up to ten capacity hotspots, or a compact
handover summary. It never sends raw CSVs, full schedules, exports, submission
packages, checksums, organiser metadata, or free-text disruption requests. Its
answers remain unverified and cannot establish feasibility. See
[the hidden-data policy](docs/HIDDEN_DATA_POLICY.md) for the operational rules.

## Tech stack

| Layer | Technology | Role |
| --- | --- | --- |
| Web app | React, TypeScript, Vite, Tailwind CSS, shadcn/ui | Upload flow, scenario control, timeline and explanations |
| Visuals | Custom SVG/Gantt timeline, Recharts | Location occupancy, buffers, capacity and score breakdown |
| API | Python 3.12, FastAPI, Pydantic, Pandas | CSV ingestion, schemas, solver and export APIs |
| Optimisation | Custom domain model / rule evaluator; OR-Tools CP-SAT | Single-source feasible scheduling, recovery and low-penalty search |
| AI | Vertex AI Gemini with structured tool calls | Grounded explanations and what-if interpretation |
| Hosting | Docker, Cloud Run | Public hosted prototype and stable judging URL |
| Optional persistence | Firestore / Cloud Storage | Saved scenarios or uploaded instances only if needed |

The MVP keeps inputs in the browser session or container workspace for the run. We will not persist organiser data unless needed and authorised. Cloud Run is used for hosting—not for unnecessary GPU or distributed-compute complexity.

## Phase 0 foundation

The initial foundation provides typed CSV and submission contracts, public schema fixtures, a minimal control-room shell, and a single Python 3.12 production container. It deliberately does **not** claim schedule feasibility: the organiser validator has not been supplied in a runnable form.

```powershell
docker compose up --build
```

Open `http://localhost:8080` and call `http://localhost:8080/api/v1/health` to confirm the versioned integration API. The validator status remains `unavailable` or `unverified` until the organiser validator is integrated. Public fixture provenance is in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md); the requested validator package details are in [`docs/VALIDATOR_REQUEST.md`](docs/VALIDATOR_REQUEST.md). Team contract and rule-review materials are in [`docs/data-contract.md`](docs/data-contract.md), [`docs/rule-matrix.md`](docs/rule-matrix.md), and [`docs/decision-log.md`](docs/decision-log.md).

To run the backend tests outside Docker, use Python 3.12 and install the exact packages in `requirements.txt`; build the frontend with `npm ci` followed by `npm run build` from `frontend/`.

### Local preflight before an organiser upload

Run the deterministic local checks against an input package and the three files you intend to upload:

```powershell
docker compose run --rm app python -m app.validation.preflight `
  --instance data/public-instance `
  --submission path/to/submission
```

Exit code `0` means the implemented local checks found no hard violation; `1` prints the violations and preserves the schedule as **unverified**. The check validates CSV contracts, workload, dates, precedence, topology, possession mixes, same-week possession-group closure zones, hidden weekly physical-night feasibility, weekly allocation, workfronts, capacity, ECLO policies, results, and score components. Scenario C treats location-specific organiser-style directional closure findings as hard; Scenario A retains those findings as diagnostics and uses nominal hidden-night feasibility as its hard gate. Same-contract/type co-share-night contradictions are hard in both. The published `access_night` remains contract/type-local and is not treated as a network-wide identifier. A locally clean result remains unverified until the organiser validator confirms the exact exported files.

### Manual organiser submission evidence

Set a full Git commit before building the package-capable container:

```powershell
$env:FOR_RAILS_BUILD_COMMIT = git rev-parse HEAD
docker compose up --build
```

After a locally clean succeeded run, the controller can create a ZIP containing
the three official CSVs plus an immutable checksum manifest. Upload the CSVs
manually on the organiser website, then record only structured result metadata
and download the combined evidence JSON. This data is held only for the live
process and must be retained outside Git. An organiser-reported outcome remains
`unverified`; it never sets `feasible=true` without a supported organiser report
integration. See [`docs/ORGANISER_SUBMISSION_PLAYBOOK.md`](docs/ORGANISER_SUBMISSION_PLAYBOOK.md).

### Public recovery sandbox (fixture-only)

The controller UI can open a public recovery demonstration without uploading
data. The API verifies the committed public input checksums, then shows the
published Scenario A schedule beside a fixed, reviewed disruption replay. The
demo is explicitly **unverified** and is not an optimisation: it cannot export
CSV files, create a submission package, record organiser evidence, or be used
with an uploaded/hidden instance.

When Vertex is enabled, the demo also accepts a short controller instruction
and returns a review-only typed disruption draft. Only recognised public
location and placement identifiers are retained; unknown or ambiguous values
remain errors. A ready draft can replay the fixed demo only. Real disruption
recovery remains unavailable until the locked-work recovery solver is wired in.

### Scenario A/C solver (implemented)

Run the CP-SAT solver directly without starting the frontend. Scenario A keeps
its existing strict-supply/no-ECLO policy; Scenario C adds the published
one-excess-possession allowance, ECLO, and two-week per-line ECLO windows.

Scenario A:

```powershell
$env:PYTHONPATH = "backend"
python -m app.solver `
  --scenario A `
  --input-dir data/public-instance `
  --output-dir sample_submission/scenario_a
```

Scenario C:

```powershell
python -m app.solver `
  --scenario C `
  --input-dir data/public-instance `
  --output-dir sample_submission/scenario_c `
  --time-limit 300 `
  --workers 8
```

The command writes `SCHEDULE_ACCESS.csv`, `SCHEDULE_OCCUPANCY.csv`, and `RESULTS.csv`, then runs the local preflight checks. If the output folder already contains a locally valid schedule, rerunning the same command reconstructs its hidden CP-SAT state and uses it as a complete warm start. The current corrected Scenario C public incumbent scores `158.2` in the 300-second/8-worker run; it is locally clean but not proven optimal. A clean local preflight remains **unverified** until the organiser/reference validator is run. Scenario B remains an extension point and is not implemented yet.

## Required exports

For **each** Scenario A, B and C, the tool generates:

```text
SCHEDULE_ACCESS.csv     # activity_id, access_seq, week, eclo, access_night
SCHEDULE_OCCUPANCY.csv  # activity_id, week, location_id, co_share_group
RESULTS.csv             # scenario, contract_number, simulated_completion_date, overrun_days
```

The dashboard makes these outputs downloadable and includes the corresponding validator report: feasibility, hard violations, capacity hotspots, total access nights, ECLO use and priority-weighted score.

## Product experience / demo

1. Upload the eight CSVs and choose Scenario C.
2. Inspect a bottleneck at the H01–H02 interchange and see why `Live` work closes more than its own line.
3. Generate a schedule and show the timeline, legal co-sharing and capacity hot spots.
4. Open a high-priority delayed contract: see the exact overrun and the alternative cost of ECLO or excess supply.
5. Simulate an urgent disruption that reduces a location's capacity; re-optimise and show minimal changes to unaffected work.
6. Ask the copilot for a plain-English handover summary, then download the validated CSV set.

## Repository structure

```text
frontend/                 # React dashboard
backend/app/
  domain/                 # canonical models and shared preprocessing/footprints
  ingestion/              # schemas and official CSV adapters
  constraints/            # buffers, mixes, caps, workfronts, ECLO rules
  solver/                 # CP-SAT model, objectives and locked-work recovery
  validation/             # validator adapter and report parser
  exports/                # required submission CSV writers
  ai/                     # Gemini tools grounded in solver results
data/public-instance/     # official sample data; no secrets
tests/                    # rule-level and scenario regression tests
docs/                     # data contract, demo script and deployment guide
```

## Definition of done

- [ ] All three public-instance schedules have zero hard validator violations.
- [ ] Every activity is fully scheduled; none is silently dropped.
- [ ] A hidden eight-CSV instance can be uploaded and scheduled through the hosted web app.
- [ ] The UI explains closures, buffers, co-sharing, workfronts, capacity and scenario trade-offs.
- [ ] The app exports correctly shaped CSVs for A, B and C.
- [ ] The Cloud Run URL, Git repository, three-minute video, short write-up and final ZIP are ready for submission.

## Sources

- [Official Track 1 brief and data package](https://github.com/aochinwen/NebulaX-Hackathon-ProblemStatement/tree/main/PS1)
- [Problem Statement 1 specification](https://github.com/aochinwen/NebulaX-Hackathon-ProblemStatement/blob/main/PS1/PS1_README.md)
