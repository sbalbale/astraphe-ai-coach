<script lang="ts">
  import type { Snippet } from 'svelte';
  import Button from './Button.svelte';
  import UiIcon, { type UiIconName } from './UiIcon.svelte';

  /**
   * Empty / not-set-up / waiting state (design: "Astrape Dark UI - empty states").
   * Icon tile + mono eyebrow + serif title + body + up to two stacked actions.
   *   tone: 'blue'    NOT SET UP (needs the user to connect or configure something)
   *         'amber'   WAITING FOR SYNC (data is expected, just not here yet)
   *         'neutral' NOTHING YET (nothing has happened yet; not a problem)
   */
  let {
    icon,
    tone = 'neutral',
    eyebrow,
    title,
    message,
    actionLabel,
    onAction,
    secondaryLabel,
    onSecondary,
    align = 'center',
    children,
  }: {
    icon: UiIconName;
    tone?: 'blue' | 'amber' | 'neutral';
    eyebrow?: string;
    title: string;
    message?: string;
    actionLabel?: string;
    onAction?: () => void;
    secondaryLabel?: string;
    onSecondary?: () => void;
    align?: 'center' | 'left';
    children?: Snippet;
  } = $props();

  const tile = {
    blue: 'bg-blue-dim border-blue/20 text-blue',
    amber: 'bg-amber-dim border-amber/20 text-amber',
    neutral: 'bg-bg3 border-border text-text1',
  };
  const eyebrowColor = { blue: 'text-blue', amber: 'text-amber', neutral: 'text-text2' };
  const center = $derived(align === 'center');
</script>

<section
  class="bg-bg2 border border-border rounded-card px-6 py-8 flex flex-col {center ? 'items-center text-center' : 'items-start text-left'}"
>
  <div class="w-14 h-14 rounded-2xl border flex items-center justify-center mb-5 {tile[tone]}">
    <UiIcon name={icon} size={24} />
  </div>
  {#if eyebrow}
    <p class="font-mono text-[11px] tracking-[0.22em] uppercase mb-2 {eyebrowColor[tone]}">{eyebrow}</p>
  {/if}
  <h2 class="font-display text-[30px] leading-[1.1] text-text0 mb-3">{title}</h2>
  {#if message}
    <p class="text-[16px] leading-relaxed text-text1 {center ? 'max-w-[34ch]' : ''}">{message}</p>
  {/if}
  {#if children}{@render children()}{/if}
  {#if actionLabel || secondaryLabel}
    <div class="w-full flex flex-col gap-3 mt-6">
      {#if actionLabel && onAction}
        <Button onclick={onAction}>{actionLabel}</Button>
      {/if}
      {#if secondaryLabel && onSecondary}
        <Button variant="secondary" onclick={onSecondary}>{secondaryLabel}</Button>
      {/if}
    </div>
  {/if}
</section>
