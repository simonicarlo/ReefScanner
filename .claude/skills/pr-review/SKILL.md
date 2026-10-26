---
name: pr-review
description: Use when asked to review a pull request, review changes, review a branch, or check work before merging. Also triggered by "review my changes", "is this ready to merge", or "what do you think of this diff".
---

# Pull Request Review

## Overview

Review local branch changes by reading the diff, tracing impact into the broader codebase, and checking for correctness, security, convention compliance, and test adequacy.

**Core principle:** A diff without context is meaningless. Always trace changes into callers, consumers, and related tests before judging.

## Arguments

- No args = diff current branch against `main`
- Branch name = diff against that branch (e.g., `/pr-review develop`)

## Process

1. **Understand the Change** → 2. **Trace Impact** → 3. **Parallel Review** → 4. **Verdict**

### Phase 1: Understand the Change

1. Run `git diff <base>...HEAD --stat` to get the change summary
2. Run `git log <base>...HEAD --oneline` to read commit messages and understand intent
3. Read ALL changed files **in full** (not just diff hunks) — you need the surrounding context
4. Read project convention files (CLAUDE.md and component-level CLAUDE.md files)

### Phase 2: Trace Impact

For each changed function, method, class, or interface:
1. Find all callers and consumers using Grep
2. Check if related tests exist and whether they cover the changed behavior
3. Identify contracts that may have shifted (API response shapes, DB schema, shared interfaces)
4. Note any changed files that lack corresponding test updates

### Phase 3: Parallel Review

Dispatch these review agents in parallel, passing them the diff and the impact context from Phase 2:

| Agent | Focus |
|-------|-------|
| `pr-review-correctness` | Logic errors, edge cases, null handling, race conditions, off-by-ones, broken contracts |
| `pr-review-security` | Injection, XSS, auth bypass, credential exposure **introduced by the diff** |
| `pr-review-conventions` | CLAUDE.md compliance, naming, patterns, style — only for changed code |
| `pr-review-tests` | Are changes tested? Are existing tests still valid? Missing coverage? |

Each agent reports findings with confidence >= 80%, severity, and file:line.

### Phase 4: Verdict

Present a structured review to the user:

```markdown
## PR Review: {branch name}

### Summary
What this PR does (1-2 sentences derived from commits and diff).

### Findings

#### CRITICAL
(items that must be fixed before merge)

#### HIGH
(items that should be fixed)

#### MEDIUM
(suggestions for improvement)

#### LOW
(nitpicks, style preferences)

### Test Coverage
- Changed files with tests: X/Y
- Files missing test updates: list

### Verdict
**Approve** | **Approve with suggestions** | **Needs changes**
(with brief justification)
```

## What This Skill Does NOT Do

- No auto-fixes (report only — user decides what to act on)
- No git operations (no commits, pushes, or branch changes)
- No remote integration (works on local branches only)
