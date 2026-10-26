import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import {
  keys,
  useCancelJob,
  useConfigDefaults,
  useJobs,
  useProject,
  useStartJob,
} from "../lib/queries";
import { JobRow } from "../components/JobRow";
import { Button, Empty, ErrorNote, Field, Input, Spinner, cx } from "../components/ui";

/**
 * The tunables worth putting in front of someone, in the order they'd think
 * about them. Everything else the engine exposes is real but rarely touched,
 * and lives behind "All settings" — a flat dump of forty fields is how a
 * config editor becomes unusable.
 */
const PRIMARY: { key: string; label: string; hint: string }[] = [
  {
    key: "detector",
    label: "Detector",
    hint: "marine = SharkTrack, trained on real BRUVS footage. generic = stock COCO YOLO, experimental.",
  },
  {
    key: "camera_timezone",
    label: "Camera timezone",
    hint: "IANA zone the footage was filmed in, e.g. Africa/Maputo. Event times are given in it; changing it rescans.",
  },
  {
    key: "camera_clock",
    label: "Camera clock",
    hint: "local = the file holds the camera's local clock time (GoPros). utc = it holds real UTC (phones).",
  },
  {
    key: "ml_confidence_threshold",
    label: "Confidence threshold",
    hint: "Detections below this are discarded. Review some events and the run page will recommend a value.",
  },
  {
    key: "frame_sample_fps",
    label: "Frames sampled per second",
    hint: "Lower is faster. 1/s is plenty for large slow animals.",
  },
  {
    key: "min_event_seconds",
    label: "Shortest event (s)",
    hint: "Anything briefer is dropped as a flicker.",
  },
  {
    key: "merge_gap_seconds",
    label: "Merge gap (s)",
    hint: "Hits closer together than this become one event.",
  },
  {
    key: "pad_seconds",
    label: "Clip padding (s)",
    hint: "Extra footage before and after, so you see the animal arrive.",
  },
];

/** Motion-gate controls. Only meaningful when the pre-filter is switched on. */
const MOTION_ONLY_KEYS = new Set([
  "min_blob_area",
  "persistence_frames",
  "bg_subtractor",
  "detect_shadows",
  "bg_history",
  "mog2_var_threshold",
  "morph_kernel_size",
  "warmup_frames",
]);

const CHOICES: Record<string, string[]> = {
  detector: ["marine", "generic"],
  detector_backend: ["onnx", "ultralytics"],
  camera_clock: ["local", "utc"],
  bg_subtractor: ["MOG2", "KNN"],
};

export function ProjectDetail() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: project, isLoading } = useProject(id);
  const { data: defaults } = useConfigDefaults();
  const { data: jobs } = useJobs(id);
  const startJob = useStartJob(id);
  const cancelJob = useCancelJob(id);

  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [showAll, setShowAll] = useState(false);

  // The saved config only holds what was overridden, so it's layered onto the
  // engine's defaults to get the values actually in force.
  const effective = useMemo(
    () => ({ ...(defaults ?? {}), ...(project?.config ?? {}) }),
    [defaults, project],
  );
  const values = draft ?? effective;
  const dirty = draft !== null;

  const save = useMutation({
    mutationFn: () => {
      // Send only what differs from the defaults — storing the whole blob
      // would freeze this project against future default changes.
      const diff: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(values)) {
        if (JSON.stringify(value) !== JSON.stringify(defaults?.[key])) {
          diff[key] = value;
        }
      }
      return api.updateProject(id, { config: diff });
    },
    onSuccess: () => {
      setDraft(null);
      queryClient.invalidateQueries({ queryKey: keys.project(id) });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.deleteProject(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.projects });
      navigate("/");
    },
  });

  if (isLoading) return <Spinner label="Reading project" />;
  if (!project) return <Empty title="Project not found" />;

  const activeJob = jobs?.find(
    (j) => j.status === "running" || j.status === "pending",
  );

  const setValue = (key: string, value: unknown) =>
    setDraft({ ...values, [key]: value });

  // Motion knobs are noise unless the pre-filter they tune is switched on.
  const prefilterOn = Boolean(values["motion_prefilter"]);
  const otherKeys = Object.keys(effective)
    .filter((k) => !PRIMARY.some((f) => f.key === k))
    .filter((k) => prefilterOn || !MOTION_ONLY_KEYS.has(k))
    .sort();

  return (
    <div className="rise space-y-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <Link to="/" className="legend hover:text-signal">
            ← Projects
          </Link>
          <h1 className="mt-1 truncate text-2xl font-semibold tracking-tight">
            {project.name}
          </h1>
          <p className="mt-1 truncate font-mono text-xs text-faint">
            {project.input_folder} → {project.output_folder}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {activeJob ? (
            <Button variant="danger" onClick={() => cancelJob.mutate(activeJob.id)}>
              Stop run
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => startJob.mutate()}
              disabled={startJob.isPending}
            >
              {startJob.isPending ? "Starting…" : "Scan footage"}
            </Button>
          )}
        </div>
      </div>

      <ErrorNote error={startJob.error} />

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="legend">Runs</h2>
          {jobs?.length ? (
            <span className="legend">{jobs.length} total</span>
          ) : null}
        </div>
        {!jobs?.length ? (
          <Empty title="Nothing scanned yet">
            Press <strong className="text-dim">Scan footage</strong> to work
            through the folder. You can watch progress here and review events as
            soon as the run finishes.
          </Empty>
        ) : (
          <div className="space-y-2">
            {jobs.map((job) => (
              <JobRow key={job.id} job={job} onCancel={(jid) => cancelJob.mutate(jid)} />
            ))}
          </div>
        )}
      </section>

      <section className="panel p-5">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-medium">Scan settings</h2>
            <p className="mt-0.5 text-xs text-faint">
              Defaults favour recall — they over-flag rather than miss an animal.
              Changes apply to the next run.
            </p>
          </div>
          {dirty && (
            <div className="flex shrink-0 gap-2">
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Revert
              </Button>
              <Button
                size="sm"
                variant="primary"
                onClick={() => save.mutate()}
                disabled={save.isPending}
              >
                Save
              </Button>
            </div>
          )}
        </div>

        <ErrorNote error={save.error} />

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {PRIMARY.map((field) => (
            <ConfigField
              key={field.key}
              name={field.key}
              label={field.label}
              hint={field.hint}
              value={values[field.key]}
              fallback={defaults?.[field.key]}
              onChange={(v) => setValue(field.key, v)}
            />
          ))}
        </div>

        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="legend mt-5 hover:text-signal"
        >
          {showAll ? "− Hide" : "+ Show"} all settings ({otherKeys.length})
        </button>

        {showAll && (
          <div className="mt-4 grid gap-4 border-t border-rule pt-4 md:grid-cols-2 xl:grid-cols-3">
            {otherKeys.map((key) => (
              <ConfigField
                key={key}
                name={key}
                label={key.replace(/_/g, " ")}
                value={values[key]}
                fallback={defaults?.[key]}
                onChange={(v) => setValue(key, v)}
              />
            ))}
          </div>
        )}
      </section>

      <section className="flex items-center justify-between gap-4 border-t border-rule pt-5">
        <p className="text-xs text-faint">
          Deleting removes this project's runs and labels from the database.
          Clips and thumbnails on disk are left alone.
        </p>
        <Button
          variant="danger"
          size="sm"
          onClick={() => {
            if (confirm(`Delete "${project.name}" and all its labels?`)) {
              remove.mutate();
            }
          }}
        >
          Delete project
        </Button>
      </section>
    </div>
  );
}

function ConfigField({
  name,
  label,
  hint,
  value,
  fallback,
  onChange,
}: {
  name: string;
  label: string;
  hint?: string;
  value: unknown;
  fallback: unknown;
  onChange: (value: unknown) => void;
}) {
  const choices = CHOICES[name];
  const reference = value ?? fallback;

  if (choices) {
    return (
      <Field label={label} hint={hint}>
        <div className="flex flex-wrap gap-1">
          {choices.map((choice) => (
            <button
              key={choice}
              type="button"
              onClick={() => onChange(choice)}
              className={cx(
                "rounded-[3px] border px-2.5 py-1 font-mono text-xs transition-colors",
                value === choice
                  ? "border-signal/60 bg-signal/15 text-signal"
                  : "border-rule text-dim hover:border-rule-hi hover:text-read",
              )}
            >
              {choice}
            </button>
          ))}
        </div>
      </Field>
    );
  }

  if (typeof reference === "boolean") {
    return (
      <Field label={label} hint={hint}>
        <button
          type="button"
          onClick={() => onChange(!value)}
          className={cx(
            "flex items-center gap-2 rounded-[3px] border px-2.5 py-1.5 text-xs transition-colors",
            value
              ? "border-signal/60 bg-signal/10 text-signal"
              : "border-rule text-faint hover:text-dim",
          )}
        >
          <span
            className={cx(
              "h-2 w-2 rounded-full",
              value ? "bg-signal" : "bg-rule-hi",
            )}
          />
          {value ? "On" : "Off"}
        </button>
      </Field>
    );
  }

  if (typeof reference === "number") {
    return (
      <Field label={label} hint={hint}>
        <Input
          type="number"
          step="any"
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
      </Field>
    );
  }

  // Lists and free-form objects: shown read-only rather than half-editable.
  if (typeof reference === "object" && reference !== null) {
    return (
      <Field label={label} hint={hint}>
        <div className="truncate rounded-[3px] border border-rule bg-abyss/40 px-2.5 py-1.5 font-mono text-xs text-faint">
          {JSON.stringify(reference)}
        </div>
      </Field>
    );
  }

  return (
    <Field label={label} hint={hint}>
      <Input
        className="font-mono text-xs"
        value={value === null || value === undefined ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      />
    </Field>
  );
}
