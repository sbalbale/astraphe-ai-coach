<script lang="ts">
  /**
   * "Link a workout" / "Change workout" picker (design: Plan · link a workout, picker sheet).
   * Recorded workouts within two days of the session, grouped SAME DAY / WITHIN 2 DAYS, with
   * search and sport chips. Moving a link from another session or linking a different sport
   * asks for confirmation first. Bottom sheet on phones, centred dialog on wide screens.
   */
  import { tick } from 'svelte';
  import type { WorkoutCandidate } from '$lib/types/linking';
  import {
    candidateTag,
    groupCandidates,
    pendingConfirm,
    pickerSports,
    sportBadge,
    workoutMeta
  } from '$lib/utils/linking';

  let {
    title,
    subtitle,
    candidates,
    planSport,
    wide = false,
    busy = false,
    error = null,
    onclose,
    onpick
  }: {
    title: string;
    subtitle: string;
    /** null while loading. */
    candidates: WorkoutCandidate[] | null;
    planSport: string;
    wide?: boolean;
    busy?: boolean;
    error?: string | null;
    onclose: () => void;
    /** `move` when the workout completes another session and the athlete confirmed moving it. */
    onpick: (c: WorkoutCandidate, move: boolean) => void;
  } = $props();

  let query = $state('');
  let sport = $state('all');
  let pending = $state<WorkoutCandidate | null>(null);
  let searchEl = $state<HTMLInputElement | null>(null);

  const sports = $derived(pickerSports(candidates ?? []));
  const groups = $derived(groupCandidates(candidates ?? [], query, sport));
  const confirm = $derived(pending ? pendingConfirm(pending, planSport) : null);

  $effect(() => {
    void tick().then(() => searchEl?.focus({ preventScroll: true }));
  });

  function pick(c: WorkoutCandidate) {
    if (c.linked_here) {
      onclose();
      return;
    }
    if (pendingConfirm(c, planSport)) {
      pending = c;
      return;
    }
    onpick(c, false);
  }

  function fitClass(c: WorkoutCandidate): string {
    if (!c.fit.sport_ok) return 'text-amber';
    return c.fit.auto_ok ? 'text-green' : 'text-text1';
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      if (pending) pending = null;
      else onclose();
    }
  }
</script>

<div class="fixed inset-0 z-[70] flex {wide ? 'items-center justify-center p-8' : 'flex-col justify-end'}" role="presentation" onkeydown={onKey}>
  <button type="button" aria-label="Close" class="absolute inset-0 border-0 bg-black/55 cursor-default" onclick={onclose}></button>
  <div
    role="dialog"
    aria-modal="true"
    aria-labelledby="link-picker-title"
    class="relative flex flex-col gap-3 bg-popover border-popover-border text-text0 {wide ? 'w-full max-w-[520px] max-h-[80dvh] rounded-[24px] border p-5' : 'h-[min(640px,88dvh)] rounded-t-[28px] border-t px-4 pt-2.5'}"
    style={wide ? undefined : 'padding-bottom: max(20px, env(safe-area-inset-bottom, 0px));'}
  >
    {#if !wide}<span aria-hidden="true" class="self-center w-10 h-[5px] rounded-sm bg-border"></span>{/if}
    <div class="flex justify-between items-start gap-3">
      <div class="flex flex-col gap-1 min-w-0">
        <h2 id="link-picker-title" class="m-0 font-display font-normal text-[28px] leading-none">{title}</h2>
        <span class="text-[13px] text-text2 truncate">{subtitle}</span>
      </div>
      <button type="button" aria-label="Close" class="shrink-0 w-11 h-11 rounded-full border-0 bg-border text-text0 text-lg cursor-pointer" onclick={onclose}>×</button>
    </div>

    {#if pending && confirm}
      <div class="flex flex-col gap-3 p-4 rounded-[18px] bg-amber-dim border border-amber/30">
        <span class="font-mono text-[10px] tracking-[0.14em] text-amber">{confirm.kicker}</span>
        <span class="text-[15px] leading-normal">{confirm.text}</span>
      </div>
      <div class="flex items-center gap-3 p-3 rounded-2xl bg-bg1 border border-border">
        <span aria-hidden="true" class="shrink-0 w-10 h-10 rounded-xl bg-border text-text1 flex items-center justify-center font-mono text-[10px]">{sportBadge(pending.sport)}</span>
        <span class="flex-1 min-w-0 flex flex-col gap-0.5">
          <span class="text-[14px] font-medium truncate">{pending.title}</span>
          <span class="text-[12px] text-text2">{workoutMeta(pending)}</span>
        </span>
      </div>
      {#if error}<p role="alert" class="m-0 text-[13px] text-red">{error}</p>{/if}
      <div class="mt-auto grid grid-cols-2 gap-2">
        <button type="button" class="h-12 rounded-[14px] border border-popover-border bg-transparent text-text0 text-[15px] font-medium cursor-pointer" onclick={() => (pending = null)}>Back</button>
        <button
          type="button"
          disabled={busy}
          class="h-12 rounded-[14px] border-0 bg-blue text-on-accent text-[15px] font-semibold cursor-pointer disabled:opacity-50"
          onclick={() => pending && onpick(pending, confirm.move)}
        >{busy ? 'Linking…' : confirm.cta}</button>
      </div>
    {:else}
      <label for="link-picker-q" class="sr-only">Search workouts</label>
      <input
        id="link-picker-q"
        bind:this={searchEl}
        bind:value={query}
        placeholder="Search workouts"
        autocomplete="off"
        class="h-11 px-3.5 rounded-xl border border-popover-border bg-bg1 text-text0 text-[15px] outline-none placeholder:text-text3 focus:border-blue"
      />
      {#if sports.length > 2}
        <div role="radiogroup" aria-label="Sport" class="flex gap-1.5">
          {#each sports as sp (sp.id)}
            <button
              type="button"
              role="radio"
              aria-checked={sport === sp.id}
              class="flex-1 h-9 rounded-[10px] text-[12px] font-medium cursor-pointer border {sport === sp.id ? 'bg-border border-text3 text-text0' : 'bg-transparent border-border text-text2'}"
              onclick={() => (sport = sp.id)}
            >{sp.label}</button>
          {/each}
        </div>
      {/if}
      {#if error}<p role="alert" class="m-0 text-[13px] text-red">{error}</p>{/if}
      <div class="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1.5">
        {#if candidates === null}
          <div class="h-[68px] rounded-2xl bg-bg1 animate-pulse"></div>
          <div class="h-[68px] rounded-2xl bg-bg1 animate-pulse"></div>
        {:else if groups.length === 0}
          <span class="px-2 py-6 text-center text-[13px] leading-normal text-text2">No workouts within two days match. Try another sport, or clear the search.</span>
        {/if}
        {#each groups as g (g.name)}
          <span class="px-1 pt-1.5 pb-0.5 font-mono text-[10px] tracking-[0.14em] text-text3">{g.name}</span>
          {#each g.rows as r (r.id)}
            {@const tag = candidateTag(r)}
            <button
              type="button"
              disabled={busy}
              class="w-full min-h-[68px] flex items-center gap-3 px-3 py-2.5 rounded-2xl text-left text-text0 cursor-pointer disabled:cursor-default {r.linked_here ? 'bg-accent-surface border border-accent-surface-border' : r.linked_to ? 'bg-bg1 border border-rail-border opacity-75' : 'bg-bg1 border border-rail-border hover:border-text3'}"
              onclick={() => pick(r)}
            >
              <span aria-hidden="true" class="shrink-0 w-10 h-10 rounded-xl bg-border text-text1 flex items-center justify-center font-mono text-[10px]">{sportBadge(r.sport)}</span>
              <span class="flex-1 min-w-0 flex flex-col gap-[3px]">
                <span class="text-[14px] font-medium truncate">{r.title}</span>
                <span class="text-[12px] text-text2">{workoutMeta(r)}</span>
                <span class="text-[12px] {fitClass(r)}">{r.fit.reason}{r.dismissed ? ' · you said not this one' : ''}</span>
              </span>
              {#if tag}
                <span class="shrink-0 font-mono text-[9px] tracking-[0.08em] px-1.5 py-1 rounded-md {r.linked_here ? 'bg-accent-surface text-blue' : 'bg-border text-text2'}">{tag}</span>
              {/if}
            </button>
          {/each}
        {/each}
      </div>
    {/if}
  </div>
</div>
