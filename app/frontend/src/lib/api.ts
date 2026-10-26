import type {
  EventFilters,
  EventPage,
  Job,
  DeploymentWrite,
  Project,
  ReefEvent,
  ThresholdAnalysis,
  Verdict,
} from "./types";

/**
 * Same-origin always: in dev Vite proxies /api to the backend, and in the
 * packaged app FastAPI serves this bundle itself. So there is no base URL to
 * configure and no CORS to get wrong.
 */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body
      ? { "Content-Type": "application/json", ...init?.headers }
      : init?.headers,
  });

  if (!res.ok) {
    // FastAPI puts the useful part in `detail`, which is a string for our
    // HTTPExceptions and a list of field errors for validation failures.
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body?.detail)) {
        message = body.detail
          .map((d: { loc?: unknown[]; msg?: string }) => {
            const field = d.loc?.slice(1).join(".");
            return field ? `${field}: ${d.msg}` : d.msg;
          })
          .join("; ");
      }
    } catch {
      /* a non-JSON error body is not worth failing over */
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/api/health"),

  configDefaults: () => request<Record<string, unknown>>("/api/projects/defaults"),

  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (body: {
    name: string;
    input_folder: string;
    output_folder: string;
    config: Record<string, unknown>;
    deployment: DeploymentWrite;
  }) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  updateProject: (id: number, body: Partial<Project>) =>
    request<Project>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteProject: (id: number) =>
    request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  listJobs: (projectId: number) =>
    request<Job[]>(`/api/projects/${projectId}/jobs`),
  startJob: (projectId: number) =>
    request<Job>(`/api/projects/${projectId}/jobs`, { method: "POST" }),
  getJob: (id: number) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: number) =>
    request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  resumeJob: (id: number) =>
    request<Job>(`/api/jobs/${id}/resume`, { method: "POST" }),

  listEvents: (jobId: number, filters: EventFilters = {}) => {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "") qs.set(key, String(value));
    }
    const query = qs.toString();
    return request<EventPage>(
      `/api/jobs/${jobId}/events${query ? `?${query}` : ""}`,
    );
  },
  listClasses: (jobId: number) => request<string[]>(`/api/jobs/${jobId}/classes`),
  listSpecies: (jobId: number) => request<string[]>(`/api/jobs/${jobId}/species`),
  getEvent: (id: string) => request<ReefEvent>(`/api/events/${encodeURIComponent(id)}`),

  saveReview: (
    eventId: string,
    body: {
      verdict: Verdict;
      scientific_name?: string | null;
      notes?: string | null;
      bbox?: number[] | null;
    },
  ) =>
    request<ReefEvent>(`/api/events/${encodeURIComponent(eventId)}/review`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteReview: (eventId: string) =>
    request<void>(`/api/events/${encodeURIComponent(eventId)}/review`, {
      method: "DELETE",
    }),

  thresholdAnalysis: (jobId: number) =>
    request<ThresholdAnalysis>(`/api/jobs/${jobId}/threshold-analysis`),

  exportUrl: (jobId: number, format: "coco" | "yolo") =>
    `/api/jobs/${jobId}/export/${format}`,

  /** Writes the run's Camtrap DP package into its run folder. */
  writePackage: (jobId: number) =>
    request<{ path: string; observations: number; media: number }>(
      `/api/jobs/${jobId}/package`,
      { method: "POST" },
    ),
};
