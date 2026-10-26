---
paths:
  - "app/src/reefscanner/app/routers/**"
  - "app/src/reefscanner/app/schemas.py"
---

# API Design Rules (FastAPI, `reefscanner.app`)

## Route Handlers
- Keep handlers thin: domain logic lives in modules (`exports.py`,
  `analysis.py`, `jobs.py`) or in `reefscanner.core`, where it can be tested
  without HTTP
- Every endpoint declares its response model (`response_model=` or a return
  annotation)
- Sessions come from `Depends(get_session)`; queries that grow beyond a few
  lines move into a module function
- Request and response shapes are Pydantic models in `schemas.py`, separate
  from the tables, so the wire format doesn't move with every column

## Validation
- Validate all input with Pydantic `Field()` constraints and validators:
  required strings `min_length=1`, bounded numbers `ge`/`le`
- Engine settings are validated by round-tripping through `ReefScannerConfig`,
  never re-declared
- Invalid input returns 422; never silently ignore or coerce it

## Status Codes
- 404 not found, 409 conflict (a run already active, an invalid state
  transition), 422 validation, 403 for a path outside its allowed folder

## Error Messages
- This is a single-user local app: a message may name the user's own folder
  when that helps them fix their input
- Never return stack traces, raw exception strings or database errors; log the
  details server-side
- When the user must fix several things (e.g. an invalid package), return all
  of them, not the first

## Safety
- Media and files are addressed by id, never by a client-supplied path
- Destructive operations say what they delete in their docstring, and delete
  only database rows unless the user asked for files to go
- Concurrent work is guarded explicitly (one active run per project)
