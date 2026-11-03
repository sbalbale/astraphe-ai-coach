<script lang="ts">
  /** Astraphe logo tile (same drawing as static/astraphe-logo.svg), optionally with the wordmark. */
  let {
    size = 40,
    wordmark = false,
    class: className = '',
  }: { size?: number; wordmark?: boolean; class?: string } = $props();
</script>

<div class="flex items-center gap-3 {className}">
  <svg width={size} height={size} viewBox="0 0 36 36" fill="none" role="img" aria-label="Astraphe">
    <rect x="1" y="1" width="34" height="34" rx="9" fill="#0E0E10" stroke="#2E2E34" stroke-width="0.75" />
    <circle cx="18" cy="18" r="7.2" stroke="#EDEBE6" stroke-width="1.4" />
    <path d="M18 7.5v21" stroke="#0E0E10" stroke-width="4.2" stroke-linecap="round" />
    <path d="M18 7.5v21" stroke="#7FB4FF" stroke-width="1.4" stroke-linecap="round" />
  </svg>
  {#if wordmark}
    <span class="font-display text-[28px] leading-none text-text0">Astraphe</span>
  {/if}
</div>
