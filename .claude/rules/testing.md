---
paths:
  - "tests/**"
  - "**/test_*.py"
  - "**/*.test.*"
---

# Testing Conventions

## Philosophy
Write **meaningful tests that prevent regressions**, not tests for the sake of
coverage. Every test should protect against a real breakage scenario. The
expensive failure in this project is a missed animal, so anything that could
silently drop detections, events or observations gets a test.

## What to Test
- **Data transformations** — detection, aggregation, the Camtrap DP mapping,
  timestamps and timezones, bounding-box conversions
- **API contracts** — status codes, response shapes, validation errors (422),
  not-found (404), conflicts (409)
- **Data formats** — written Camtrap DP packages validate against the official
  profile and table schemas (`tests/camtrap_check.py`)
- **Edge cases** — missing metadata, empty results, invalid input at boundaries
- **Security boundaries** — paths that must stay inside a folder, input that
  must be refused

## What NOT to Test
- Trivial pass-throughs, framework wiring, styling
- Implementation details that couple tests to internal structure

## Stack and Fixtures
- **pytest**, run with `uv run pytest`; tests live in `tests/core/`,
  `tests/edge/` and `tests/app/`, shared helpers in `tests/` (`conftest.py`, `camtrap_check.py`)
- **No network, no real model, no real footage.** Use the `stub_detector`
  fixture instead of weights, `make_video` for synthetic footage, `tmp_path`
  for files and databases, and fake sessions for ONNX Runtime
- A temporary SQLite file and a short synthetic video are fine: they are the
  seams that actually break, and they stay fast
- External validators (jsonschema, frictionless) run offline from schema
  copies in the repo
- Polling a background job is fine; fixed `sleep`s are not
- Checks against real footage or real models belong in scripts
  (`scripts/check_onnx_parity.py`), not in the suite

## Guidelines
- Test behaviour and outcomes, not how they were achieved
- One logical outcome per test; several asserts are fine if they check it
- Names describe the scenario in snake_case:
  `test_a_new_run_rescans_everything_so_its_package_is_complete`
- A guard that "can't fail" needs a test proving it can (see
  `test_the_validators_catch_a_broken_package`)
- Bug fixes get a regression test that fails without the fix
