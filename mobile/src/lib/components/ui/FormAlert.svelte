<script lang="ts">
  import type { Snippet } from 'svelte';

  /** Inline message above a form: errors, confirmations, neutral notes. */
  let {
    tone = 'error',
    class: className = '',
    children,
  }: { tone?: 'error' | 'success' | 'info'; class?: string; children: Snippet } = $props();

  const tones = {
    error: 'bg-red-dim border-red/30',
    success: 'bg-green-dim border-green/30',
    info: 'bg-bg2 border-border',
  };
</script>

<div
  role={tone === 'error' ? 'alert' : 'status'}
  class="px-4 py-3 border rounded-[14px] text-[14px] leading-relaxed text-text0 {tones[tone]} {className}"
>
  {@render children()}
</div>
