<script lang="ts">
  /**
   * Session picker for a recorded workout (design: PWorkoutLink, "Link to a planned session"):
   * planned sessions within two days, best fit first, with a confirm step before replacing
   * another recording's link or linking across sports. Bottom sheet on phone, dialog on wide.
   */
  import { viewport } from '$lib/stores/viewport.svelte';
  import type { PlanCandidate } from '$lib/types/linking';
  import { filterSessions, pendingFor, pickerTag, sessionMeta, type Pending } from '$lib/utils/workoutLinking';

  let {
    title,
    dateLabel,
    rows,
    workoutSport,
    busy = false,
    onpick,
    onclose
  }: {
    title: string;
    dateLabel: string;
    rows: PlanCandidate[];
    workoutSport: string;
    busy?: boolean;
    onpick: (c: PlanCandidate) => void;
    onclose: () => void;
  } = $props();

  let query = $state('');
  let pending = $state<{ row: PlanCandidate; info: Pending } | null>(null);
  const shown = $derived(filterSessions(rows, query));
  const wide = $derived(viewport.wide);

  function choose(c: PlanCandidate) {
    if (c.linked_here) return;
    const info = pendingFor(c, workoutSport);
    if (info) pending = { row: c, info };
    else onpick(c);
  }

  function chip(c: PlanCandidate): string {
    return c.fit.sport_ok ? 'var(--blue)' : 'var(--text3)';
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') onclose();
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="fixed inset-0 z-[70] bg-black/55" aria-hidden="true" onclick={onclose}></div>
<div
  role="dialog"
  aria-modal="true"
  aria-labelledby="wsp-title"
  class="fixed z-[71] box-border flex flex-col gap-3 bg-popover border-popover-border text-text0 {wide
    ? 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[520px] max-h-[640px] h-[80vh] rounded-[24px] border p-5'
    : 'left-0 right-0 bottom-0 h-[600px] max-h-[85vh] rounded-t-[28px] border-t px-4 pt-2.5 pb-5'}"
>
  {#if !wide}<span aria-hidden="true" class="self-center w-10 h-[5px] rounded-[3px] bg-text3/60"></span>{/if}
  <div class="flex justify-between items-start gap-3">
    <div class="flex flex-col gap-1 min-w-0">
      <h2 id="wsp-title" class="m-0 font-display font-normal text-[28px] leading-none">{title}</h2>
      <span class="text-[13px] text-text2">Sessions near {dateLabel}</span>
    </div>
    <button type="button" aria-label="Close" class="shrink-0 w-11 h-11 rounded-full border-0 bg-border text-text0 text-lg cursor-pointer" onclick={onclose}>×</button>
  </div>

  {#if !pending}
    <label for="wsp-q" class="sr-only">Search sessions</label>
    <input
      id="wsp-q"
      bind:value={query}
      placeholder="Search planned sessions"
      autocomplete="off"
      class="h-11 px-3.5 rounded-xl border border-popover-border bg-bg1 text-text0 text-[15px] outline-none placeholder:text-text3 focus:border-blue"
    />
    <div class="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1.5">
      {#each shown as c (c.id)}
        {@const tag = pickerTag(c)}
        <button
          type="button"
          disabled={busy || c.linked_here}
          class="flex items-center gap-3 p-3 rounded-[14px] text-left cursor-pointer disabled:cursor-default {c.linked_here
            ? 'bg-accent-surface border border-accent-surface-border'
            : 'bg-bg1 border border-rail-border hover:border-text3'}"
          onclick={() => choose(c)}
        >
          <span aria-hidden="true" class="shrink-0 w-1 h-10 rounded-sm" style="background: {chip(c)}"></span>
          <span class="flex-1 min-w-0 flex flex-col gap-[3px]">
            <span class="text-[14px] font-medium truncate">{c.title}</span>
            <span class="text-[12px] text-text2">{sessionMeta(c)}</span>
            <span class="text-[12px] {c.fit.sport_ok ? 'text-text1' : 'text-amber'}">{c.fit.reason}</span>
          </span>
          {#if tag}
            <span
              class="shrink-0 font-mono text-[9px] tracking-[0.08em] px-1.5 py-1 rounded-md {tag.kind === 'here'
                ? 'bg-accent-surface text-blue'
                : tag.kind === 'sport'
                  ? 'bg-bg3 text-text2'
                  : 'bg-border text-text0'}">{tag.label}</span
            >
          {/if}
        </button>
      {/each}
      {#if shown.length === 0}
        <span class="px-2 py-6 text-center text-[13px] text-text2">No planned sessions within two days match.</span>
      {/if}
    </div>
  {:else}
    <div class="flex flex-col gap-3 p-4 rounded-[18px] bg-amber-dim border border-amber/30">
      <span class="font-mono text-[10px] tracking-[0.14em] text-amber">{pending.info.kicker}</span>
      <span class="text-[15px] leading-normal">{pending.info.text}</span>
    </div>
    <div class="mt-auto grid grid-cols-2 gap-2">
      <button type="button" class="h-12 rounded-[14px] border border-popover-border bg-transparent text-text0 text-[15px] font-medium cursor-pointer" onclick={() => (pending = null)}>Back</button>
      <button
        type="button"
        disabled={busy}
        class="h-12 rounded-[14px] border-0 bg-blue text-on-accent text-[15px] font-semibold cursor-pointer disabled:opacity-50"
        onclick={() => pending && onpick(pending.row)}
      >{pending.info.cta}</button>
    </div>
  {/if}
</div>
