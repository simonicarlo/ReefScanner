# ReefScanner

## Specs

Specs are versioned under `docs/specs/` — see `docs/specs/README.md`. The current
version is **v3** (`docs/specs/v3/spec.md`); its task list and decisions are in
`docs/specs/v3/TODO.md` — keep it current as work lands.

Write new feature specs and implementation plans (including those from the
superpowers brainstorming and writing-plans skills) to
`docs/specs/v3/features/`, named `YYYY-MM-DD-<topic>-design.md` and
`YYYY-MM-DD-<topic>-plan.md` — not to `docs/superpowers/`.

## Standards

Coding standards live in `.claude/rules/` (Python, testing, API design,
security, dependencies, frontend) and apply to all new and changed code.
Skills for audits, onboarding and PR review are in `.claude/skills/`.

## Layout

A uv workspace of three packages sharing the `reefscanner` namespace:
`core/` (engine + CLI, no web deps), `edge/` (on-rig agent), `app/` (FastAPI
service, review UI in `app/frontend/`, desktop shell, Mac build). Core must
never import from `app` or `edge`.

- `uv sync` installs every member editable, plus the dev group.
- `uv run pytest` runs `tests/core/` and `tests/app/`.
- Database schema changes need an Alembic migration: from `app/`, run
  `uv run alembic revision --autogenerate -m "..."` and review the file.
  `tests/app/test_migration.py` fails if models and migrations disagree.
- Camtrap DP tables live in `core/src/reefscanner/core/camtrap/`, with field
  names exactly as in the standard (camelCase).
