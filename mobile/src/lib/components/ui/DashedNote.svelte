<script lang="ts">
  import type { Snippet } from 'svelte';

  /**
   * Dashed secondary card: a side note under an empty state ("MEANWHILE …"), a
   * placeholder for something that appears later, or a quiet info block.
   *   layout 'inline'  mono label left, text right (MEANWHILE)
   *   layout 'stacked' mono label above the content (YOUR NOTES)
   */
  let {
    label,
    layout = 'stacked',
    children,
  }: { label?: string; layout?: 'inline' | 'stacked'; children: Snippet } = $props();
</script>

<div class="border border-dashed border-border rounded-card px-6 py-5 {layout === 'inline' ? 'flex gap-5 items-start' : ''}">
  {#if label}
    <p class="font-mono text-[11px] tracking-[0.18em] uppercase text-text2 shrink-0 {layout === 'inline' ? 'pt-1' : 'mb-2'}">{label}</p>
  {/if}
  <div class="text-[16px] leading-relaxed text-text1 min-w-0 flex-1">{@render children()}</div>
</div>
