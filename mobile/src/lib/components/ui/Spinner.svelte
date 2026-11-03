<script lang="ts">
  /** Ring spinner: border-coloured track with a sky arc. */
  let { size = 56, label = 'Loading' }: { size?: number; label?: string } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 48 48" fill="none" role="status" aria-label={label} class="animate-spin">
  <circle cx="24" cy="24" r="21" class="stroke-border" stroke-width="3" />
  <path d="M24 3a21 21 0 0 1 21 21" class="stroke-blue" stroke-width="3" stroke-linecap="round" />
</svg>
