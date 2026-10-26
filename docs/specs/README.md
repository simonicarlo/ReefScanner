# Specs

Every version of ReefScanner has one overarching spec, and any number of
feature specs and plans written while building it.

| Version | What it is | Status |
|---|---|---|
| [v1](v1/spec.md) | Motion-only triage engine, run as a Colab notebook from an iPad | Superseded; its reasoning still governs the engine |
| [v2](v2/spec.md) | Local desktop app: FastAPI + SQLite + React review UI, detector-first | Shipped (2026-09) |
| [v3](v3/spec.md) | On-rig live detection: a headless edge agent that keeps only the clips worth reviewing | In design (2026-10) |

## Layout

```
docs/specs/
  vN/
    spec.md       the version spec: scope, goals, decisions, non-goals
    plan.md       optional working plan / session handoff for the version
    features/     feature-level specs and implementation plans
      YYYY-MM-DD-<topic>-design.md   feature spec
      YYYY-MM-DD-<topic>-plan.md     implementation plan for that spec
```

The version spec says *what* the version is and *why*. Feature specs narrow one
piece of it down to something buildable, and each plan implements one feature
spec. When a feature spec contradicts the version spec, update the version spec
so it stays the source of truth.

## Adding to it

- **A feature for the current version:** write the spec and plan into
  `vN/features/` with the date-prefixed names above.
- **A new version:** create `vN+1/spec.md`, link back to the specs it builds on,
  add a row to the table above, and set the previous version's status.
