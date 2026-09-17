# Track 1 — AI Maintenance Scheduler

An explainable decision-support tool for planning railway maintenance during short engineering windows. It detects conflicts across track access, work compatibility and qualified staff, then proposes feasible, prioritised alternatives.

Built for **NEBULA X Hackathon 2026 — Problem Statement 01: Smarter planning, better outcomes**.

## The problem

Maintenance, upgrades and renewals must be completed in limited non-revenue engineering hours. Planners receive competing work requests and must manually reconcile:

- track sector and possession availability;
- whether simultaneous works are compatible;
- engineer certifications and line/system competencies;
- crew capacity, travel/transition time and shift limits; and
- request urgency and the effect of deferring work on service and commuters.

The result is slow coordination, opaque trade-offs and avoidable conflicts. Our aim is not to replace the planner: it is to make every feasible choice visible, explainable and quick to act on.

## What we are building

The scheduler accepts a set of maintenance requests, engineering windows and staff availability. It will:

1. Validate each request against non-negotiable safety and operational constraints.
2. Clearly show every conflict and its cause (for example, **same track sector**, **overlapping isolation**, or **no engineer with signalling certification available**).
3. Generate ranked alternatives: another valid window, compatible sector, eligible crew, or a lower-impact reordering.
4. Produce a draft allocation for each engineer and a live capacity view for planners.
5. Surface the trade-off behind a recommendation—e.g. *“This move keeps the high-priority renewal in-window and reduces the number of displaced requests from two to one.”*

## Why this fits Track 1

The official brief asks for a tool that **automatically detects conflicts, flags them clearly, suggests alternatives and automates scheduling**. This project addresses all four directly, while keeping a human planner in approval of the resulting plan. The brief specifically calls out competing track requests, sector availability, work compatibility and engineer availability as the scheduling riddle to solve.

## Scheduling model

### Inputs

| Entity | Essential fields |
| --- | --- |
| Maintenance request | ID, work type, priority, duration, earliest/latest date, sector(s), possession/isolation needs, required skills/certifications, crew size, service-impact score |
| Engineering window | start/end time, available sectors, permitted work types, planned early closure or late opening, blackout periods |
| Engineer / crew | availability, shift limit, certifications, line/system competencies, home base, assigned work |
| Network constraints | incompatible work pairs, sector adjacency/exclusion rules, setup/teardown and transition times |

### Hard constraints — never violated

- Work occurs wholly inside an approved engineering window.
- A sector, possession or incompatible adjacent sector is never double-booked.
- The allocated crew meets required size and every required certification/competency.
- Each engineer has one assignment at a time and respects availability, shift and transition-time limits.
- Required setup, safety buffer and teardown time are included.

### Soft objectives — ranked transparently

Among valid schedules, the optimiser should minimise a weighted penalty for:

1. deferring high-priority or high-service-impact work;
2. leaving requests unscheduled;
3. disrupting already confirmed work;
4. inefficient crew movement or avoidable idle gaps; and
5. using scarce, cross-qualified engineers when a specialist alternative exists.

Weights are visible and adjustable for a scenario. That makes a recommendation auditable rather than a black box.

## Proposed architecture

```text
Requests + windows + crews
           |
           v
  Validation & conflict graph  ---> Conflict explanations
           |
           v
 Constraint solver / optimiser ---> Ranked feasible schedules
           |
           v
 Planner dashboard             ---> Approve, adjust, notify
```

- **Data layer:** CSV/JSON import for the hackathon demo; a production version would integrate with work-request, possession and workforce systems.
- **Scheduling engine:** constraint programming (for example, OR-Tools CP-SAT) is the preferred MVP approach because it naturally represents hard safety constraints and weighted trade-offs. A bounded beam-search heuristic is a useful fallback for fast “what if?” suggestions, but it must never bypass hard constraints.
- **Explainability layer:** store the failed rule(s) for every rejected placement and the score breakdown for every recommendation.
- **Dashboard:** request queue, conflict inspector, engineering-window timeline, engineer allocation and capacity view.
- **Notification stub:** export or simulate a notification after a planner approves an allocation; no automatic operational dispatch during the demo.

## Demo flow

1. Import a realistic synthetic set of maintenance requests, windows and engineer profiles.
2. Show the initial conflict list, including a double-booked sector and an unavailable specialist engineer.
3. Select a high-priority request and inspect why it cannot be scheduled as requested.
4. Compare two proposed alternatives, including constraints satisfied and scheduling trade-offs.
5. Approve one plan and show the updated engineer capacity / notification preview.

## Feasibility and scope

This is highly feasible for a hackathon when we model a representative operating slice—such as 10–30 requests, 5–10 engineering windows, several sectors and a small set of crews. Constraint programming can solve that scope quickly while producing a credible schedule.

The public MRT station-location data can support the map/sector visualisation. It does **not** contain operational possessions, crew rosters, certifications, work compatibility rules or service-impact data, so those must be represented as carefully labelled synthetic demo data unless the organisers provide them. The project should never imply that a public dataset can safely drive live rail operations.

### Deliberate MVP boundaries

- Decision support only; a human approves every proposed plan.
- Model explicit safety and operational rules; do not present a generic calendar as an optimiser.
- Use deterministic rules and a constraint solver before adding LLM features. An LLM may help turn planner notes into a structured draft request, but it must not decide feasibility.
- Start with sector-level conflicts and predefined compatibility matrices; do not attempt full network simulation.

## Team backlog

- [ ] Define the request, window, engineer and compatibility schemas.
- [ ] Prepare synthetic data with at least three compelling conflict scenarios.
- [ ] Implement validation and reason-coded conflict detection.
- [ ] Implement the optimiser and configurable priority weights.
- [ ] Build the timeline, conflict inspector and crew-capacity dashboard.
- [ ] Add schedule comparison, approval and notification preview.
- [ ] Rehearse a three-minute demo focused on conflict → explanation → alternative → approved plan.

## References

- [NEBULA X — Track 1 problem statement](https://nebulax.com.sg/#tracks)
- The official Track 1 brief lists an MRT station-locations API as a possible dataset.
