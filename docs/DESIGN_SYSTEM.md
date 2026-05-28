# Design System

ASTRAPHE's visual language is "Spectral": dark-first, high-contrast, data dense, and built from translucent layers with surgical accent color.

The source of truth is:

- `mobile/tailwind.config.js`
- `mobile/src/app.css`
- shared Svelte components in `mobile/src/lib/components/`
- frontend rules in `.cursor/rules/frontend-design.mdc`

## Principles

1. Elevation comes from layered opacity and borders, not heavy blur.
2. Accent colors are semantic and should not be overused.
3. Numeric metrics use `font-mono`; prose and UI chrome use `font-sans`.
4. Prefer Tailwind tokens over hardcoded colors in class attributes.
5. Use Svelte 5 patterns: runes, snippets, `onclick`, and tokenized classes.

## Core Tokens

### Surfaces

| Tailwind | CSS variable | Value | Use |
|---|---|---|---|
| `bg-bg0` | `--bg0` | `#08080F` | Page background |
| `bg-bg1` | `--bg1` | `#0F0F1A` | Nav/section background |
| `bg-bg2` | `--bg2` | `#141424` | Card background |
| `bg-bg3` | `--bg3` | `#1C1C30` | Elevated surfaces |
| `bg-glass` | `--glass` | `rgba(255,255,255,0.04)` | Standard glass card |
| `bg-glass2` | `--glass2` | `rgba(255,255,255,0.08)` | Elevated/interactive card |
| `border-border` | `--border` | `rgba(255,255,255,0.07)` | Dividers and card borders |

Glass surfaces are opacity layers. Do not add backdrop blur to normal cards; keep blur for modal/overlay contexts only if needed.

### Text

| Tailwind | CSS variable | Use |
|---|---|---|
| `text-text0` | `--text0` | Primary text |
| `text-text1` | `--text1` | Secondary text |
| `text-text2` | `--text2` | Muted labels/metadata |

`text-text3` is not defined.

### Accents

| Tailwind | CSS variable | Use |
|---|---|---|
| `blue` | `--blue` | Primary actions, selected states, fitness |
| `teal` | `--teal` | Recovery, success, positive deltas |
| `amber` | `--amber` | Load, caution, fatigue |
| `red` | `--red` | Stress, alerts, high intensity |
| `sky` | `--sky` | Secondary blue accent |
| `violet` | `--violet` | Specialty/secondary accent |
| `steel` | `--steel` | Neutral data accent |
| `green` | `--green` | Positive/secondary success |

Dim variants exist for `blue`, `teal`, `amber`, `red`, `sky`, `violet`, `steel`, and `green`.

### Zone Colors

Zone colors are CSS variables, not Tailwind tokens:

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
| `chartCtl` | `#3b82f6` | CTL/fitness |
| `chartAtl` | `#334155` | ATL/fatigue |

For canvas/D3/MapLibre/SVG presentation attributes, use hex constants rather than CSS variables.

## Typography

Fonts:

- `font-sans`: Space Grotesk
- `font-mono`: Space Mono

Rules:

- Metric values, scores, watts, HR, paces, dates used as data, tags, and compact labels use `font-mono`.
- Body copy, AI text, buttons, headings, and descriptive labels use `font-sans`.
- Uppercase labels generally use `tracking-widest`.

## Component Patterns

### Card

The shared `Card.svelte` component uses Svelte 5 snippets:

```svelte
<Card>
  <p>Content</p>
</Card>
```

It renders a rounded border layer with either `bg-glass` or `bg-glass2`. Do not assume backdrop blur is present.

### Metric

```svelte
<div class="flex flex-col gap-0.5">
  <span class="text-[10px] font-mono text-text2 uppercase tracking-widest">
    Label
  </span>
  <span class="text-3xl font-mono font-bold text-text0 leading-none">
    72
  </span>
  <span class="text-[11px] font-mono text-text1">score</span>
</div>
```

### Badge

```svelte
<span class="inline-flex items-center rounded px-2 py-0.5 text-[10px] font-mono uppercase tracking-wide bg-teal-dim text-teal border border-teal/30">
  Good
</span>
```

### Button

```svelte
<button
  class="w-full rounded-xl bg-blue px-4 py-3 text-sm font-semibold text-text0 transition-colors disabled:opacity-40"
  onclick={handleClick}
>
  Continue
</button>
```

Use `onclick`, not legacy `on:click`.

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
- snippets and `{@render}` over slots in new components.
- keyed `{#each}` blocks.

Avoid:

- `$:` reactive statements in new code.
- `export let`.
- `on:click`.
- shared mutable module state for request/user-scoped state.

## Tailwind Rules

- Use Astraphe tokens instead of standard Tailwind palette colors for UI.
- Opacity modifiers should be standard Tailwind steps such as `/5`, `/10`, `/15`, `/20`, `/25`, `/30`, `/40`, `/50`.
- Keep exact non-token colors in `style=""`, canvas/SVG/D3/MapLibre constants, or documented third-party brand cases.
- Do not use `pb-safe` or `pt-safe`; they are not configured.

## Accessibility

Targets:

- Interactive controls should be touch friendly.
- Icon-only buttons need labels.
- Color should not be the only signal.
- Data visualizations need text labels/legends where practical.
- Motion should be minimal and functional.

## Light Mode

The current product is dark-mode native. Light mode is not implemented.
