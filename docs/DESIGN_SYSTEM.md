# Design System

## Spectral Glassmorphism

APEX's visual language is called "Spectral." It is a dark-mode-native, high-contrast design system built around three principles:

1. **Depth through translucency.** Cards and panels are not opaque — they are frosted glass layers that reveal depth in the background without losing legibility.
2. **Color as signal.** Every color in the palette has a single, consistent semantic meaning. Blue = action/fitness, Teal = positive/recovery, Amber = caution/load, Red = stress/intensity.
3. **Typography as data.** Metrics are always rendered in the monospace `Space Mono` face. UI chrome uses `Space Grotesk`. The contrast between the two creates an immediate visual hierarchy.

---

## Color Tokens

### Background Scale

```css
--bg0: #08080F;   /* Base canvas. The darkest layer. */
--bg1: #0F0F1A;   /* Navigation bars, sidebars. */
--bg2: #141424;   /* Grouped content containers. */
--bg3: #1C1C30;   /* Elevated modals, drawers. */
```

Depth is achieved by layering these backgrounds, never through border lines alone. Moving from `bg0` → `bg3` creates visual elevation.

### Glass Surfaces

```css
--glass:  rgba(255, 255, 255, 0.04);   /* Standard card surface */
--glass2: rgba(255, 255, 255, 0.08);   /* Elevated / interactive surface */
```

Glass surfaces should always use `backdrop-filter: blur(20px) saturate(160%)` with a `border: 1px solid var(--border)` to define the edge.

### Borders

```css
--border: rgba(255, 255, 255, 0.07);   /* Subtle, never dominant */
```

### Semantic Accent Colors

Each accent color ships in three forms: a full color, a dim background, and a glow for box-shadows.

```css
/* Blue — Fitness, Primary Actions, Running */
--blue:       #4621FF;
--blue-dim:   rgba(70, 33, 255, 0.15);
--blue-glow:  rgba(70, 33, 255, 0.30);

/* Teal — Recovery, Success, Positive Delta */
--teal:       #00C8A8;
--teal-dim:   rgba(0, 200, 168, 0.15);

/* Amber — Load, Caution, Fatigue */
--amber:      #FFCB88;
--amber-dim:  rgba(255, 203, 136, 0.15);

/* Red — Stress, High Intensity, Alerts */
--red:        #F07178;
--red-dim:    rgba(240, 113, 120, 0.15);
```

### Text Scale

```css
--text0: #F0F0FF;                    /* Primary text. High contrast. */
--text1: rgba(240, 240, 255, 0.65);  /* Secondary text, labels. */
--text2: rgba(240, 240, 255, 0.35);  /* Tertiary text, metadata, disabled. */
```

---

## Typography

### Typefaces

```css
--font: 'Space Grotesk', sans-serif;   /* UI chrome, body copy */
--mono: 'Space Mono', monospace;        /* Metrics, numbers, timestamps, codes */
```

**Loading from Google Fonts:**
```html
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
```

### Type Scale

| Use Case | Size | Weight | Family |
|---|---|---|---|
| Screen title | 22px | 700 | Grotesk |
| Card heading | 13–15px | 600 | Grotesk |
| Body / AI messages | 13px | 400 | Grotesk |
| Labels / metadata | 11–12px | 400–500 | Grotesk |
| Tag / badge text | 9–10px | 600 | Mono |
| Metric values | 16–26px | 700 | Grotesk |
| Metric labels | 9–10px | 400 | Mono |
| Timestamps | 11px | 400 | Mono |

### Rules
- **Letter-spacing:** All-caps labels use `0.06–0.12em`. Metric labels use `0.08em`.
- **Line-height:** Body copy: `1.55`. AI messages: `1.6`. Compact metadata: `1.2`.
- **Tabular numerals:** All metric displays use `font-variant-numeric: tabular-nums` to prevent layout shift when values update.

---

## Component Patterns

### Card

The fundamental container. All content lives in cards.

```svelte
<!-- Svelte component -->
<div class="card" class:glass2={elevated}>
  <slot />
</div>

<style>
  .card {
    background: var(--glass);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 16px;
  }
  .card.glass2 {
    background: var(--glass2);
  }
</style>
```

**Gradient cards** (used for key metrics and readiness):
```svelte
<!-- Fitness card with blue gradient -->
<div class="card" style="background: linear-gradient(135deg, var(--blue-dim), transparent); border-color: var(--blue-glow)">
```

### Tag / Badge

Small status indicators.

```css
.tag {
  font-size: 9px;
  font-family: var(--mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 2px 7px;
  border-radius: 99px;
  /* Color is set inline: background = color + "22", border = color + "44" */
}
```

### Pill Button

Segmented selectors and filter tabs.

```css
.pill {
  padding: 6px 14px;
  border-radius: 99px;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
}
.pill.active {
  background: var(--blue);
  color: #fff;
  border-color: var(--blue);
}
.pill:not(.active) {
  background: var(--glass);
  color: var(--text1);
  border-color: var(--border);
}
```

### Radial Progress Ring

Used for Readiness, Recovery, and Strain scores.

The ring is drawn on a `<canvas>` element using two arcs: a background track at 7% white, and a value arc with a gradient fill. The gradient always runs from the secondary accent to the primary accent (blue → teal for recovery, for example).

```javascript
// Drawing the value arc
const grad = ctx.createLinearGradient(0, 0, size, size);
grad.addColorStop(0, accentColor);
grad.addColorStop(1, accentColor + 'AA');  // 67% opacity at tail

ctx.beginPath();
ctx.arc(cx, cy, r, startAngle, valueAngle);
ctx.strokeStyle = grad;
ctx.lineWidth = 4;
ctx.lineCap = 'round';
ctx.stroke();
```

### Telemetry Charts

All charts are implemented using LayerChart with D3 scales. Common chart patterns:

**Line chart with gradient fill:**
```svelte
<LayerChart {data} x="date" y="value">
  <AreaLayer fill="url(#grad)" opacity={0.3} />
  <LineLayer stroke={color} strokeWidth={2} />
  <defs>
    <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color={color} stop-opacity={0.5} />
      <stop offset="100%" stop-color={color} stop-opacity={0} />
    </linearGradient>
  </defs>
</LayerChart>
```

**Multi-line overlay (CTL + ATL):**
The `MultiLineChart` combines a bar series (ATL, rendered with 25% blue opacity) with a line+dot series (CTL, solid teal). The dual encoding (bars for fatigue, line for fitness) makes the Training Stress Balance immediately readable as the gap between them.

---

## Motion

APEX uses minimal motion. Animations serve one purpose: confirming state changes.

| Transition | Duration | Easing |
|---|---|---|
| Pill button active state | 200ms | ease |
| Toggle switch | 150ms | ease |
| Card gradient on hover | 200ms | ease |
| Progress bar fill on load | 600ms | ease |
| Segmented control thumb | 150ms | cubic-bezier(0.3, 0.7, 0.4, 1) |
| AI typing indicator dots | 1200ms | ease-in-out, staggered 200ms |

**No page transitions.** Navigation is instantaneous — content swaps in-place. On mobile, this eliminates the vestibular-motion concerns of slide animations and keeps the app feeling fast.

---

## Accessibility

WCAG AA compliance targets:

- All text on `--bg0` meets 4.5:1 contrast ratio (`--text0` achieves 16.5:1)
- Interactive elements have a minimum touch target of 44×44px
- All icon buttons have `aria-label` attributes
- Radial progress rings include a visually hidden text value for screen readers
- The segmented radio control uses `role="radiogroup"` and `role="radio"` with `aria-checked`
- Color is never the sole conveyor of meaning (tags include text labels; charts include axis labels)

---

## Dark / Light Mode

The current Spectral system is dark-mode native. A light-mode export is specified in the design documentation for future implementation:

```css
/* Light mode palette (future) */
--bg0: #FFFFFF;
--bg1: #F5F5F5;
--accent: #0055FF;     /* Electric Blue */
--secondary: #0088CC;  /* Deep Cyan */
--muted: #8D909D;
```

Light mode maintains the same semantic color roles but inverts the surface hierarchy. Implementation is deferred to post-MVP.
