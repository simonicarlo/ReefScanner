---
paths:
  - "app/frontend/**/*.ts"
  - "app/frontend/**/*.tsx"
  - "app/frontend/**/*.css"
---

# Frontend Conventions (React, TypeScript, TanStack Query, CSS Modules)

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
- The design language is Clear Water
  (`docs/specs/v3/features/2026-10-30-clear-water-design.md`); follow it for
  new screens
- Plain CSS: a `Component.module.css` next to each component or page, its
  rules inside `@layer components`, native nesting allowed. No CSS framework,
  no preprocessor, no inline style objects except for computed values
  (positions, widths, a verdict colour)
- Every colour, size, corner, duration and shadow comes from
  `styles/tokens.css`; no literal colours or shadows in modules. A new value
  goes into the tokens for both modes
- Both modes work everywhere: test light and dark, and translucency on and
  off. Glass (`--glass-bg`, `--glass-filter`) is for chrome only, never over
  footage
- Reuse the primitives in `components/ui.tsx`, `SegmentedControl`, `Switch`,
  `PageHeader`, `ReviewBar` before writing new ones
- Verdicts look and are entered the same everywhere: take labels, keys,
  tones and colours from `lib/verdicts.ts`. Marks drawn on footage use
  `mark`, which is the same in both modes
- Motion uses `--ease-settle` and the `--dur-*` tokens; nothing animates on
  its own, and `prefers-reduced-motion` turns transitions off
- Keyboard first in review screens: every verdict action has a shortcut
