import type {
  ApiErrorResponse,
  CapabilityReport,
  CopilotMode,
  CopilotResponse,
  EvidenceEnvelope,
  Health,
  OrganiserEvidenceInput,
  RunView,
  ScenarioChangeDraft,
  Scenario,
  SubmissionPackageSummary
} from "./types";

export class ForRailsApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId?: string
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, init);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as ApiErrorResponse | null;
    throw new ForRailsApiError(
      payload?.error.message ?? `Request failed with status ${response.status}.`,
      response.status,
      payload?.error.code ?? "request_failed",
      payload?.request_id
    );
  }
  return response.json() as Promise<T>;
}

export const forRailsApi = {
  getHealth: () => request<Health>("/health"),
  getCapabilities: () => request<CapabilityReport>("/capabilities"),
  getRun: (runId: string) => request<RunView>(`/runs/${runId}`),
  getActivityEvidence: (runId: string, activityId: string) => request<EvidenceEnvelope>(`/runs/${runId}/evidence/activities/${encodeURIComponent(activityId)}`),
  getCapacityHotspots: (runId: string) => request<EvidenceEnvelope>(`/runs/${runId}/evidence/capacity-hotspots`),
  getHandoverEvidence: (runId: string) => request<EvidenceEnvelope>(`/runs/${runId}/evidence/handover`),
  createCopilotResponse: (runId: string, mode: CopilotMode, activityId?: string) =>
    request<CopilotResponse>(`/runs/${runId}/copilot-responses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // The API deliberately accepts an activity only for an explanation.
      // Do not leak a stale selector value into hotspot or handover requests.
      body: JSON.stringify(
        mode === "activity_explanation" ? { mode, activity_id: activityId } : { mode }
      )
    }),
  createRun: (scenario: Scenario, files: File[]) => {
    const body = new FormData();
    body.set("scenario", scenario);
    files.forEach((file) => body.append("files", file, file.name));
    return request<RunView>("/runs", { method: "POST", body });
  },
  createPublicDemoRun: () => request<RunView>("/demo-runs", { method: "POST" }),
  createPublicDemoReplay: (runId: string, draftId?: string) => request<RunView>(`/runs/${runId}/demo-recovery`, {
    method: "POST",
    ...(draftId ? { body: JSON.stringify({ draft_id: draftId }) } : {})
  }),
  createDisruptionDraft: (runId: string, text: string) =>
    request<ScenarioChangeDraft>(`/runs/${runId}/disruption-drafts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    }),
  createSubmissionPackage: (runId: string) =>
    request<SubmissionPackageSummary>(`/runs/${runId}/submission-packages`, { method: "POST" }),
  recordOrganiserEvidence: (runId: string, packageId: string, payload: OrganiserEvidenceInput) =>
    request<SubmissionPackageSummary>(`/runs/${runId}/submission-packages/${packageId}/organiser-evidence`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }),
  getExportUrl: (runId: string, filename: string) => `/api/v1/runs/${runId}/exports/${filename}`,
  getPublicScheduleUrl: (filename: string) => `/api/v1/public-schedule/${filename}`,
  getSubmissionPackageUrl: (runId: string, packageId: string) =>
    `/api/v1/runs/${runId}/submission-packages/${packageId}/download`,
  getEvidenceRecordUrl: (runId: string, packageId: string) =>
    `/api/v1/runs/${runId}/submission-packages/${packageId}/evidence-record`
};
