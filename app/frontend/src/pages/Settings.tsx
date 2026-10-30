import { useState } from "react";
import { useSaveSettings, useSettings } from "../lib/queries";
import type { Settings as SettingsData } from "../lib/types";
import { Button, ErrorNote, Field, Input, Panel, Spinner } from "../components/ui";
import { AppearancePanel } from "../components/AppearancePanel";
import { PageHeader } from "../components/PageHeader";
import styles from "./Settings.module.css";

/** The person using this laptop: who signs reviews and starts new projects. */
export function Settings() {
  const { data, isLoading, error } = useSettings();
  if (isLoading) return <Spinner label="Reading settings" />;
  if (!data) return <ErrorNote error={error} />;
  // Keyed so a save (or a reload) starts the form from what's stored.
  return <SettingsForm key={JSON.stringify(data)} saved={data} />;
}

function SettingsForm({ saved }: { saved: SettingsData }) {
  const save = useSaveSettings();
  const [name, setName] = useState(saved.name ?? "");
  const [email, setEmail] = useState(saved.email ?? "");
  const [organization, setOrganization] = useState(saved.organization ?? "");
  const dirty =
    name !== (saved.name ?? "") ||
    email !== (saved.email ?? "") ||
    organization !== (saved.organization ?? "");

  return (
    <div className={styles.page}>
      <PageHeader
        title="Settings"
        subtitle="How the app looks, and who you are on this laptop."
      />

      <AppearancePanel />

      <Panel
        title="You"
        description="Reviews are signed with your name, and new projects list you as their contributor. Each project's own team is edited on its page."
      >
        <form
          className={styles.form}
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({
              name: name || null,
              email: email || null,
              organization: organization || null,
            });
          }}
        >
          <Field
            label="Your name"
            hint={`Reviews are signed as “${saved.signed_as}”${saved.name ? "" : " (your login name) until you set one"}.`}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          </Field>
          <Field label="Email" hint="Optional. Goes into packages with your name.">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              maxLength={200}
            />
          </Field>
          <Field label="Organisation" hint="Optional.">
            <Input
              value={organization}
              onChange={(e) => setOrganization(e.target.value)}
              maxLength={200}
            />
          </Field>

          <ErrorNote error={save.error} />

          <div className={styles.actions}>
            <Button type="submit" variant="primary" disabled={!dirty || save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  );
}
