import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys, useProjects } from "../lib/queries";
import { shortDate, tailPath } from "../lib/format";
import { Button, Empty, ErrorNote, Field, Input, Spinner, cx } from "../components/ui";

export function Projects() {
  const { data: projects, isLoading } = useProjects();
  const [form, setForm] = useState<"new" | "import" | null>(null);
  const toggle = (which: "new" | "import") => setForm((f) => (f === which ? null : which));

  return (
    <div className="rise">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="mt-1 text-sm text-faint">
            A folder of footage plus the settings used to scan it.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => toggle("import")}>
            {form === "import" ? "Cancel" : "Import package"}
          </Button>
          <Button variant="primary" onClick={() => toggle("new")}>
            {form === "new" ? "Cancel" : "New project"}
          </Button>
        </div>
      </div>

      {form === "new" && <NewProjectForm onDone={() => setForm(null)} />}
      {form === "import" && <ImportPackageForm onDone={() => setForm(null)} />}

      {isLoading ? (
        <Spinner label="Reading projects" />
      ) : !projects?.length ? (
        <Empty title="No projects yet">
          Create one pointing at a folder of video files, or import a package
          from the rig. Nothing is uploaded — ReefScanner reads the footage
          where it already lives.
        </Empty>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((project, i) => (
            <Link
              key={project.id}
              to={`/projects/${project.id}`}
              style={{ animationDelay: `${i * 40}ms` }}
              className="panel rise group flex flex-col gap-3 p-4 transition-colors hover:border-signal/50"
            >
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-base font-medium group-hover:text-signal">
                  {project.name}
                </h2>
                <span className="tabular shrink-0 text-xs text-faint">
                  {project.job_count} run{project.job_count === 1 ? "" : "s"}
                </span>
              </div>

              <dl className="space-y-1.5">
                <div>
                  <dt className="legend">Footage</dt>
                  <dd
                    className="truncate font-mono text-xs text-dim"
                    title={project.input_folder}
                  >
                    {tailPath(project.input_folder)}
                  </dd>
                </div>
                <div>
                  <dt className="legend">Results</dt>
                  <dd
                    className="truncate font-mono text-xs text-dim"
                    title={project.output_folder}
                  >
                    {tailPath(project.output_folder)}
                  </dd>
                </div>
              </dl>

              <div className="legend mt-auto pt-1">
                {shortDate(project.created_at)}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
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
    <form
      className="panel rise mb-6 space-y-4 p-5"
      onSubmit={(e) => {
        e.preventDefault();
        importing.mutate();
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <Field
          label="Package folder"
          hint="The folder with datapackage.json in it, e.g. a deployment on the rig's SD card."
        >
          <Input
            autoFocus
            className="font-mono text-xs"
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
            className="font-mono text-xs"
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

      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={importing.isPending}>
          {importing.isPending ? "Checking…" : "Import"}
        </Button>
      </div>
    </form>
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
    <form
      className="panel rise mb-6 space-y-4 p-5"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
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
            className="font-mono text-xs"
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
          className="font-mono text-xs"
          value={outputFolder}
          onChange={(e) => setOutputFolder(e.target.value)}
          placeholder={
            inputFolder ? `${inputFolder.replace(/\/+$/, "")}_results` : "/Users/you/results"
          }
        />
      </Field>

      <div className="grid gap-4 md:grid-cols-4">
        <Field label="Latitude" hint="Decimal degrees, south negative.">
          <Input
            className="font-mono text-xs"
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
            className="font-mono text-xs"
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
            className="font-mono text-xs"
            type="number"
            step="any"
            min={0}
            value={depth}
            onChange={(e) => setDepth(e.target.value)}
            placeholder="18"
          />
        </Field>
        <Field label="Bait" hint="Was the rig baited?">
          <label className="flex items-center gap-2 py-1.5 text-sm text-read">
            <input
              type="checkbox"
              checked={baited}
              onChange={(e) => setBaited(e.target.checked)}
              className="accent-[var(--color-signal)]"
            />
            Baited (BRUV)
          </label>
        </Field>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
      <Field
        label="Camera timezone"
        hint="Where the footage was filmed. Filled in with this computer's timezone; change it if that's elsewhere. Video files can't be trusted to say."
      >
        <Input
          className="font-mono text-xs"
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
      >
        <div className="flex flex-wrap gap-1">
          {(["local", "utc"] as const).map((choice) => (
            <button
              key={choice}
              type="button"
              onClick={() => setCameraClock(choice)}
              className={cx(
                "rounded-[3px] border px-2.5 py-1 font-mono text-xs transition-colors",
                cameraClock === choice
                  ? "border-signal/60 bg-signal/15 text-signal"
                  : "border-rule text-dim hover:border-rule-hi hover:text-read",
              )}
            >
              {choice === "local" ? "local time" : "true UTC"}
            </button>
          ))}
        </div>
      </Field>
      </div>

      <ErrorNote error={create.error} />

      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create project"}
        </Button>
      </div>
    </form>
  );
}
