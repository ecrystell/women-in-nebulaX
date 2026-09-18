import type { RunView, ValidationReport } from "../types";

/** Public-fixture UI data only. It is deliberately not validator-verified. */
export const MOCK_API_VERSION = "v1";

/** A typed local-check example for UI development; it is not organiser evidence. */
export const localEvidenceMockViolation: ValidationReport["hard_violations"][number] = {
  rule: "topology",
  severity: "hard",
  detail: "A001 occupancy footprint is missing one required location.",
  activity_ids: ["A001"],
  location_ids: ["SEC:BET:S15_S16:EB"],
  week: 22,
  co_share_group: "b4",
  derived_footprint: ["SEC:BET:S15_S16:EB", "PLAT:BET:S15:EB"],
  input_values: {
    expected_location_count: 2,
    observed_location_count: 1,
    missing_location_count: 1,
    unexpected_location_count: 0
  }
};

export const publicFixtureMockRun: RunView = {
  run_id: "mock-public-a",
  status: "succeeded",
  scenario: "A",
  input_instance: {
    instance_id: "public-fixture",
    fixture: true,
    row_counts: { lines: 2, stations: 20, sectors: 18, location_supply: 76, buffer_locations: 3, parameters: 2, projects: 14, activities: 54 }
  },
  created_at: "2026-09-18T00:00:00Z",
  updated_at: "2026-09-18T00:00:00Z",
  schedule: {
    schedule_id: "mock-public-a-schedule",
    input_instance_id: "public-fixture",
    scenario: "A",
    generated_at: "2026-09-18T00:00:00Z",
    placements: [{ activity_id: "A001", access_seq: 1, week: 22, access_night: 3, eclo: 0, occupancies: [{ location_id: "SEC:BET:S15_S16:EB", co_share_group: "b4" }, { location_id: "PLAT:BET:S15:EB", co_share_group: "b2" }] }],
    contract_results: [{ scenario: "A", contract_number: "C001", simulated_completion_date: "2027-06-13", overrun_days: 0 }]
  },
  validation_report: {
    schedule_id: "mock-public-a-schedule",
    status: "unverified",
    feasible: null,
    message: "Mock public-fixture candidate. It has not run through the organiser validator.",
    hard_violations: [],
    soft_scores: {},
    detail: {}
  },
  schedule_diff: { baseline_schedule_id: "mock-public-a-schedule", recovered_schedule_id: "mock-public-a-schedule", placement_changes: [], unchanged_count: 1, moved_count: 0 },
  submission_packages: []
};
