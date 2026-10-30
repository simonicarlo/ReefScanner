// Mirrors reefscanner/app/schemas.py. Kept hand-written rather than generated
// from the OpenAPI doc: the surface is small, and a generator would be one
// more build step between an endpoint changing and the type changing.

/** TP; FP with nothing there; FP with something else there; unsure. */
export const VERDICTS = ["TP", "FP", "FP-other", "unsure"] as const;

export type Verdict = (typeof VERDICTS)[number];

export type JobStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "cancelled";

export const TERMINAL: JobStatus[] = ["done", "failed", "cancelled"];

/** The Camtrap DP deployment a project is: where and how it was filmed. */
export interface DeploymentWrite {
  latitude: number;
  longitude: number;
  location_name?: string | null;
  camera_depth?: number | null;
  bait_use?: boolean | null;
  comments?: string | null;
}

export interface Deployment extends DeploymentWrite {
  deployment_id: string;
  start: string | null;
  end: string | null;
  /** Some video's start time had to be guessed from the file. */
  timestamp_issues: boolean;
}

/** The roles Camtrap DP allows a contributor. */
export const CONTRIBUTOR_ROLES = [
  "contributor",
  "contact",
  "principalInvestigator",
  "rightsHolder",
  "publisher",
] as const;

export type ContributorRole = (typeof CONTRIBUTOR_ROLES)[number];

/** A person or organisation behind the data (Camtrap `contributors`). */
export interface Contributor {
  title: string;
  email?: string | null;
  organization?: string | null;
  role: ContributorRole;
}

/** What a project's exported packages say about the study and its team. */
export interface PackageMetadata {
  project: { title: string; description?: string | null };
  contributors: Contributor[];
}

/** The person using this laptop. */
export interface Settings {
  name: string | null;
  email: string | null;
  organization: string | null;
  /** Who reviews are signed as: name, or the login name while unset. */
  signed_as: string;
}

export const APPEARANCE_MODES = ["system", "light", "dark"] as const;
export type AppearanceMode = (typeof APPEARANCE_MODES)[number];

/** How the app looks on this laptop. */
export interface Appearance {
  mode: AppearanceMode;
  translucency: boolean;
}

/** Where a project's review stands: its latest run with events. */
export interface RunSummary {
  job_id: number;
  events: number;
  reviewed: number;
  confirmed: number;
  /** "Nothing there" and "something else" together. */
  rejected: number;
  /** Its most recent confirmed event's frame, otherwise its first event's. */
  cover_url: string | null;
}

export interface Project {
  id: number;
  name: string;
  input_folder: string;
  output_folder: string;
  config: Record<string, unknown>;
  created_at: string;
  job_count: number;
  latest_run: RunSummary | null;
  package_metadata: PackageMetadata;
  deployment: Deployment;
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
  /** The package folder an import run came from; null for a scan. */
  source: string | null;
}

export interface Review {
  verdict: Verdict;
  /** The species for a TP; what it was instead for an FP-other. */
  scientific_name: string | null;
  notes: string | null;
  /** [x, y, width, height] as fractions of the frame, each 0 to 1. */
  bbox: number[] | null;
  reviewed_at: string | null;
}

export interface ReefEvent {
  /** The Camtrap eventID. Contains ":", so encode it in URLs. */
  id: string;
  job_id: number;
  source_video: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  peak_seconds: number;
  /** Wall-clock start, with the camera timezone's offset. */
  start_time: string;
  confidence: number | null;
  detected_class: string | null;
  scientific_name: string | null;
  /** [x, y, width, height] as fractions of the frame, each 0 to 1. */
  bbox: number[] | null;
  clip_url: string;
  frame_url: string;
  review: Review | null;
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
