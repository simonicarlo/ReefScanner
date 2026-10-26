---
name: audit
description: Use when asked to review, audit, or assess codebase quality - covers architecture, duplication, test coverage, separation of concerns, and security. Also triggered by requests for code health checks or technical debt assessment.
---

# Codebase Audit

## Overview

Systematic codebase review using parallel specialist agents. Produces a severity-graded report with prioritized action items.

**Core principles:**
- Review all code against its own documented conventions AND framework best practices. Findings must include file:line references and severity ratings.
- **Finding nothing is a valid outcome.** A clean audit is a positive signal, not a failure. Do not manufacture or stretch findings just to have something to report. If a dimension has no issues above the confidence threshold, say so and move on.

## When to Use

- Full codebase review or audit requested
- Technical debt assessment needed
- Pre-production security review
- Quality gate before a major release
- Onboarding to an unfamiliar codebase

## Arguments

- No args = all 5 dimensions
- Comma-separated filters to narrow scope:
  - `security` — injection, auth, credentials, XSS, input validation
  - `architecture` — layering, async patterns, error handling, file sizes
  - `duplication` — repeated patterns, missed abstractions, copy-paste
  - `tests` — coverage gaps, untested critical paths, test quality
  - `separation` — layer bleeding, component responsibilities, service abstraction
- Alternatively, the arguments can set a focus for the audit (e.g. updated libraries or new feature)
- Example: `/audit security,tests` or `/audit I just updated our auth library, can you check for security issues and test gaps?`

## Process

1. **Context Gathering** → 2. **Parallel Deep Review** → 3. **Best Practices Check** → 4. **Report**

### Phase 1: Context Gathering

1. Read project documentation and convention files: `CLAUDE.md`, `README.md`, and any project-specific docs (e.g., spec files, contributing guides, architecture docs)
2. Read component/module-level convention files if they exist
3. Count LOC per component — source vs test, identify largest files
4. Run existing test suites — capture pass/fail counts and warnings
5. Identify tech stack for Phase 3 (frameworks, ORMs, frontend libs)

### Phase 2: Parallel Deep Review

Dispatch one background agent per requested dimension. **All agents run in parallel.**

Use these dedicated agent definitions (from the `agents/` directory alongside this skill):

| Dimension | Agent | Focus |
|-----------|-------|-------|
| `architecture` | `audit-architecture` | Layering, async patterns, error handling, file organization, convention compliance |
| `duplication` | `audit-duplication` | Repeated patterns, missed abstractions, diverged implementations |
| `tests` | `audit-test-coverage` | Module-by-module coverage, untested critical paths, test quality |
| `separation` | `audit-separation` | Layer boundaries, component responsibilities, service abstraction |
| `security` | `audit-security` | Injection, auth, credentials, XSS, infrastructure, input validation |

Each agent reads ALL source files and verifies CLAUDE.md convention compliance within its domain.

### Phase 3: Best Practices Check

Use context7 (if available) to fetch current documentation for the detected tech stack. Compare codebase patterns against documented best practices. Focus on:
- Security recommendations from framework docs
- Deprecated patterns or APIs
- Recommended patterns the codebase doesn't follow

### Phase 4: Report

Compile all findings into `code-review-YYYY-MM-DD--hh-mm.md` in a reasonable location (e.g., `docs/` or root). Use the following format:

```markdown
# Codebase Review - YYYY-MM-DD hh:mm

## Executive Summary
- Codebase size (LOC source/test per component)
- Test counts and pass/fail status
- Health scorecard (rating per dimension)

## 1. Security
### CRITICAL
### HIGH
### MEDIUM
### LOW

## 2. Architecture & Error Handling
(same severity sections)

## 3. Code Duplication
(same severity sections)

## 4. Test Coverage
- Summary table: module | coverage level | priority gaps
- Completely untested modules listed first

## 5. Separation of Concerns
(same severity sections)

## 6. Best Practices (context7)
- Framework-specific findings

## 7. Convention Compliance
- CLAUDE.md violations found across all dimensions

## Prioritized Action Items
### Immediate (security, critical bugs)
### Short-term (high-severity, resilience)
### Medium-term (test gaps, duplication)
### Long-term (hardening, nice-to-haves)
```

Present a terminal summary after writing the report. **Do not auto-fix or commit anything.**

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Reviewing only a sample of files | Agents must read ALL source files in their dimension |
| Reporting low-confidence findings | Only report >= 80% confidence, state confidence level |
| Missing file:line references | Every finding must be traceable to exact location |
| Forgetting to check CLAUDE.md conventions | Conventions are the project's own rules — verify compliance |
| Running agents sequentially | Always dispatch all dimension agents in parallel (background) |
| Proposing fixes in the report | Report findings only — user decides what to fix |
| Manufacturing findings to fill the report | Finding nothing is valid — a clean result is a positive signal, not a gap to fill |
