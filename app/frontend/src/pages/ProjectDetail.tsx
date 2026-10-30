import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import {
  keys,
  useCancelJob,
  useConfigDefaults,
  useJobs,
  useProject,
  useResumeJob,
  useStartJob,
} from "../lib/queries";
import { tailPath } from "../lib/format";
import { useBackdrop } from "../lib/backdrop";
import { JobRow } from "../components/JobRow";
import { MetadataPanel } from "../components/MetadataPanel";
import { PageHeader } from "../components/PageHeader";
import { SegmentedControl } from "../components/SegmentedControl";
import { Switch } from "../components/Switch";
import { Button, Empty, ErrorNote, Field, Input, Panel, Spinner } from "../components/ui";
import styles from "./ProjectDetail.module.css";

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
  const resumeJob = useResumeJob(id);

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

  // The project's cover frame, blurred behind the window.
  useBackdrop(project?.latest_run?.cover_url);

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
    <div className={styles.page}>
      <PageHeader
        back={{ to: "/", label: "Projects" }}
        title={project.name}
        subtitle={
          <span className={styles.folders} title={`${project.input_folder} → ${project.output_folder}`}>
            {tailPath(project.input_folder)} → {tailPath(project.output_folder)}
          </span>
        }
        actions={
          activeJob ? (
            <Button variant="danger" onClick={() => cancelJob.mutate(activeJob.id)}>
              Stop run
            </Button>
          ) : (
            <Button variant="primary" onClick={() => startJob.mutate()} disabled={startJob.isPending}>
              {startJob.isPending ? "Starting…" : "Scan footage"}
            </Button>
          )
        }
      />

      <ErrorNote error={startJob.error} />
      <ErrorNote error={cancelJob.error} />
      <ErrorNote error={resumeJob.error} />
      <ErrorNote error={remove.error} />

      <Panel title="Runs" aside={jobs?.length ? `${jobs.length} in total` : undefined}>
        {!jobs?.length ? (
          <Empty title="Nothing scanned yet">
            Press Scan footage to work through the folder. You can watch progress here
            and review events as soon as the run finishes.
          </Empty>
        ) : (
          <div>
            {jobs.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onCancel={(jid) => cancelJob.mutate(jid)}
                onResume={(jid) => resumeJob.mutate(jid)}
              />
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Scan settings"
        description="Defaults favour recall: they over-flag rather than miss an animal. Changes apply to the next run."
        aside={
          dirty && (
            <>
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Revert
              </Button>
              <Button size="sm" variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>
                Save
              </Button>
            </>
          )
        }
      >
        <ErrorNote error={save.error} />

        <div className={styles.settings}>
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

        <Button
          variant="ghost"
          size="sm"
          className={styles.more}
          onClick={() => setShowAll((v) => !v)}
          aria-expanded={showAll}
        >
          {showAll ? "Hide other settings" : `Show all settings (${otherKeys.length} more)`}
        </Button>

        {showAll && (
          <div className={`${styles.settings} ${styles.others}`}>
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
      </Panel>

      <MetadataPanel projectId={id} saved={project.package_metadata} />

      <div className={styles.danger}>
        <p>
          Deleting removes this project's runs and labels from the database. Clips and
          thumbnails on disk are left alone.
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
      </div>
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
      <Field label={label} hint={hint} group>
        <div>
          <SegmentedControl
            label={label}
            options={choices.map((choice) => ({ value: choice, label: choice }))}
            value={typeof value === "string" ? value : ""}
            onChange={onChange}
          />
        </div>
      </Field>
    );
  }

  if (typeof reference === "boolean") {
    return (
      <Field label={label} hint={hint} group>
        <Switch label={label} hideLabel checked={Boolean(value)} onChange={onChange} />
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
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
      </Field>
    );
  }

  // Lists and free-form objects: shown read-only rather than half-editable.
  if (typeof reference === "object" && reference !== null) {
    return (
      <Field label={label} hint={hint}>
        <div className={styles.readonly}>{JSON.stringify(reference)}</div>
      </Field>
    );
  }

  return (
    <Field label={label} hint={hint}>
      <Input
        className={styles.mono}
        value={value === null || value === undefined ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      />
    </Field>
  );
}
