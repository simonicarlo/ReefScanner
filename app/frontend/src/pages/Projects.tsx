import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys, useProjects } from "../lib/queries";
import { shortDate, tailPath } from "../lib/format";
import type { Project } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import { ReviewBar } from "../components/ReviewBar";
import { SegmentedControl } from "../components/SegmentedControl";
import { Switch } from "../components/Switch";
import { Button, Empty, ErrorNote, Field, Input, Panel, Spinner } from "../components/ui";
import styles from "./Projects.module.css";

export function Projects() {
  const { data: projects, isLoading } = useProjects();
  const [form, setForm] = useState<"new" | "import" | null>(null);
  const toggle = (which: "new" | "import") => setForm((f) => (f === which ? null : which));

  return (
    <div className={styles.page}>
      <PageHeader
        title="Projects"
        subtitle="A folder of footage plus the settings used to scan it."
        actions={
          <>
            <Button onClick={() => toggle("import")}>
              {form === "import" ? "Cancel" : "Import package"}
            </Button>
            <Button variant="primary" onClick={() => toggle("new")}>
              {form === "new" ? "Cancel" : "New project"}
            </Button>
          </>
        }
      />

      {form === "new" && <NewProjectForm onDone={() => setForm(null)} />}
      {form === "import" && <ImportPackageForm onDone={() => setForm(null)} />}

      {isLoading ? (
        <Spinner label="Reading projects" />
      ) : !projects?.length ? (
        <Empty title="No projects yet">
          Create one pointing at a folder of video files, or import a package from the
          rig. Nothing is uploaded: ReefScanner reads the footage where it already lives.
        </Empty>
      ) : (
        <div className={styles.cards}>
          {projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const run = project.latest_run;
  return (
    <Link to={`/projects/${project.id}`} className={styles.card}>
      <div className={styles.cover}>
        {run?.cover_url ? (
          <img src={run.cover_url} alt="" loading="lazy" />
        ) : (
          <span className={styles.noCover}>Not scanned yet</span>
        )}
      </div>
      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{project.name}</h2>
        <div className={styles.cardMeta}>
          <span className={styles.mono} title={project.input_folder}>
            {tailPath(project.input_folder, 1)}
          </span>
          <span>
            {project.job_count} run{project.job_count === 1 ? "" : "s"}
          </span>
          <span>{shortDate(project.created_at)}</span>
        </div>
        {run && (
          <div className={styles.review}>
            <ReviewBar
              thin
              total={run.events}
              confirmed={run.confirmed}
              rejected={run.rejected}
              unsure={run.reviewed - run.confirmed - run.rejected}
            />
            <span>
              {run.reviewed === run.events
                ? `All ${run.events} reviewed`
                : `${run.reviewed} of ${run.events} reviewed`}
            </span>
          </div>
        )}
      </div>
    </Link>
  );
}

/** A Camtrap DP package folder (from the rig, an SD card, another laptop) as a new project. */
function ImportPackageForm({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [packageFolder, setPackageFolder] = useState("");
  const [outputFolder, setOutputFolder] = useState("");
  const [name, setName] = useState("");

  const importing = useMutation({
    mutationFn: () =>
      api.importProject({
        package_folder: packageFolder.trim(),
        output_folder: outputFolder.trim(),
        ...(name.trim() ? { name: name.trim() } : {}),
      }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: keys.projects });
      onDone();
      navigate(`/projects/${project.id}`);
    },
  });

  return (
    <Panel title="Import a package" description="A Camtrap DP package from the rig, an SD card or another laptop becomes a new project.">
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          importing.mutate();
        }}
      >
        <div className={styles.row2}>
          <Field
            label="Package folder"
            hint="The folder with datapackage.json in it, e.g. a deployment on the rig's SD card."
          >
            <Input
              autoFocus
              className={styles.mono}
              value={packageFolder}
              onChange={(e) => setPackageFolder(e.target.value)}
              placeholder="/Volumes/RIG/tofo-2026-11-02-a"
              required
            />
          </Field>
          <Field
            label="Results folder"
            hint="Where the clips and frames are copied, so the card can go back in the rig."
          >
            <Input
              className={styles.mono}
              value={outputFolder}
              onChange={(e) => setOutputFolder(e.target.value)}
              placeholder="/Users/you/reefscanner/tofo"
              required
            />
          </Field>
        </div>
        <Field label="Project name" hint="Optional. Defaults to the deployment's location.">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Manta Reef" />
        </Field>

        <ErrorNote error={importing.error} />

        <div className={styles.formActions}>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={importing.isPending}>
            {importing.isPending ? "Checking…" : "Import"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/** This computer's IANA timezone: a starting guess for the camera's, never a fact. */
const LOCAL_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC";

/** Every IANA zone the browser knows, for autocompletion; empty if unsupported. */
const TIMEZONES: string[] = (() => {
  try {
    return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf(
      "timeZone",
    );
  } catch {
    return [];
  }
})();

function NewProjectForm({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [inputFolder, setInputFolder] = useState("");
  const [outputFolder, setOutputFolder] = useState("");
  const [cameraTimezone, setCameraTimezone] = useState(LOCAL_TIMEZONE);
  const [cameraClock, setCameraClock] = useState<"local" | "utc">("local");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [depth, setDepth] = useState("");
  const [baited, setBaited] = useState(true);

  const create = useMutation({
    mutationFn: () =>
      api.createProject({
        name: name.trim(),
        input_folder: inputFolder.trim(),
        // Default the results next to the footage: it's the answer almost
        // everyone wants, and it keeps clips near what they came from.
        output_folder:
          outputFolder.trim() || `${inputFolder.trim().replace(/\/+$/, "")}_results`,
        config: { camera_timezone: cameraTimezone.trim(), camera_clock: cameraClock },
        deployment: {
          latitude: Number(latitude),
          longitude: Number(longitude),
          camera_depth: depth.trim() ? Number(depth) : null,
          bait_use: baited,
        },
      }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: keys.projects });
      onDone();
      navigate(`/projects/${project.id}`);
    },
  });

  return (
    <Panel title="New project" description="Point it at a folder of footage. Nothing is copied until you scan.">
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div className={styles.row2}>
          <Field label="Project name">
            <Input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ningaloo BRUV, March"
              required
            />
          </Field>
          <Field
            label="Footage folder"
            hint="Absolute path. Searched recursively for video files."
          >
            <Input
              className={styles.mono}
              value={inputFolder}
              onChange={(e) => setInputFolder(e.target.value)}
              placeholder="/Users/you/footage/ningaloo"
              required
            />
          </Field>
        </div>

        <Field
          label="Results folder"
          hint="Optional — defaults to the footage folder with '_results' appended. Each scan gets a folder here with its clips, frames and Camtrap DP package."
        >
          <Input
            className={styles.mono}
            value={outputFolder}
            onChange={(e) => setOutputFolder(e.target.value)}
            placeholder={
              inputFolder ? `${inputFolder.replace(/\/+$/, "")}_results` : "/Users/you/results"
            }
          />
        </Field>

        <div className={styles.row4}>
          <Field label="Latitude" hint="Decimal degrees, south negative.">
            <Input
              className={styles.mono}
              type="number"
              step="any"
              min={-90}
              max={90}
              value={latitude}
              onChange={(e) => setLatitude(e.target.value)}
              placeholder="-23.8500"
              required
            />
          </Field>
          <Field label="Longitude" hint="Decimal degrees, west negative.">
            <Input
              className={styles.mono}
              type="number"
              step="any"
              min={-180}
              max={180}
              value={longitude}
              onChange={(e) => setLongitude(e.target.value)}
              placeholder="35.5500"
              required
            />
          </Field>
          <Field label="Depth (m)" hint="Optional. Water depth of the rig.">
            <Input
              className={styles.mono}
              type="number"
              step="any"
              min={0}
              value={depth}
              onChange={(e) => setDepth(e.target.value)}
              placeholder="18"
            />
          </Field>
          <Field label="Bait" hint="Was the rig baited?" group>
            <Switch label="Baited (BRUV)" checked={baited} onChange={setBaited} />
          </Field>
        </div>

        <div className={styles.row2}>
          <Field
            label="Camera timezone"
            hint="Where the footage was filmed. Filled in with this computer's timezone; change it if that's elsewhere. Video files can't be trusted to say."
          >
            <Input
              className={styles.mono}
              value={cameraTimezone}
              onChange={(e) => setCameraTimezone(e.target.value)}
              list="timezones"
              placeholder="Africa/Maputo"
              required
            />
            <datalist id="timezones">
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz} />
              ))}
            </datalist>
          </Field>
          <Field
            label="Camera clock"
            hint="Local: the camera's clock shows local time (GoPros, most action cams). UTC: it records real UTC (phones, GPS-synced cameras)."
            group
          >
            <div>
              <SegmentedControl
                label="Camera clock"
                options={[
                  { value: "local", label: "Local time" },
                  { value: "utc", label: "True UTC" },
                ]}
                value={cameraClock}
                onChange={setCameraClock}
              />
            </div>
          </Field>
        </div>

        <ErrorNote error={create.error} />

        <div className={styles.formActions}>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create project"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}
