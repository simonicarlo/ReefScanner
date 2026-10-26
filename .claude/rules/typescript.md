---
paths:
  - "app/frontend/**/*.ts"
  - "app/frontend/**/*.tsx"
  - "app/frontend/**/*.css"
---

# Frontend Conventions (React, TypeScript, TanStack Query, Tailwind)

## Typing
- Domain models are `export interface` in `lib/types.ts`, mirroring
  `app/schemas.py` field for field (snake_case, as the API sends them)
- No `type` aliases for domain models; the exception is unions derived from an
  `as const` array (`export type Verdict = (typeof VERDICTS)[number]`)
- Nullable fields: `field: string | null`; `?` only when the API may omit it
- API responses are fully typed; never `any`
- Strict mode stays on

## Naming
- Files: `PascalCase.tsx` for components and pages, `camelCase.ts` for modules
  in `lib/`
- Components and interfaces: `PascalCase`, no `I` prefix
- Module-level constants: `UPPER_SNAKE_CASE`; locals `camelCase`

## Data and Errors
- All server data goes through TanStack Query hooks in `lib/queries.ts`; raw
  `fetch` only in `lib/api.ts`
- Every query and mutation that can fail renders its error (`<ErrorNote>`);
  never just `console.error`
- Disable buttons while their mutation is pending, so a failure can't leave a
  stuck or doubled action
- Encode ids in URLs with `encodeURIComponent` (Camtrap ids contain `:`)
- Show times in the zone the data states (camera timezone), never the viewer's

## Styling
- Tailwind utilities with the design tokens from `index.css` (`bg-panel`,
  `text-signal`, `border-rule`); no hardcoded colours or ad-hoc hex values
- Verdict colours keep their meaning everywhere: signal = confirmed,
  reject = rejected, hedge = unsure
- Keyboard first in review screens: every verdict action has a shortcut
