import type { ApiErrorResponse, Health, RunView } from "./types";

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
  getExportUrl: (runId: string, filename: string) => `/api/v1/runs/${runId}/exports/${filename}`
};
