---
paths:
  - "**/*.py"
---

# Python Conventions

Python 3.12+ (`requires-python = ">=3.12"`); developed and shipped on the
version in `.python-version`. Don't use syntax newer than the minimum.

## Type Hints
- Union syntax: `str | None`, never `Optional[str]` / `Union[...]`
- Lowercase generics: `list[str]`, `dict[str, Any]`, `tuple[int, int]`
- Every function signature has a return annotation
- SQLModel table modules (`models.py`) must NOT use `from __future__ import
  annotations`: SQLModel evaluates field annotations at class creation

## Imports
Order, separated by blank lines:
1. `from __future__ import annotations` (everywhere except SQLModel table modules)
2. Standard library, alphabetical
3. Third-party, alphabetical
4. `reefscanner.*` absolute imports across packages, then relative imports within one

Heavy or optional dependencies (torch, ultralytics, onnxruntime, sahi, cv2 in
exporters) are imported inside the function that needs them, so importing a
module never costs them.

## Package boundaries
- `reefscanner.core` never imports `reefscanner.app` or `reefscanner.edge`
- `core` must stay installable on an edge board: no web stack, no torch
- Camtrap DP field names stay exactly as the standard spells them (camelCase)

## Naming
- Functions, variables, modules: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private helpers and state: single leading underscore

## Concurrency
The app is deliberately synchronous: FastAPI runs plain `def` routes in its
threadpool, and scans run on worker threads (`app/jobs.py`) because OpenCV and
model inference block.
- Route handlers are `def`, not `async def`, unless they truly await (the
  WebSocket); never call blocking code from an `async def`
- Worker threads open their own short-lived database sessions; never share a
  session across threads
- Long loops check a cancellation flag between units of work (frames, videos)

## Error Handling
- Catch specific exception types; never a bare `except:`
- Re-raise with context: `raise RuntimeError("...") from exc`
- When swallowing an exception is right, log it (at least `debug`) and say why
  in a comment
- Fail loudly on bad input at boundaries (config, API payloads, packages);
  collect and report every problem when the user has to fix them all

## Comments and Docstrings
- Module docstrings say what the module is for and the decisions behind it
- Comments explain *why*, not what; keep the reasoning next to the code it
  justifies (e.g. why recall beats precision, why a value is required)

## Documentation
- When unsure about a library API (FastAPI, SQLModel/SQLAlchemy, Pydantic,
  Alembic, ONNX Runtime, OpenCV), check current docs with context7 rather than
  relying on memory
