---
name: onboard
description: Use when starting work on an unfamiliar codebase or module, when asked to understand project structure, or when onboarding documentation is needed. Also triggered by questions like "how does this project work" or "walk me through the architecture".
---

# Codebase Onboarding

## Overview

Rapidly understand an unfamiliar codebase or module by mapping its architecture, key files, conventions, data flow, and entry points. Produces a persistent onboarding document and offers interactive follow-up.

**Core principle:** Read the code and its conventions systematically — don't guess from file names alone.

## Arguments

- No args = full codebase onboarding
- Module/directory name = onboard on that specific module only (e.g., `/onboard backend`)

## Process

1. **Discovery** → 2. **Parallel Deep Exploration** → 3. **Report** → 4. **Follow-up Q&A**

### Phase 1: Discovery

1. Detect project type from file patterns (languages, frameworks, build tools, package managers)
2. Read all convention and documentation files: `CLAUDE.md`, `README.md`, `CONTRIBUTING.md`, and any project-specific docs
3. Map top-level directory structure — identify the major components
4. If a specific module was requested, narrow scope to that module and its immediate dependencies

### Phase 2: Parallel Deep Exploration

Dispatch one `onboard-explorer` agent per discovered component/layer. Each agent:
- Reads ALL source files in its component (not tests initially)
- Identifies entry points (main files, route definitions, app bootstrap)
- Maps data flow (how requests/data move through the layer)
- Catalogs key abstractions (services, models, utilities, shared patterns)
- Notes external dependencies and integrations (APIs, databases, queues)
- Lists conventions in use (naming, patterns, error handling)

For module-scoped onboarding, dispatch one agent for the target module and one for its dependencies/consumers.

### Phase 3: Report

Write an `onboarding.md` (full codebase) or `onboarding-{module}.md` (module-scoped) file in a reasonable location:

```markdown
# Onboarding: {Project or Module Name}

## Tech Stack
Languages, frameworks, key dependencies with versions

## Architecture Overview
Components and how they connect (with ASCII diagram if helpful)

## Key Files
Table: file path | purpose | when you'd modify it

## Conventions & Patterns
What the codebase expects (from CLAUDE.md + observed patterns)

## Data Flow
How a request/action moves through the system end-to-end

## Entry Points for Common Tasks
- "To add a new API endpoint, start at..."
- "To add a new UI page, create..."
- "To modify the database schema..."

## Development Setup
Commands to install, build, test, and run

## External Integrations
APIs, databases, services the project talks to
```

### Phase 4: Follow-up

After presenting the report summary, offer to answer questions about specific areas. Stay in conversational mode until the user moves on.

## What This Skill Does NOT Do

- No code changes or refactoring suggestions
- No quality judgments (that's what `/audit` is for)
- No git operations
