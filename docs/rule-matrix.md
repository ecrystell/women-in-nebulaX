# RailAccess AI rule matrix

**Status:** approved v0.1 — local preflight coverage is implemented where the published CSV contract contains enough evidence; replace `TBD` items with organiser-validator evidence.
**Rule owner:** Role 2. **Constraint implementation:** Role 3. **Integration/display:** Role 4 / Role 1.

The official brief and organiser validator outrank this matrix. A validator tag is recorded only when published or observed; do not invent missing tags. Published/observed tags currently include `closure`, `capacity`, `planned_date`, and `eclo`.

| ID | Official requirement | Source columns | Derived state / enforcement | Validator tag | Phase 1 minimal fixture | Accountable owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | All activities are fully delivered; standard access yields 1.0 and ECLO yields 1.5. | `08.total_accesses`; `SCHEDULE_ACCESS.eclo` | Sum yields by `activity_id`; reject omitted or under-delivered activity. | TBD from organiser | One activity needs 2 accesses but receives one standard placement. | Role 2 | Implemented locally |
| R02 | Work cannot begin before its planned start week. | `06.horizon_start`, `08.planned_start_date`, placement `week` | Convert date to planning week; minimum placement week is the activity start week. | `planned_date` is published for B overrun; start-date tag TBD | One placement in the week before an activity's start date. | Role 2 | Implemented locally |
| R03 | A work section occupies every required tunnel and platform sector from book-in through book-out. | `02_STATIONS`, `03_SECTORS`, `04_LOCATION_SUPPLY`, `08.start_location_id`, `08.end_location_id` | Expand an activity route into ordered `SEC` and `PLAT` locations on its line/bound. | TBD | Cross-station activity is missing an intermediate SEC or PLAT occupancy. | Role 2 | Implemented locally |
| R04 | Live/Non-live(Consist) work applies the published buffer; Non-live(Others) has none. Buffers and external work may not overlap. | `05_BUFFER_LOCATION`, R03 route footprint, project nature, occupancies | Expand buffer footprint and exclude other possession spans/buffers unless legal co-sharing applies. | `closure` is observed; buffer-specific tag TBD | Consist work with a one-sector buffer and another non-shared activity inside it. | Role 2 | Footprint implemented; cross-group order needs organiser evidence |
| R05 | Live work mirrors onto the opposite bound. | `05.opposite_bound_required`, project nature, R03 footprint | Add opposite-bound closure footprint for every Live location. | `closure` | Live EB work conflicts with WB work at its mirrored location. | Role 2 | Footprint implemented; collision timing unresolved |
| R06 | A Live activity at H01–H02 also closes the other line's H01–H02 tunnel and H01/H02 platforms; non-Live work does not cross lines. | `02.is_interchange`, `03_SECTORS`, project nature, R03 footprint | Add cross-line H01/H02 Live closure only; keep PC/PM/C line-local. | `closure` | Live ALP H01–H02 work conflicts with BET H01/H02 occupancy; non-Live equivalent does not. | Role 2 | Footprint implemented; collision timing unresolved |
| R07 | A location possession is either one PM alone, one PC with up to three C, or up to four C. | `07.access_type`, occupancy `(location_id, week, co_share_group)` | Group activities by possession and count/match access types. | TBD | PM co-shared with any activity; PC with four C; five C together. | Role 2 | Implemented locally |
| R08 | Same location/week/co-share group is one possession and is exempt from each other's buffers; different groups are separate possessions. | occupancy rows; R04 buffer footprint | Treat a matching group as a legal shared span only if R07 passes; apply buffers across groups. | `closure` or co-share tag TBD | Same group avoids buffer collision; different groups collide. | Role 2 | Group semantics implemented; cross-group timing unresolved |
| R09 | A contract/type uses no more distinct access-night values in a week than its allocation. | `07.number_of_maximum_access_per_week`, `07.activity_type`, `08.contract_number`, placements | Count distinct `access_night` by `(contract_number, activity_type, week)`. | TBD | Cap 3 contract uses nights 1, 2, 3, and 4 in one week. | Role 2 | Implemented locally |
| R10 | A contract has no more concurrent distinct activities on an access night than its workfront limit. | `07.number_of_workfronts`, `07.activity_type`, `08.contract_number`, placements | Count distinct `activity_id` by `(contract_number, activity_type, week, access_night)`. | TBD | Workfront 1 contract schedules two activity IDs on the same access night. | Role 2 | Implemented locally |
| R11 | Scenario A: nominal location supply is rigid; zero excess capacity permitted. | `04.supply_capacity`, occupancy possession groups, scenario | Count separate possessions by `(location_id, week)` and require count ≤ supply. | `capacity` | Capacity 1 location has two separate legal possession groups in A. | Role 2 | Implemented locally |
| R12 | Scenario A: ECLO is hard-forbidden. | scenario, placement `eclo` | Reject any A placement with `eclo = 1`. | `eclo` | Otherwise valid A schedule contains one ECLO placement. | Role 2 | Implemented locally |
| R13 | Scenario B: no simulated completion after planned completion date. | `06.horizon_start`, `07.planned_completion_date`, activity completion derived from placements, `RESULTS` | Require all contract completion dates ≤ planned completion dates. | `planned_date` | B schedule completes one contract one week late. | Role 2 | Implemented locally |
| R14 | Scenario B: supply excess is allowed but counted; ECLO is allowed and counted. | R11 capacity count, placement `eclo` | Compute excess access-nights and ECLO nights for score; no hard cap on excess. | `capacity` is soft-scored; exact report tag confirmed by validator | B schedule uses two possessions at capacity 1 and one ECLO; assert metrics, not hard failure. | Role 2 | Implemented locally |
| R15 | Scenario C: no more than one excess access-night per location/week. | R11 capacity count, scenario | Require possessions ≤ nominal supply + 1; count allowed excess in score. | `capacity` | Capacity 1 location has three separate possessions in C. | Role 2 | Implemented locally |
| R16 | Scenario C: ECLO for each line fits one continuous window of at most two calendar weeks; cross-line Live ECLO fits both affected-line windows. | placement `eclo`, R03/R05/R06 line footprint, scenario | Determine affected line(s), collect ECLO weeks, require each line's span ≤ 2 weeks. | `eclo` or continuity tag TBD | Same-line ECLO in weeks 1 and 4; cross-line Live ECLO outside one line's window. | Role 2 | Implemented locally |
| R17 | Scenario A objective is priority-weighted planned-completion overrun; B objective is `7 × excess + 5 × ECLO`; C combines both. | `07.contract_priority`, `08.activity_priority`, planned dates, completion, R11/R14 counts, eclo | Calculate published score terms exactly; hard constraints are never hidden by score. | Score field names/tag TBD | Hand-built schedule with known P1/P2/P3 overrun, excess, and ECLO totals. | Role 3 | Local diagnostics implemented; confirm score semantics with organiser |
| R18 | Required submissions contain exact schemas and one scenario per result file. | canonical `Schedule`, three output files | Flatten placements and contract results; enforce exact ordered headers and scenario consistency. | Parse error/tag TBD | Wrong header, mixed B/C results, or missing occupancy row. | Role 2 | Implemented locally |
| R19 | Only organiser-validator evidence can establish feasibility. | validator invocation and report | Preserve unavailable/unverified/verified distinction and raw evidence. | Organiser report itself | Internal rule checks pass while validator is unavailable; report remains unverified. | Role 2 | Implemented locally |

## Published scoring facts

These values are locked by the official brief; Role 3 may choose search mechanics and tie-breakers, but may not change them.

- Contract-priority overrun base weights are P1 = `100`, P2 = `10`, P3 = `1` per overrun day.
- Activity-priority adjustments are P1 = `+0.3`, P2 = `+0.2`, P3 = `+0.0` within that contract's tier.
- Scenario A score is priority-weighted overrun; ECLO and supply excess are not legal A levers.
- Scenario B score is `7 × excess_access_nights_total + 5 × eclo_nights_total`; planned-date overrun is hard-forbidden.
- Scenario C combines the A overrun term with the same `7 × excess` and `5 × ECLO` terms, subject to its hard `+1` capacity and ECLO-window policies.

## Review checklist

Before marking a row implemented, the accountable owner must provide all of the following:

1. A citation to the official PS1 rule or an organiser clarification.
2. Deterministic domain logic with no UI-only or solver-only interpretation.
3. The named minimal fixture and an automated assertion.
4. A confirmed validator tag/report example when the organiser tool is available.
5. A note in `docs/decision-log.md` if the implementation resolves an ambiguity.

## Known interpretation guardrails

- Capacity measures distinct possession groups per location/week, not raw activity count.
- Co-sharing is legal only after the PM/PC/C mix rule passes; it is not a generic buffer bypass.
- Live is a rail-power/closure property, not a staff resource.
- `access_night` is a per-contract/type/week allocation index, not a globally shared location slot.
- Scenario B's flexible supply is a score trade-off, whereas Scenario A's supply limit and Scenario C's `+1` ceiling are hard policies.
- The public data package and sample output are useful fixtures, not proof that a new candidate schedule is feasible.
