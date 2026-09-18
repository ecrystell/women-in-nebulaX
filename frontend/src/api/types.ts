export type Scenario = "A" | "B" | "C";
export type ValidationStatus = "unavailable" | "unverified" | "verified";
export type RunStatus = "accepted" | "running" | "succeeded" | "failed" | "blocked";

export type PlacementKey = { activity_id: string; access_seq: number };
export type Occupancy = { location_id: string; co_share_group: string };

export type Placement = PlacementKey & {
  week: number;
  access_night: number;
  eclo: 0 | 1;
  occupancies: Occupancy[];
};

export type ContractResult = {
  scenario: Scenario;
  contract_number: string;
  simulated_completion_date: string;
  overrun_days: number;
};

export type Schedule = {
  schedule_id: string;
  input_instance_id: string;
  scenario: Scenario;
  placements: Placement[];
  contract_results: ContractResult[];
  generated_at: string;
};

export type ValidationReport = {
  schedule_id?: string;
  status: ValidationStatus;
  feasible: boolean | null;
  message: string;
  hard_violations: Array<{ rule: string; severity: "hard" | "soft"; detail: string }>;
  soft_scores: Record<string, unknown>;
  detail: Record<string, unknown>;
};

export type ScheduleDiff = {
  baseline_schedule_id: string;
  recovered_schedule_id: string;
  placement_changes: Array<{
    key: PlacementKey;
    kind: "unchanged" | "moved" | "added" | "removed";
    changed_fields: Array<"week" | "access_night" | "eclo" | "occupancies">;
  }>;
  unchanged_count: number;
  moved_count: number;
};

export type RunView = {
  run_id: string;
  status: RunStatus;
  scenario: Scenario;
  input_instance: { instance_id: string; fixture: boolean; row_counts: Record<string, number> };
  created_at: string;
  updated_at: string;
  recovery_of_run_id?: string;
  schedule?: Schedule;
  validation_report?: ValidationReport;
  schedule_diff?: ScheduleDiff;
  problem?: { code: string; message: string };
};

export type Health = {
  service: string;
  api_version: "v1";
  status: "ok";
  validator_status: ValidationStatus;
};

export type ApiErrorResponse = {
  request_id: string;
  error: {
    code: string;
    message: string;
    field_errors: Array<{ field: string; message: string }>;
  };
};
