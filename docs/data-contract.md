# For Rails data contract

**Status:** proposed v0.1 — review and approve before feature branches diverge.  
**Source of truth:** the official PS1 brief, then the organiser validator/mentor clarification, then this contract.  
**Owners:** Role 4 owns integration and publication; Roles 2 and 3 approve semantic changes; Role 1 receives updated mocks.

This document defines the shared language between CSV ingestion, deterministic rules, CP-SAT, API, frontend, exports, recovery, and grounded AI. It deliberately separates a **candidate schedule** from the organiser's **verification evidence**.

## Contract-wide rules

- JSON field names use `snake_case`; identifiers remain the exact strings supplied in official CSVs.
- Dates use ISO-8601 calendar dates (`YYYY-MM-DD`). Weeks are positive, one-based planning-horizon weeks.
- `eclo` is always `0` or `1`, matching the required CSVs. A standard placement yields `1.0` access units; an ECLO placement yields `1.5`.
- `access_night` is the local, positive allocation index for a `(contract_number, activity_type, week)` combination. It is not a global night identifier and is not a location capacity slot.
- A `Schedule` is one scenario only. A `RESULTS.csv` must never combine scenarios.
- Only an organiser-validator execution with zero hard violations may produce `ValidationReport.status = "verified"` and `feasible = true`. Local parsing, export, solver, or UI checks cannot do so.
- The domain/rule engine owns derived railway facts. Frontend code displays those facts and must not reimplement rail rules.

## Canonical objects

### `InputInstance`

The complete, parsed eight-CSV input package for one planning horizon.

```ts
type InputInstance = {
  source: {
    instance_id: string;          // caller-generated, not an organiser identifier
    received_at: string;          // ISO timestamp
    fixture: boolean;             // true only for vendored public data
  };
  lines: LineRecord[];
  stations: StationRecord[];
  sectors: SectorRecord[];
  location_supply: LocationSupplyRecord[];
  buffer_locations: BufferLocationRecord[];
  parameters: ParameterRecord[];
  projects: ProjectRecord[];
  activities: ActivityRecord[];
};
```

`backend/app/domain/models.py:InstanceBundle` is the current in-memory implementation of the table portion of `InputInstance`. The `source` envelope is an integration concern to add when uploads are implemented; do not duplicate the eight source tables in a new solver model.

Input validation has two layers:

1. **Schema validation:** exactly the eight recognised filenames, exact ordered headers, parseable types, enums, dates, and numeric bounds.
2. **Reference/domain validation:** cross-file IDs, route direction/reachability, valid planned weeks, and any other requirements established by the official validator. This begins in Phase 1.

### `Placement`

One scheduled access sequence for one activity. A placement is the internal unit chosen by the solver and the unit shown in a timeline.

```ts
type PlacementKey = {
  activity_id: string;
  access_seq: number;
};

type Occupancy = {
  location_id: string;
  co_share_group: string;
};

type Placement = PlacementKey & {
  week: number;
  access_night: number;
  eclo: 0 | 1;
  occupancies: Occupancy[];
};
```

`occupancies` is deliberately a list: one activity access occupies multiple `SEC` and `PLAT` locations, and its co-share group can differ by location. Do not put one schedule-wide or placement-wide `co_share_group` field on this object.

Current Phase 0 equivalents are `AccessAssignment` plus the matching `OccupancyAssignment` rows. The exporter is responsible for flattening a `Placement` to the two required submission files.

### `Schedule`

The complete candidate answer for a single scenario, independent of whether it is verified.

```ts
type Schedule = {
  schedule_id: string;
  input_instance_id: string;
  scenario: "A" | "B" | "C";
  placements: Placement[];
  contract_results: ContractResult[];
  generated_at: string;
};
```

Invariants:

- Each `PlacementKey` occurs at most once.
- Every `contract_results[].scenario` equals `Schedule.scenario`.
- A schedule is not labelled feasible itself. It is a candidate until paired with a `ValidationReport`.
- Solver-specific variables, candidate rankings, and CP-SAT diagnostics stay out of this object.

`ScenarioSchedule` is the current Phase 0 equivalent. Role 3 may use solver-internal representations, but conversion to this contract is required before validation, exports, API delivery, or UI use.

### `ValidationReport`

Evidence about a specific schedule produced by the validator adapter.

```ts
type Violation = {
  rule: string;                  // local rule name; organiser tags only when supplied
  severity: "hard" | "soft";
  detail: string;
  activity_ids?: string[];
  location_ids?: string[];
  week?: number;
  source_file?: string;
  row?: number;
  field?: string;
  co_share_group?: string;
  derived_footprint?: string[];
  input_values?: Record<string, string | number | boolean | null>;
};

type ValidationReport = {
  schedule_id?: string;
  status: "unavailable" | "unverified" | "verified";
  feasible: boolean | null;
  message: string;
  hard_violations: Violation[];
  soft_scores: Record<string, unknown>;
  detail?: Record<string, unknown>;
  validator: {
    name?: string;
    version?: string;
    executed_at?: string;
  };
};
```

`derived_footprint` and `input_values` are local-check evidence. They make a
finding inspectable without claiming that its `rule` is an organiser-validator
tag. The three source-location fields identify an input problem when the
information came from CSV ingestion or preprocessing. All evidence fields are
optional because a rule may not have a meaningful value for every one.

State meanings:

| Status | `feasible` | Meaning |
| --- | --- | --- |
| `unavailable` | `null` | Official validator package/command is not installed. |
| `unverified` | `null` | Local contract checks may have run, but no organiser decision exists. |
| `verified` | `true` or `false` | Organiser validator ran successfully; `true` requires no hard violations. |

The current adapter exposes the first two states only. Never convert a local solver success or empty internal error list into `verified`.

### `ScenarioChange`

A user-confirmed recovery input. It expresses a changed operating condition, never a direct instruction to fabricate a schedule.

```ts
type SupplyOverride = {
  location_id: string;
  week: number;
  supply_capacity: number;
};

type ScenarioChange = {
  change_id: string;
  base_schedule_id: string;
  scenario: "A" | "B" | "C";
  supply_overrides: SupplyOverride[];
  locked_placements: PlacementKey[];
  requested_by: string;
  confirmed_at: string;
  rationale?: string;
};
```

Rules:

- The frontend may preview a change, but only an explicit user confirmation creates `confirmed_at` and starts re-optimisation.
- `locked_placements` preserves the exact access sequence selected in the baseline; the solver may not silently change it.
- This MVP contract supports capacity reduction/override and locking only. New activities, priority edits, ad-hoc ECLO requests, and manual placement edits require a reviewed contract extension.
- Gemini may propose a draft change, but cannot confirm or execute it.

### `ScheduleDiff`

The deterministic comparison between a baseline candidate and a recovered candidate.

```ts
type PlacementChange = {
  key: PlacementKey;
  kind: "unchanged" | "moved" | "added" | "removed";
  before?: Placement;
  after?: Placement;
  changed_fields: Array<"week" | "access_night" | "eclo" | "occupancies">;
};

type ScheduleDiff = {
  baseline_schedule_id: string;
  recovered_schedule_id: string;
  placement_changes: PlacementChange[];
  unchanged_count: number;
  moved_count: number;
  score_delta?: Record<string, number>;
  completion_delta?: Record<string, number>;
};
```

A recovery cannot remove workload: each activity's delivered yield must still meet `total_accesses` in both schedules. ECLO can legitimately change the number of access sequences, so an access sequence may be `added` or `removed` in the diff. A changed co-share group or occupancy footprint counts as a moved placement even when week and access night stay the same.

### Capability and public-demo boundary

`GET /api/v1/capabilities` is the controller's source of truth for which
workflow may be started. Each Scenario A/B/C entry and the `recovery`,
`public_demo_recovery`, and `disruption_drafts` features expose `available`, a
stable unavailable `code`, and a human-readable `message`.

The public demonstration is deliberately separate from an uploaded instance:

- it is created only from the repository-owned, checksum-verified public
  fixture and has `RunView.demo=true` plus a visible notice;
- it replays a fixed reviewed change and never represents a new optimisation;
- it cannot export, package, record organiser evidence, or become feasible;
- an ordinary upload is never eligible for this route, even when its bytes
  happen to match the public input files.

### `ScenarioChangeDraft`

A review-only interpretation of bounded controller text:

```ts
type ScenarioChangeDraft = {
  draft_id: string;
  change: Omit<ScenarioChange, "confirmed_at"> & { confirmed_at: null };
  assumptions: string[];
  unresolved_references: string[];
  field_errors: Array<{ field: string; message: string }>;
  evidence_version: "1";
  status: "ready" | "needs_review";
};
```

R4.8A restricts this endpoint to the public demo and passes the model only the
controller text plus bounded public location and placement identifiers. Server
code validates every generated reference before retaining the draft. A draft
cannot run any solver, validator, exporter, submission action, or real
recovery. A `ready` draft may only trigger the fixed public replay; extending
that confirmation path to a live recovery waits for the locked-work solver.

## Official CSV and export mapping

| Canonical area | Official source/output | Contract rule |
| --- | --- | --- |
| `InputInstance` tables | `01_LINES.csv` through `08_ACTIVITY_DETAILS.csv` | Preserve source column names and values; do not infer missing data. |
| `Placement.key`, `week`, `eclo`, `access_night` | `SCHEDULE_ACCESS.csv` | One row per scheduled activity access sequence. |
| `Placement.occupancies` | `SCHEDULE_OCCUPANCY.csv` | One row per activity/week/location occupancy. |
| `Schedule.contract_results` | `RESULTS.csv` | One row per contract, one scenario per file. |
| `ValidationReport` | Organiser validator JSON/report | Adapter normalises evidence without changing its meaning. |

Exact output columns and order are fixed:

```text
SCHEDULE_ACCESS.csv:    activity_id,access_seq,week,eclo,access_night
SCHEDULE_OCCUPANCY.csv: activity_id,week,location_id,co_share_group
RESULTS.csv:            scenario,contract_number,simulated_completion_date,overrun_days
```

## Change control and review gate

1. Propose a contract change in `docs/decision-log.md` with motivation, affected owners, and migration impact.
2. Roles 2 and 3 approve semantic changes; Role 4 updates API/mocks; Role 1 confirms the UI impact.
3. Update the rule matrix and relevant fixtures in the same pull request.
4. No consumer may depend on an unreviewed field or derive a different meaning locally.

## Open decisions for the team

- Confirm the public API envelope and generated client strategy (`/api/v1` vs a minimal unversioned MVP route) before Role 4 publishes frontend mocks.
- Confirm the organiser validator's exact report shape and tag vocabulary before making any field mandatory beyond the documented wrapper.
- Confirm whether recovery allows supply increases as well as reductions; the proposed contract permits an explicit override but the UI should default to reduction only.
