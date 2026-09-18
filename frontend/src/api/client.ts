import type {
  ApiErrorResponse,
  CopilotMode,
  CopilotResponse,
  EvidenceEnvelope,
  Health,
  OrganiserEvidenceInput,
  RunView,
  Scenario,
  SubmissionPackageSummary
} from "./types";

export class RailAccessApiError extends Error {
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
    throw new RailAccessApiError(
      payload?.error.message ?? `Request failed with status ${response.status}.`,
      response.status,
      payload?.error.code ?? "request_failed",
      payload?.request_id
    );
  }
  return response.json() as Promise<T>;
}

export const railAccessApi = {
  getHealth: () => request<Health>("/health"),
  getRun: (runId: string) => request<RunView>(`/runs/${runId}`),
  getActivityEvidence: (runId: string, activityId: string) => request<EvidenceEnvelope>(`/runs/${runId}/evidence/activities/${encodeURIComponent(activityId)}`),
  getCapacityHotspots: (runId: string) => request<EvidenceEnvelope>(`/runs/${runId}/evidence/capacity-hotspots`),
  getHandoverEvidence: (runId: string) => request<EvidenceEnvelope>(`/runs/${runId}/evidence/handover`),
  createCopilotResponse: (runId: string, mode: CopilotMode, activityId?: string) =>
    request<CopilotResponse>(`/runs/${runId}/copilot-responses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, activity_id: activityId })
    }),
  createRun: (scenario: Scenario, files: File[]) => {
    const body = new FormData();
    body.set("scenario", scenario);
    files.forEach((file) => body.append("files", file, file.name));
    return request<RunView>("/runs", { method: "POST", body });
  },
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
