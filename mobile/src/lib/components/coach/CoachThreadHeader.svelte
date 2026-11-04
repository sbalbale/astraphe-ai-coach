<script lang="ts">
  /**
   * Top of a coach-started thread (design: Coach · opened from the notification):
   * "FROM YOUR COACH · POST-WORKOUT DEBRIEF" and the context card the thread is about
   * (workout / plan / week), linking to it.
   */
  import { navTo } from '$lib/nav';
  import { contextKindLabel, safeAppHref, triggerLabel, type CoachConversation } from '$lib/utils/coachThreads';

  let { conversation, wide = false }: { conversation: CoachConversation; wide?: boolean } = $props();

  const ctx = $derived(conversation.context ?? null);
  const href = $derived(safeAppHref(ctx?.href));
</script>

<div class="flex flex-col gap-3.5 {wide ? 'pb-1' : ''}">
  <span class="self-start flex items-center gap-1.5 px-2 py-1 rounded-[7px] bg-accent-surface font-mono text-[10px] tracking-[0.1em] text-blue">
    FROM YOUR COACH · {triggerLabel(conversation.trigger)}
  </span>
  {#if ctx && (ctx.title || ctx.meta)}
    {#if href}
      <a
        {href}
        class="flex items-center gap-3 px-3.5 py-3 rounded-[18px] bg-bg2 border border-border no-underline text-text0 hover:border-text3 transition-colors"
        onclick={(e) => {
          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
          e.preventDefault();
          navTo(href);
        }}
      >
        {@render body()}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="flex-none text-text3"><path d="m9 6 6 6-6 6"></path></svg>
      </a>
    {:else}
      <div class="flex items-center gap-3 px-3.5 py-3 rounded-[18px] bg-bg2 border border-border text-text0">{@render body()}</div>
    {/if}
  {/if}
</div>

{#snippet body()}
  <span class="flex-1 min-w-0 flex flex-col gap-[3px]">
    <span class="font-mono text-[10px] tracking-[0.12em] text-text2">{contextKindLabel(ctx?.kind)}</span>
    {#if ctx?.title}<span class="text-[15px] font-medium truncate">{ctx.title}</span>{/if}
    {#if ctx?.meta}<span class="text-[12px] text-text2 truncate">{ctx.meta}</span>{/if}
  </span>
{/snippet}
