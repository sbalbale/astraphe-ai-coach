<script lang="ts">
  /**
   * Wide Coach, right pane: "What I can see" (design: WCoach). Only real data: a card
   * without data is left out rather than shown with placeholders.
   */
  import { format } from 'date-fns';
  import { api } from '$lib/api';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { currentRecoveryState, readinessScoreFromRow } from '$lib/utils/biometrics';
  import { BAND_COPY, readinessBand } from '$lib/readiness';
  import type { Workout } from '$lib/types/training';
  import { connectedSourcesLabel, sessionMeta, weekLoad, weekRange } from './coachContext';

  const range = weekRange();
  const todayIso = format(new Date(), 'yyyy-MM-dd');

  let planned = $state<Workout[]>([]);
  $effect(() => {
    let cancelled = false;
    api.getWorkouts(range.start, range.end).then(
      (rows) => {
        if (!cancelled) planned = rows ?? [];
      },
      () => {}
    );
    return () => {
      cancelled = true;
    };
  });

  const recovery = $derived(
    currentRecoveryState(athleteStore.biometrics?.series, athleteStore.profile?.timezone_offset_min)
  );
  /** Today's readiness only; yesterday's carried-over number would read as today's. */
  const readiness = $derived(recovery.hasTodayRow ? readinessScoreFromRow(recovery.row) : null);
  const band = $derived(readiness != null ? BAND_COPY[readinessBand(readiness)] : null);

  const load = $derived(weekLoad(athleteStore.workouts, planned, range));
  const today = $derived(planned.find((w) => w.date === todayIso) ?? null);
  const sources = $derived(connectedSourcesLabel(athleteStore.syncStatus?.integrations));

  const card = 'flex p-3.5 rounded-2xl bg-bg2 border border-border no-underline text-text0 hover:border-text3 transition-colors';
</script>

<aside aria-label="What your coach can see" class="flex-none w-[280px] h-full box-border px-5 py-8 border-l border-rail-border bg-rail flex flex-col gap-3.5 overflow-y-auto">
  <span class="font-mono text-[11px] tracking-[0.14em] text-text2">WHAT I CAN SEE</span>

  {#if readiness != null && band}
    <a href="/readiness" class="{card} justify-between items-center">
      <span class="flex flex-col gap-0.5">
        <span class="text-[11px] text-text2">Readiness</span>
        <span class="font-display text-[32px] leading-none">{readiness}</span>
      </span>
      <span class="text-[12px]" style="color: {band.color}">{band.verdict}</span>
    </a>
  {/if}

  {#if load}
    <a href="/training" class="{card} flex-col gap-2">
      <span class="text-[11px] text-text2">This week</span>
      <span class="text-[15px] font-medium">{load.planned > 0 ? `${load.done} / ${load.planned} TSS` : `${load.done} TSS`}</span>
      {#if load.planned > 0}
        <span aria-hidden="true" class="h-1.5 rounded-[3px] bg-border overflow-hidden"><span class="block h-1.5 bg-blue" style="width: {load.pct}%"></span></span>
      {/if}
    </a>
  {/if}

  {#if today}
    <a href="/plan" class="{card} flex-col gap-1">
      <span class="text-[11px] text-text2">Today's session</span>
      <span class="text-[15px] font-medium">{today.title}</span>
      {#if sessionMeta(today)}<span class="font-mono text-[11px] text-text2">{sessionMeta(today)}</span>{/if}
    </a>
  {/if}

  <a href="/profile/connections" class="{card} flex-col gap-1.5">
    <span class="text-[11px] text-text2">Data sources</span>
    <span class="text-[13px]">{sources || 'Nothing connected yet'}</span>
    <span class="text-[11px] text-text3">{sources ? 'Read-only' : 'Connect an app so I can see your training'}</span>
  </a>
</aside>
