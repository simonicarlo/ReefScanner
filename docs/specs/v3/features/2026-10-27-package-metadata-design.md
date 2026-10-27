# Contributors and project metadata

Phase 0 item: packages name who made them. Today an export lists the laptop's
login name as its only contributor, reviews are signed with it too, and an
import drops the package's contributors.

## Decisions

### 1. Two levels: you, and the project

- **You** (app settings, one per laptop): your name, and optionally email and
  organisation. Reviews are signed with your name (`classifiedBy`), and a new
  project starts with you as its contributor. Until you set a name, the login
  name stands in, as today.
- **The project** (per project): the Camtrap `project.title` and
  `project.description`, and the `contributors` list. Each contributor has a
  name (`title`), and optionally `email`, `organization` and a `role` from the
  standard's list (`contact`, `principalInvestigator`, `rightsHolder`,
  `publisher`, `contributor`).

A project, not the laptop, owns the contributor list: different deployments
have different teams, and an imported package brings its own.

### 2. Storage

- A new `AppSettings` table with a single row for "you".
- Project metadata goes in one JSON column on `Project` (`package_metadata`),
  stored in Camtrap's own shape (`project`, `contributors`) so an export
  copies it as is. JSON rather than columns, like `config`: adding a field
  later needs no migration.
- One Alembic migration (`0003`) for both.

### 3. Export and import

- An export writes the project's `project` and `contributors` into
  `datapackage.json`. A project always has at least one contributor (the API
  refuses an empty list), which Camtrap requires.
- An import takes `project.title`, `project.description` and `contributors`
  from the package. They are untrusted, so only those keys are kept, every
  value must be a string of bounded length, roles must be in the standard's
  list, and anything else is a listed problem like the rest of the import
  checks. A package without contributors can't exist (the reader refuses it).

### 4. UI

- A **Settings** page in the top bar: your name, email, organisation.
- A **Package metadata** panel on the project page, next to Scan settings:
  project title, description, and the contributor list (add, edit, remove).

## Not now

- Licences (`licenses`) and a citation: wanted before publishing to GBIF, but
  Camtrap then requires both a data and a media licence, which is a decision
  for the team.
- Pushing contributors to the rig: that is part of deployment setup (phase 2);
  the agent's YAML config already takes them.
