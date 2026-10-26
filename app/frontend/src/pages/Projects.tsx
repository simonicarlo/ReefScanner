import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys, useProjects } from "../lib/queries";
import { shortDate, tailPath } from "../lib/format";
import { Button, Empty, ErrorNote, Field, Input, Spinner } from "../components/ui";

export function Projects() {
  const { data: projects, isLoading } = useProjects();
  const [creating, setCreating] = useState(false);

  return (
    <div className="rise">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="mt-1 text-sm text-faint">
            A folder of footage plus the settings used to scan it.
          </p>
        </div>
        <Button variant="primary" onClick={() => setCreating((v) => !v)}>
          {creating ? "Cancel" : "New project"}
        </Button>
      </div>

      {creating && <NewProjectForm onDone={() => setCreating(false)} />}

      {isLoading ? (
        <Spinner label="Reading projects" />
      ) : !projects?.length ? (
        <Empty title="No projects yet">
          Create one pointing at a folder of video files. Nothing is uploaded —
          ReefScanner reads the footage where it already lives.
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

function NewProjectForm({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [inputFolder, setInputFolder] = useState("");
  const [outputFolder, setOutputFolder] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.createProject({
        name: name.trim(),
        input_folder: inputFolder.trim(),
        // Default the results next to the footage: it's the answer almost
        // everyone wants, and it keeps clips near what they came from.
        output_folder:
          outputFolder.trim() || `${inputFolder.trim().replace(/\/+$/, "")}_results`,
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
        hint="Optional — defaults to the footage folder with '_results' appended. Clips, thumbnails and the CSV go here."
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
