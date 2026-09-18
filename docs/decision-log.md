# RailAccess AI decision log

**Status:** prepared for the first team decision session. Entries marked **Proposed** are review prompts, not settled product policy.  
**Decision precedence:** official PS1 specification → organiser validator/mentor clarification → approved entry here → implementation convenience.

## Session record

| Field | Fill in during the session |
| --- | --- |
| Date/time | |
| Attendees | Role 1: ___; Role 2: ___; Role 3: ___; Role 4: ___ |
| Facilitator | |
| Decision-log editor | |
| Validator contact / mentor | |

## 35-minute agenda

1. **5 min:** confirm the validator contact, command availability, and deadline for its package.
2. **10 min:** approve or edit the canonical object meanings in `docs/data-contract.md`.
3. **10 min:** review high-risk rows R04–R10 and R15–R16 in `docs/rule-matrix.md`.
4. **5 min:** lock the MVP boundary and explicit non-goals.
5. **5 min:** assign owners, next actions, and any mentor questions.

## Decisions

| ID | Topic | Proposed decision | Status | Approval / notes |
| --- | --- | --- | --- | --- |
| D-001 | Canonical input | Use `InputInstance` as the public name; map its table payload to the existing `InstanceBundle` model. | Proposed | |
| D-002 | Canonical placement | One `Placement` contains one access assignment and a list of location-specific occupancies/co-share groups. | Proposed | |
| D-003 | Canonical schedule | A `Schedule` contains one scenario only and never carries a self-declared feasibility flag. | Proposed | |
| D-004 | Validation evidence | Only the organiser adapter can return `verified`; local schema/export checks return `unverified`. | Proposed | |
| D-005 | Recovery scope | MVP recovery accepts confirmed supply overrides and exact locked placements; it does not accept manual activity/priority/ECLO edits. | Proposed | |
| D-006 | Change measurement | `ScheduleDiff` keys comparable sequences by `(activity_id, access_seq)`; ECLO may legitimately add/remove sequences, while occupancy or co-share changes count as moved work. | Proposed | |
| D-007 | API compatibility | Public API schemas use `snake_case`, ISO dates, explicit `0/1` ECLO, and named versioning before frontend mocks are published. | Proposed | |
| D-008 | Data retention | Default: no persistence of organiser/hidden input files beyond a single active run. | Proposed | |
| D-009 | MVP included | A/B/C candidate schedules, organiser validation evidence, upload/export, timeline, recovery sandbox, and grounded explanations. | Proposed | |
| D-010 | MVP excluded until core works | Accounts, saved history, autonomous AI schedule changes, duration prediction, generic chat, crew allocation, and new external data stores. | Proposed | |
| D-011 | Repository deliverable | Confirm whether the final organiser requirement is GitLab, GitHub, or both; current repository remote does not settle the organiser rule. | Open — organiser confirmation required | |

## Validator decision gate

| Question | Current answer | Owner | Due / evidence needed |
| --- | --- | --- | --- |
| Is the official validator package available? | No runnable package is in the public PS1 repository or this project. | Role 2 | Ask mentor using `docs/VALIDATOR_REQUEST.md`. |
| What command invokes it? | Unknown. | Role 2 | Exact CLI/API command and input directory layout. |
| What report shape and tags does it emit? | Sample docs show `closure`, `capacity`, `planned_date`, and `eclo`; full tag vocabulary is unknown. | Role 2 | Machine-readable report and a public-sample run. |
| What is the public-instance baseline? | Not established; sample files are not a validator run in this repository. | Role 2 + Role 3 | Validator output for A, B, and C candidates. |

## MVP acceptance gate

The team may build in parallel after approving D-001 through D-010. The following are the non-negotiable demo gates:

- Every input activity has its full workload scheduled.
- Each A, B, and C output has its own three required CSVs.
- The organiser validator reports zero hard violations before the UI calls a schedule feasible.
- The app accepts a fresh eight-CSV hidden instance without persisting it by default.
- The recovery view visibly reports preserved versus moved work and still goes through validation.

## Action register

| Action | Owner | Definition of done | Status |
| --- | --- | --- | --- |
| Approve/revise canonical object definitions | Roles 1–4 | D-001 through D-007 have accepted wording and named approvers. | Open |
| Approve high-risk rule interpretations | Role 2, reviewed by Role 3 | R04–R10 and R15–R16 have no unresolved internal ambiguity. | Open |
| Request organiser validator | Role 2 | All five items in `VALIDATOR_REQUEST.md` are requested and response is recorded. | Open |
| Establish API/mock package | Role 4 | Versioned `Schedule`, `ValidationReport`, and `ScheduleDiff` mocks available to Role 1. | Open |
| Create controller workflow | Role 1 | One-page flow identifies what a controller can inspect, lock, change, and confirm. | Open |
| Create CP-SAT model sketch | Role 3 | Variables, candidate data, hard constraints, and output conversion reviewed against this contract. | Open |
