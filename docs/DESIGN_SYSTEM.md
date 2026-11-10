# Design System

ASTRAPHE's current visual language is "Graphite + Sky" (the November 2026 UI overhaul): dark-only, graphite surfaces that step up in lightness, warm off-white text, and a soft sky-blue brand accent used sparingly.

The source of truth is:

- `mobile/tailwind.config.js`
- `mobile/src/app.css` (CSS variables; keep in sync with the Tailwind config)
- shared Svelte components in `mobile/src/lib/components/` (primitives in `lib/components/ui/`)
- editor rules in `.cursor/rules/frontend-design.mdc`

The older "Spectral" palette (indigo `#4621FF`, Space Grotesk / Space Mono) is gone.

## Principles

1. Elevation comes from surface steps (`bg0` -> `bg3`) and borders, not blur or shadow.
2. Accent colors are semantic and should not be overused. `blue` (sky) is the brand accent.
3. Numeric metrics use `font-mono`; prose and UI chrome use `font-sans`; page titles and hero numbers may use `font-display`.
4. Prefer Tailwind tokens over hardcoded colors in class attributes.
5. Use Svelte 5 patterns: runes, snippets, `onclick`.

## Core Tokens

### Surfaces

| Tailwind | CSS variable | Value | Use |
|---|---|---|---|
| `bg-bg0` | `--bg0` | `#0E0E10` | Page background |
| `bg-bg1` | `--bg1` | `#141416` | Nav/section background |
| `bg-bg2` | `--bg2` | `#17171A` | Card background |
| `bg-bg3` | `--bg3` | `#1F1F23` | Elevated surfaces |
| `bg-glass` | `--glass` | `rgba(255,255,255,0.03)` | Subtle translucent layer |
| `bg-glass2` | `--glass2` | `rgba(255,255,255,0.06)` | Stronger translucent layer |
| `border-border` | `--border` | `#26262B` | Dividers and card borders |
| `bg-rail` (`-border`, `-hover`) | none | `#121214` / `#222226` / `#1A1A1E` | Wide-layout sidebar |
| `bg-popover` (`-border`) | none | `#1B1B1F` / `#2E2E34` | Popovers, menus, command palette |
| `bg-accent-surface` (`-border`, `-avatar`) | none | `#15212F` / `#2E3B4C` / `#1F2A38` | Selected surfaces tinted with the accent |

Backdrop blur is used only on overlays (modal scrim, dropdown/select/time-picker menus). Do not add it to normal cards.

### Text

| Tailwind | CSS variable | Value | Use |
|---|---|---|---|
| `text-text0` | `--text0` | `#EDEBE6` | Primary text |
| `text-text1` | `--text1` | `#A9A69E` | Secondary text |
| `text-text2` | `--text2` | `#8A877F` | Muted labels/metadata |
| `text-text3` | none | `#6A6A72` | Quietest text: shortcut hints, placeholders |
| `text-on-accent` | none | `#0B1420` | Text on sky fills (primary buttons, selected chips) |

`text3` and `on-accent` are Tailwind-only; there is no matching CSS variable.

### Accents

| Tailwind | CSS variable | Value | Use |
|---|---|---|---|
| `blue` | `--blue` | `#7FB4FF` | Brand accent: primary actions, selected states, fitness |
| `sky` | `--sky` | `#7FB4FF` | Same value as `blue` |
| `teal` | `--teal` | `#00C8A8` | Recovery, success, positive deltas |
| `amber` | `--amber` | `#FFCB88` | Load, caution, fatigue |
| `red` | `--red` | `#F07178` | Stress, alerts, high intensity |
| `violet` | `--violet` | `#B49CFF` | Secondary accent |
| `steel` | `--steel` | `#6B7FA3` | Neutral data accent |
| `green` | `--green` | `#6FCF97` | Positive/secondary success |

Each accent has a `-dim` variant (about 14-15% alpha) for tinted backgrounds. `blue` also has `blue-glow` (30% alpha).

The `astraphe-*` colors (`neutral`, `muted`, `teal`, `amber`, `red`, `blue`) are used by the score color rules in `mobile/src/lib/scoreColors.ts` (`text-astraphe-*`) to color recovery/sleep/strain scores and related values.

Sleep stage colors are CSS variables only: `--stage-deep` (`#4C7CF0`) and `--stage-light` (`#8DB3E8`). A few other charts reuse them.

### Zone Colors

Heart-rate zone colors are CSS variables, not Tailwind tokens:

| Variable | Value | Zone |
|---|---|---|
| `--zone-0` | `#94a3b8` | Rest |
| `--zone-1` | `#579BFA` | Z1 |
| `--zone-2` | `#00C8A8` | Z2 |
| `--zone-3` | `#FFCB88` | Z3 |
| `--zone-4` | `#FF8C42` | Z4 |
| `--zone-5` | `#F07178` | Z5 |

Use them through `style=""` or chart constants, not as generic UI accents.

### Chart Identities

Training-load chart colors:

| Token | Value | Use |
|---|---|---|
| `chartCtl` | `#7FB4FF` | CTL/fitness (the accent) |
| `chartAtl` | `#6A6A72` | ATL/fatigue (neutral grey) |

For canvas/D3/MapLibre/SVG presentation attributes, use hex constants rather than CSS variables.

## Typography

Fonts are loaded from Google Fonts in `mobile/src/routes/+layout.svelte`:

- `font-sans`: Inter
- `font-mono`: JetBrains Mono
- `font-display`: Instrument Serif (weight 400; page titles and hero numbers)

Rules:

- Metric values, scores, watts, HR, paces, dates used as data, tags, and compact labels use `font-mono`.
- Body copy, AI text, buttons, and descriptive labels use `font-sans`.
- Uppercase mono labels use wide tracking (`tracking-widest` or an explicit `tracking-[0.14em]`).

## Component Patterns

### Card

`Card.svelte` takes a `children` snippet and renders `rounded-card` (24px) with `border-border` on `bg-bg2`, or `bg-bg3` when `glass2` is set. Padding defaults to `p-4` (`paddingClass` overrides it).

```svelte
<Card>
  <p>Content</p>
</Card>
```

### Button

Use `lib/components/ui/Button.svelte`. Variants: `primary` (sky fill, `text-on-accent`), `secondary` (outlined), `ghost` (text only). Sizes `lg` (default) and `sm`; full width unless `full={false}`.

```svelte
<Button onclick={handleClick}>Continue</Button>
```

Other primitives in `lib/components/ui/`: `TextField`, `FormAlert`, `Spinner`, `EmptyStateCard`, `DashedNote`, `UiIcon`, `BrandMark`, `AuthShell`, `PasswordStrengthMeter`.

### Metric

```svelte
<div class="flex flex-col gap-0.5">
  <span class="text-[10px] font-mono text-text2 uppercase tracking-widest">Label</span>
  <span class="text-3xl font-mono font-bold text-text0 leading-none">72</span>
  <span class="text-[11px] font-mono text-text1">score</span>
</div>
```

### Tag

`Tag.svelte` takes a `color` (hex) and renders a small mono uppercase pill tinted with that color.

## Svelte 5 Rules

Use runes for new components:

```svelte
<script lang="ts">
  let { value = 0 }: { value: number } = $props();
  let loading = $state(false);
  let displayValue = $derived(value.toFixed(1));
</script>
```

Prefer:

- `$state` for reactive mutable values.
- `$derived` for computed values.
- `$props` for props.
- snippets and `{@render}` over slots.
- keyed `{#each}` blocks.

Avoid:

- `$:` reactive statements.
- `export let`.
- `on:click`.
- shared mutable module state for request/user-scoped state (user caches must be cleared in `lib/stores/userSession.ts`).

## Tailwind Rules

- Use Astraphe tokens instead of standard Tailwind palette colors for UI.
- Opacity modifiers should be standard Tailwind steps such as `/5`, `/10`, `/20`, `/30`, `/50`.
- Keep exact non-token colors in `style=""`, canvas/SVG/D3/MapLibre constants, or documented third-party brand cases.
- `pb-safe` / `pt-safe` are not configured. Safe-area insets are handled in CSS: the installed PWA pads the top in `app.css`, and `BottomNav` owns the bottom inset.

## Accessibility

Targets:

- Interactive controls should be touch friendly (44 px is common, e.g. `w-11 h-11`).
- Icon-only buttons need labels.
- Color should not be the only signal.
- Data visualizations need text labels/legends where practical.
- Motion should be minimal and functional.

## Light Mode

The product is dark only. Light mode is not implemented.
