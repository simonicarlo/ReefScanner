import { useState } from "react";
import { useSaveMetadata } from "../lib/queries";
import {
  CONTRIBUTOR_ROLES,
  type Contributor,
  type ContributorRole,
  type PackageMetadata,
} from "../lib/types";
import { Button, ErrorNote, Field, Input, cx } from "./ui";

const ROLE_LABELS: Record<ContributorRole, string> = {
  contributor: "Contributor",
  contact: "Contact",
  principalInvestigator: "Principal investigator",
  rightsHolder: "Rights holder",
  publisher: "Publisher",
};

/**
 * The study and team a project's packages name (Camtrap `project` and
 * `contributors`). Edited as a draft and saved whole, like the scan settings.
 */
export function MetadataPanel({
  projectId,
  saved,
}: {
  projectId: number;
  saved: PackageMetadata;
}) {
  const save = useSaveMetadata(projectId);
  const [draft, setDraft] = useState<PackageMetadata | null>(null);
  const value = draft ?? saved;

  const setProject = (patch: Partial<PackageMetadata["project"]>) =>
    setDraft({ ...value, project: { ...value.project, ...patch } });
  const setContributor = (i: number, patch: Partial<Contributor>) =>
    setDraft({
      ...value,
      contributors: value.contributors.map((c, j) => (j === i ? { ...c, ...patch } : c)),
    });

  // Caught here so the person gets a plain sentence, not a field path.
  const missing = !value.project.title.trim()
    ? "The project needs a title."
    : value.contributors.some((c) => !c.title.trim())
      ? "Every contributor needs a name."
      : null;

  // Blank optional fields go as null; the server leaves them out of packages.
  const cleaned = (): PackageMetadata => ({
    project: {
      title: value.project.title.trim(),
      description: value.project.description?.trim() || null,
    },
    contributors: value.contributors.map((c) => ({
      title: c.title.trim(),
      email: c.email?.trim() || null,
      organization: c.organization?.trim() || null,
      role: c.role,
    })),
  });

  return (
    <section className="panel p-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium">Package metadata</h2>
          <p className="mt-0.5 text-xs text-faint">
            The study and the people named in this project's exported packages.
            At least one contributor is required.
          </p>
        </div>
        {draft && (
          <div className="flex shrink-0 gap-2">
            <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
              Revert
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() =>
                save.mutate(cleaned(), { onSuccess: () => setDraft(null) })
              }
              disabled={save.isPending || missing !== null}
              title={missing ?? undefined}
            >
              Save
            </Button>
          </div>
        )}
      </div>

      {draft && missing && <p className="mb-3 text-xs text-hedge">{missing}</p>}
      <ErrorNote error={save.error} />

      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Project title" hint="The study the footage was collected for.">
          <Input
            value={value.project.title}
            onChange={(e) => setProject({ title: e.target.value })}
            maxLength={300}
          />
        </Field>
        <Field label="Description" hint="Optional.">
          <Input
            value={value.project.description ?? ""}
            onChange={(e) => setProject({ description: e.target.value })}
            maxLength={5000}
          />
        </Field>
      </div>

      <div className="mt-5 space-y-2">
        <div className="legend">Contributors</div>
        {value.contributors.map((c, i) => (
          <div
            key={i}
            className="grid items-center gap-2 md:grid-cols-[1.2fr_1.2fr_1fr_auto_auto]"
          >
            <Input
              aria-label="Name"
              placeholder="Name"
              value={c.title}
              onChange={(e) => setContributor(i, { title: e.target.value })}
              maxLength={200}
            />
            <Input
              aria-label="Email"
              placeholder="Email (optional)"
              type="email"
              value={c.email ?? ""}
              onChange={(e) => setContributor(i, { email: e.target.value })}
              maxLength={200}
            />
            <Input
              aria-label="Organisation"
              placeholder="Organisation (optional)"
              value={c.organization ?? ""}
              onChange={(e) => setContributor(i, { organization: e.target.value })}
              maxLength={200}
            />
            <select
              aria-label="Role"
              value={c.role}
              onChange={(e) =>
                setContributor(i, { role: e.target.value as ContributorRole })
              }
              className={cx(
                "rounded-[3px] border border-rule bg-abyss/60 px-2 py-1.5 text-sm text-read",
                "focus:border-signal/60 focus:outline-none",
              )}
            >
              {CONTRIBUTOR_ROLES.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Remove ${c.title || "contributor"}`}
              disabled={value.contributors.length === 1}
              title={
                value.contributors.length === 1
                  ? "A package needs at least one contributor"
                  : undefined
              }
              onClick={() =>
                setDraft({
                  ...value,
                  contributors: value.contributors.filter((_, j) => j !== i),
                })
              }
            >
              Remove
            </Button>
          </div>
        ))}
        <button
          type="button"
          className="legend hover:text-signal"
          onClick={() =>
            setDraft({
              ...value,
              contributors: [...value.contributors, { title: "", role: "contributor" }],
            })
          }
        >
          + Add contributor
        </button>
      </div>
    </section>
  );
}
