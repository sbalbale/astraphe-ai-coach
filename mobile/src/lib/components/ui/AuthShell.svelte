<script lang="ts">
  import type { Snippet } from 'svelte';
  import BrandMark from './BrandMark.svelte';
  import UiIcon from './UiIcon.svelte';

  /**
   * Layout for signed-out screens: an optional back link or brand header, a serif
   * title, subtitle, body, and a footer pinned to the bottom.
   */
  let {
    title,
    subtitle,
    brand = false,
    backLabel,
    backHref,
    onBack,
    centered = false,
    children,
    footer,
    subtitleContent,
  }: {
    title?: string;
    subtitle?: string;
    brand?: boolean;
    backLabel?: string;
    backHref?: string;
    onBack?: () => void;
    centered?: boolean;
    children?: Snippet;
    footer?: Snippet;
    subtitleContent?: Snippet;
  } = $props();
</script>

<div
  class="min-h-full flex flex-col bg-bg0 px-6"
  style="padding-top: max(24px, env(safe-area-inset-top, 0px)); padding-bottom: max(24px, env(safe-area-inset-bottom, 0px));"
>
  <div class="w-full max-w-md mx-auto flex-1 flex flex-col {centered ? 'justify-center items-center text-center' : ''}">
    {#if onBack}
      <button type="button" onclick={onBack} class="inline-flex items-center gap-2 text-text1 text-[16px] mt-2 mb-10 w-fit bg-transparent border-none p-0 cursor-pointer hover:text-text0">
        <UiIcon name="chevron-left" size={18} />
        {backLabel ?? 'Back'}
      </button>
    {:else if backHref}
      <a href={backHref} class="inline-flex items-center gap-2 text-text1 text-[16px] mt-2 mb-10 w-fit no-underline hover:text-text0">
        <UiIcon name="chevron-left" size={18} />
        {backLabel ?? 'Back'}
      </a>
    {:else if brand}
      <BrandMark size={44} wordmark class="mt-12 mb-10" />
    {/if}

    {#if title}
      <h1 class="font-display text-[44px] leading-[1.05] text-text0 mb-3 {!backHref && !onBack && !brand && !centered ? 'mt-16' : ''}">{title}</h1>
    {/if}
    {#if subtitleContent}
      <div class="text-[17px] text-text1 leading-relaxed mb-8">{@render subtitleContent()}</div>
    {:else if subtitle}
      <p class="text-[17px] text-text1 leading-relaxed mb-8">{subtitle}</p>
    {/if}

    {#if children}{@render children()}{/if}

    {#if footer}
      <div class="mt-auto pt-10 text-center">{@render footer()}</div>
    {/if}
  </div>
</div>
