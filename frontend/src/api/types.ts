export type Scenario = "A" | "B" | "C";
export type ValidationStatus = "unavailable" | "unverified" | "verified";
export type RunStatus = "accepted" | "running" | "succeeded" | "failed" | "blocked";
export type OrganiserReportedOutcome = "unknown" | "accepted" | "rejected";

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
  hard_violations: Array<{
    rule: string;
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
  }>;
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
  score_delta?: Record<string, number>;
  completion_delta?: Record<string, number>;
};

export type FeatureCapability = {
  available: boolean;
  code?: string | null;
  message: string;
};

export type CapabilityReport = {
  scenarios: Array<FeatureCapability & { scenario: Scenario }>;
  recovery: FeatureCapability;
  public_demo_recovery: FeatureCapability;
  disruption_drafts: FeatureCapability;
};

export type ScenarioChange = {
  change_id: string;
  base_schedule_id: string;
  scenario: Scenario;
  supply_overrides: Array<{ location_id: string; week: number; supply_capacity: number }>;
  locked_placements: PlacementKey[];
  requested_by: string;
  confirmed_at?: string | null;
  rationale?: string;
};

export type ScenarioChangeDraft = {
  draft_id: string;
  change: ScenarioChange;
  assumptions: string[];
  unresolved_references: string[];
  field_errors: Array<{ field: string; message: string }>;
  evidence_version: "1";
  status: "ready" | "needs_review";
};

export type OrganiserEvidenceInput = {
  attempt_number: number;
  submitted_at: string;
  reported_outcome: OrganiserReportedOutcome;
  report_reference?: string;
  report_sha256?: string;
  note?: string;
};

export type OrganiserEvidence = OrganiserEvidenceInput & { recorded_at: string };

export type SubmissionPackageSummary = {
  package_id: string;
  run_id: string;
  schedule_id: string;
  scenario: Scenario;
  created_at: string;
  build_commit: string;
  organiser_evidence?: OrganiserEvidence;
};

export type RunView = {
  run_id: string;
  status: RunStatus;
  scenario: Scenario;
  input_instance: { instance_id: string; fixture: boolean; row_counts: Record<string, number> };
  created_at: string;
  updated_at: string;
  recovery_of_run_id?: string | null;
  scenario_change?: ScenarioChange | null;
  schedule?: Schedule;
  validation_report?: ValidationReport;
  schedule_diff?: ScheduleDiff;
  problem?: { code: string; message: string };
  demo: boolean;
  demo_notice?: string | null;
  submission_packages: SubmissionPackageSummary[];
};

export type Health = {
  service: string;
  api_version: "v1";
  status: "ok";
  validator_status: ValidationStatus;
};

export type EvidenceValidation = {
  status: ValidationStatus;
  feasible: boolean | null;
  hard_violation_count: number;
  message: string;
};

export type CapacityHotspot = {
  location_id: string;
  location_label: string;
  week: number;
  possession_group_count: number;
  supply_capacity: number;
  allowed_possessions: number;
  excess_access_nights: number;
  utilisation: number;
  co_share_groups: string[];
  activity_ids: string[];
};

export type EvidenceEnvelope = {
  evidence_version: "1";
  run_id: string;
  schedule_id: string;
  scenario: Scenario;
  generated_at: string;
  validation: EvidenceValidation;
  payload:
    | { kind: "activity"; activity_id: string; contract_number: string; activity_type: string; access_type: string; nature_of_activity: string; total_accesses_required: number; planned_start_week: number; predecessor_activity_id?: string; placements: Placement[]; closure_footprint: string[]; closure_footprint_labels: string[]; placement_summaries: string[]; contract_result?: ContractResult; local_findings: ValidationReport["hard_violations"] }
    | { kind: "capacity_hotspots"; hotspots: CapacityHotspot[] }
    | { kind: "handover"; placement_count: number; scheduled_activity_count: number; contract_results: ContractResult[]; local_score_components: Record<string, unknown>; top_hotspots: CapacityHotspot[] };
};

export type CopilotMode = "activity_explanation" | "capacity_hotspots" | "handover_summary";
export type CopilotResponse = {
  mode: CopilotMode;
  answer: string;
  evidence: EvidenceEnvelope;
  model: string;
  generated_at: string;
  verification_disclaimer: string;
};

export type ApiErrorResponse = {
  request_id: string;
  error: {
    code: string;
    message: string;
    field_errors: Array<{ field: string; message: string }>;
  };
};
