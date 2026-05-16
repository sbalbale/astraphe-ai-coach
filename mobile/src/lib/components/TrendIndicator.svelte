<script lang="ts">
  import { ArrowUp, ArrowDown, Minus } from 'lucide-svelte';
  import { zScoreCssColor } from '$lib/scoreColors';

  let {
    z,
    inverted = false,
    size = 16,
    flatThreshold = 0.2
  } = $props<{
    z: number | null | undefined;
    inverted?: boolean;
    size?: number;
    flatThreshold?: number;
  }>();

  // Color always reflects the rule (z-score band) — direction (arrow) is just
  // the sign of the z. For inverted metrics (RHR), an "up" arrow visually means
  // the raw value rose, which is *bad*; the color (already inverted) carries the
  // good/bad signal.
  const color = $derived(z == null ? 'var(--text2)' : zScoreCssColor(z, inverted));
  const Icon = $derived(
    z == null || Math.abs(z) < flatThreshold ? Minus : (z > 0 ? ArrowUp : ArrowDown)
  );
</script>

<Icon {size} {color} strokeWidth={2.5} aria-hidden="true" />
