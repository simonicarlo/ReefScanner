# Clear Water: the field app's design language

After phase 0 the review UI worked but looked like every other AI-made
frontend: navy chrome, a cyan accent with a glow, uppercase tracked labels,
tinted outlined pills, a bordered box around everything. This note replaces
that look with **Clear Water**: simple, Mac-like, with rounded shapes, soft
motion and translucent panes that take their colour from the dive on screen.

Study (picked over a Japanese-minimalist alternative, "Indigo & Sumi"):
<https://claude.ai/artifact/PnXFCzzYhyJGVd5ydx2Ao1>

## Decisions

### 1. Principles

- **The footage is the subject.** Nothing covers the frame except the
  detection box and its label. The chrome is quiet and lighter or darker
  than the footage, never brighter.
- **Simple, not empty.** Few elements per screen, a clear hierarchy from size
  and weight, and grouping by space and soft fills rather than borders.
- **Native to the Mac.** The app runs in a Mac window (pywebview, WKWebView),
  so it uses the system font, system-like controls and the platform's motion.
  It should sit comfortably next to Photos and Finder.
- **Alive, not busy.** Translucency and motion give the app its feel, and
  each one is used in exactly one way (sections 4 and 5).

### 2. Light and dark, everywhere

Every screen works in both modes, the review screen included. The mode
follows the system by default. Settings offers **System / Light / Dark**.

Colour tokens (CSS custom properties, set on `<html data-mode="…">`):

| Token | Light | Dark | Use |
|---|---|---|---|
| `--win` | `#f5f5f7` | `#1e1e20` | window ground |
| `--surface` | `#ffffff` | `#2c2c2e` | buttons, fields, cards |
| `--label` | `#1d1d1f` | `#f5f5f7` | primary text |
| `--secondary` | `rgba(60,60,67,.62)` | `rgba(235,235,245,.62)` | secondary text |
| `--tertiary` | `rgba(60,60,67,.32)` | `rgba(235,235,245,.30)` | placeholders, key hints |
| `--sep` | `rgba(60,60,67,.14)` | `rgba(84,84,88,.55)` | hairlines |
| `--fill` | `rgba(118,118,128,.12)` | `rgba(118,118,128,.24)` | grouped rows, hover |
| `--fill-2` | `rgba(118,118,128,.20)` | `rgba(118,118,128,.34)` | tracks, selected rows |
| `--glass` | `rgba(250,250,252,.66)` | `rgba(36,36,38,.58)` | translucent panes |
| `--glass-solid` | `#ececf0` | `#2a2a2c` | panes with translucency off |
| `--stage` | `#ebebef` | `#0e0e10` | behind the footage |
| `--accent` | `#0071e3` | `#0a84ff` | selection, focus, primary action |

No other colours appear in components. A literal hex outside the token file
is a review finding.

### 3. Verdicts

| Verdict | Token | Light | Dark | Symbol | Key |
|---|---|---|---|---|---|
| Confirmed | `--green` | `#28a745` | `#30d158` | ✓ | T |
| Nothing there | `--red` | `#ff3b30` | `#ff453a` | ✕ | F |
| Something else | `--red` | same | same | − | O |
| Unsure | `--orange` | `#ff9500` | `#ff9f0a` | ? | U |

- Colour always comes with a symbol, so the verdict reads without colour.
- The two rejections share red and differ by symbol and label.
- A verdict button is a card. Selected, it fills with its colour, with white
  text and a soft coloured shadow.
- The detection box is white until the event has a verdict, then takes the
  verdict's colour. Marks drawn on footage (`--mark-*`) keep the brighter
  dark-mode colours in both modes, because the footage doesn't change with
  the mode and the light-mode green is weak on blue-green water. A
  reviewer's corrected box is dashed.
- Lists show the verdict as a small dot: filled when judged, a hollow ring
  when not reviewed.

### 4. Translucency

Translucency is **on by default**. It is what makes the app feel like water.

- **Ambient backdrop:** behind each window sits a heavily blurred
  (`blur(80px) saturate(1.25)`) copy of a frame. On the review screen that is
  the current event's peak frame. On a project or job page it is the
  project's cover frame (its most recent event with a confirmed verdict,
  otherwise its first event). With no frame, the backdrop is plain `--win`.
  Opacity is 0.3 in light mode and 0.7 in dark mode.
- **Glass panes** (`--glass` plus `backdrop-filter: blur(30px)
  saturate(180%)`) are used only for chrome: the title bar, sidebars, the
  inspector, toasts and popovers. Content areas are solid or nearly solid.
- **Never over the footage**, except the small label pill on the detection
  box.
- **Performance:** the backdrop is a still image, never the playing video.
  Changing events crossfades the backdrop. If scrolling or playback stutters
  in WKWebView on the dev Mac, the first step is fewer glass panes, not
  weaker blur.
- **Off switch:** a "Translucency" toggle in Settings swaps every pane to
  `--glass-solid` and hides the backdrop. The same happens when the engine
  reports `prefers-reduced-transparency: reduce`. That matters more for
  colour-critical review: the tint subtly shifts how the footage's colours
  read, and Settings says so in one line.

### 5. Motion

- One easing curve, `cubic-bezier(0.32, 0.72, 0, 1)`: a long, soft settle.
- Durations: 200 ms for presses and hovers, 300 ms for colour changes,
  450–500 ms for things that move (the segmented-control thumb, the
  detection box between events, mode and backdrop crossfades).
- Pressed buttons and verdict cards scale to 0.96–0.97.
- Nothing animates on its own: no pulsing, no looping sweeps. A running job
  shows determinate progress whenever the server knows it.
- `prefers-reduced-motion: reduce` turns all transitions off.

### 6. Type

- System font: `-apple-system, BlinkMacSystemFont, "SF Pro Text", …` for
  text, and `"SF Pro Display"` for titles of 20 px and up. The `@fontsource`
  packages go away.
- Numbers in columns (timecodes, scores, counts, ids) use
  `ui-monospace, "SF Mono"` with `tabular-nums`.
- Scale: 11 (captions, group labels), 13 (base), 15, 17 (card titles),
  22, 28 (page titles), 30–34 (the event time on the review screen).
  Titles are bold with slightly negative tracking.
- Sentence case everywhere. No uppercase micro-labels.

### 7. Shape and space

- Radius scale: 7 px for controls inside a segmented control, 8 px for buttons,
  fields and the detection box, 10 px for grouped rows, 12 px for cards,
  media and verdicts, 14 px for windows. Pills and switches are fully round.
- Spacing on a 4 px base. Panes pad 16–20 px, and gaps are 8, 12, 18 or 24 px.
- Hairlines are 0.5 px in `--sep`, used only between panes and between rows
  of a group.
- Shadows are soft and large, only on things that float: cards, media,
  toasts, selected verdicts.

### 8. Layout

- **App shell:** a glass sidebar with Projects and Settings, replacing the
  top bar. The window keeps macOS's own title bar; each page opens with its
  title and context (`Test · scan-1`). A "Waiting for review" group listing
  projects with unreviewed events follows with the project cards, which need
  the same per-project review counts from the API.
- **Projects:** cards with the project's cover frame, footage folder, run
  count and a thin progress bar split by verdict. Progress and cover come
  from the project's latest run with events (`latest_run` in the API), not
  a sum over runs: rescans of the same footage find the same animals again.
- **Review:** three columns. The event list on the left, the frame with its
  scrubber in the middle, and the inspector on the right (time, facts, the 2×2
  verdict cards with keys, species, notes). The list collapses below about
  1080 px, and the inspector drops under the frame below about 760 px.
- Keyboard shortcuts are unchanged.

### 9. Appearance settings

`AppSettings` gains `appearance_mode` (`system` / `light` / `dark`, default
`system`) and `translucency` (bool, default `true`), with one Alembic
migration. They live in the database rather than `localStorage`, because
pywebview's default private mode doesn't keep web storage between launches.
The frontend applies them as `data-mode` and `data-glass` on `<html>`. With
`system`, `prefers-color-scheme` decides.

### 10. CSS: plain CSS with CSS Modules

Tailwind and `@tailwindcss/vite` go. Styling moves to plain CSS, which Vite
handles without extra dependencies:

- `src/styles/tokens.css`: every token from sections 2–7, for both modes
- `src/styles/base.css`: the reset, body, focus ring, scrollbars and the
  reduced-motion rule
- `Component.module.css` next to each component and page, using native
  nesting and the tokens
- `@layer reset, base, components` so the order of the cascade is explicit

Why: the glass, the two modes and the motion are easier to read, review and
keep consistent as one stylesheet per component than as utility strings
spread through the JSX.

`.claude/rules/typescript.md` changes with the migration. Its styling section
will say: tokens only, CSS Modules per component, verdicts as in section 3,
and keyboard first.

### 11. Migration

One branch, in this order, with the app usable after each step:

1. Tokens, base styles, appearance settings (API and migration), the shell
   with the sidebar, and the ambient backdrop. The old Tailwind colour names
   point at the new tokens, so pages not yet moved follow light and dark
2. The primitives in `components/ui.tsx` (Button, Field, Input, Tag →
   status dot, Readout, Empty, ErrorNote, Spinner), plus a SegmentedControl,
   Switch and Toast
3. Pages: EventReview, then JobDetail, ProjectDetail, Projects, Settings,
   along with the panels they use
4. Remove Tailwind, the `@fontsource` packages and the old tokens; update the
   frontend rules

Done when no `className` holds a utility string, `npm run build` and the
lint pass, and each screen has been checked in both modes, with
translucency on and off, inside the desktop shell.

## Not now

- Custom accent colours or themes beyond light and dark.
- A Windows or Linux look. The shell targets the Mac, and other platforms
  get the same design with their system font.
- Animating the backdrop with live video.
