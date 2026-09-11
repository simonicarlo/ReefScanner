// Mirrors reefscanner/app/schemas.py. Kept hand-written rather than generated
// from the OpenAPI doc: the surface is small, and a generator would be one
// more build step between an endpoint changing and the type changing.

export type Verdict = "TP" | "FP" | "unsure";

export const VERDICTS: Verdict[] = ["TP", "FP", "unsure"];

export type JobStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "cancelled";

export const TERMINAL: JobStatus[] = ["done", "failed", "cancelled"];

export interface Project {
  id: number;
  name: string;
  input_folder: string;
  output_folder: string;
  config: Record<string, unknown>;
  created_at: string;
  job_count: number;
}

export interface Job {
  id: number;
  project_id: number;
  status: JobStatus;
  progress: number;
  message: string;
  videos_total: number;
  videos_done: number;
  events_found: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface Label {
  verdict: Verdict;
  species: string | null;
  notes: string | null;
  tight_bbox: number[] | null;
  updated_at: string;
}

export interface ReefEvent {
  id: number;
  job_id: number;
  event_id: string;
  source_video: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  peak_timestamp: number;
  peak_score: number;
  peak_bbox: number[] | null;
  motion_score: number | null;
  ml_confidence: number | null;
  detected_class: string | null;
  start_timestamp: string;
  frame_width: number | null;
  frame_height: number | null;
  clip_url: string | null;
  thumbnail_url: string | null;
  frame_url: string | null;
  label: Label | null;
}

export interface EventPage {
  items: ReefEvent[];
  total: number;
  limit: number;
  offset: number;
  n_labeled: number;
  n_tp: number;
  n_fp: number;
}

/** What the /ws/jobs socket pushes. A subset of Job, by design. */
export interface JobProgress {
  job_id: number;
  status: JobStatus;
  progress: number;
  message: string;
  videos_total: number;
  videos_done: number;
  events_found: number;
  error: string | null;
}

export interface EventFilters {
  detected_class?: string;
  min_confidence?: number;
  labeled?: boolean;
  verdict?: Verdict;
  source_video?: string;
  limit?: number;
  offset?: number;
}

export interface ThresholdPoint {
  threshold: number;
  kept: number;
  confirmed_kept: number;
  rejected_kept: number;
  confirmed_lost: number;
  precision: number;
}

export interface ThresholdAnalysis {
  labeled: number;
  confirmed: number;
  rejected: number;
  undecided: number;
  unscored: number;
  reliable: boolean;
  scan_threshold: number | null;
  recommended: number | null;
  recommendation: string;
  points: ThresholdPoint[];
}
