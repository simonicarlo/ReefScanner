# Security Rules

These rules apply to all code. Violations are high-priority findings.

## Threat Model
- The field app is single-user and localhost-only, with no authentication.
  Binding to anything else must warn; never weaken that default.
- Anything reaching the service can be another program on the same machine,
  so every endpoint must be safe against hostile input.
- Camtrap DP packages imported from a rig, an SD card or someone else are
  untrusted input, including every path inside them.

## Input Validation
- Validate user-controlled values at system boundaries: API payloads, CLI
  arguments, config files, imported packages
- Never join user- or package-supplied paths without resolving them and
  checking the result stays inside the expected folder
- Never interpolate user input into shell commands; pass argument lists to
  `subprocess` (as the ffmpeg calls do)
- Never render server or user data as HTML (`dangerouslySetInnerHTML`)

## Error Responses
- No stack traces, raw exception strings or database errors in API responses;
  log them internally

## Downloads and Credentials
- Downloaded models are checked against a pinned SHA-256 before use
- Never hardcode secrets or log credentials or tokens, even at debug level

## CORS
- Only the explicit dev origin (Vite) is allowed; never `*`

## Resource Cleanup
- Close sessions, files and subprocesses in `finally` blocks or context managers
- Write files atomically (temp file plus replace) where a half-written file
  would be read as complete
