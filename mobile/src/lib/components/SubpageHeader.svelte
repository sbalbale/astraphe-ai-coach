<script lang="ts">
  /** "‹ Back" link above a serif page title, for screens reached from another page (e.g. Me → Privacy). */
  import { navTo } from '$lib/nav';

  let {
    title,
    backLabel = 'Me',
    backHref = '/profile',
    subtitle = ''
  }: { title: string; backLabel?: string; backHref?: string; subtitle?: string } = $props();
</script>

<div class="flex flex-col gap-1.5 pt-1">
  <button type="button" class="self-start h-11 flex items-center gap-1 border-0 bg-transparent p-0 text-sm text-text1 cursor-pointer" onclick={() => navTo(backHref)}>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>{backLabel}
  </button>
  <h1 class="m-0 font-display font-normal text-[36px] leading-none">{title}</h1>
  {#if subtitle}<p class="m-0 mt-1.5 text-sm leading-[1.45] text-text2">{subtitle}</p>{/if}
</div>
