<script lang="ts">
  import { WEEK_STARTS_ON } from '$lib/utils/week';
  /**
   * Today on tablets / desktop (designs: WToday landscape, WTodayPortrait).
   * Landscape: session + week on the left, readiness + coach on the right.
   * Portrait: session, week, then readiness and coach side by side.
   */
  import { addDays, format, startOfWeek } from 'date-fns';
  import { api } from '$lib/api';
  import type { Workout } from '$lib/types/training';
  import TodaySessionCard from './TodaySessionCard.svelte';
  import TodayWeekStrip from './TodayWeekStrip.svelte';
  import TodayReadinessCard from './TodayReadinessCard.svelte';
  import TodayCoachCard from './TodayCoachCard.svelte';
  import { moveChanges } from './todayWide';

  let {
    todayIso,
    landscape,
    ftp,
    provisional = false,
    readiness,
    coachNote,
    onPlanChanged
  }: {
    todayIso: string;
    landscape: boolean;
    ftp: number;
    provisional?: boolean;
    readiness: {
      score: number | null;
      recovery: number | null;
      hrv: number | null;
      sleepLabel: string | null;
      form: number | null;
      stale: boolean;
      notes: string[];
    } | null;
    coachNote: string;
    /** After a move, so the page can refresh anything else showing the plan. */
    onPlanChanged?: () => void;
  } = $props();

  const weekStart = $derived(startOfWeek(new Date(todayIso + 'T12:00:00'), { weekStartsOn: WEEK_STARTS_ON }));
  const days = $derived(Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)));
  const startIso = $derived(format(days[0], 'yyyy-MM-dd'));
  const endIso = $derived(format(days[6], 'yyyy-MM-dd'));

  let week = $state<Workout[]>([]);
  let reloadTick = $state(0);
  $effect(() => {
    const from = startIso;
    const to = endIso;
    void reloadTick;
    let cancelled = false;
    api.getWorkouts(from, to).then(
      (rows) => {
        if (!cancelled) week = rows;
      },
      () => {}
    );
    return () => {
      cancelled = true;
    };
  });

  const byIso = $derived.by(() => {
    const out: Record<string, Workout[]> = {};
    for (const w of week) (out[w.date] ??= []).push(w);
    return out;
  });

  let selectedIso = $state('');
  $effect(() => {
    // Back to today when the day rolls over.
    selectedIso = todayIso;
  });
  const selected = $derived((byIso[selectedIso] ?? [])[0] ?? null);

  let saving = $state(false);
  let error = $state<string | null>(null);
  let toast = $state<string | null>(null);
  let undoChanges: { id: string; date: string }[] = [];

  async function apply(changes: { id: string; date: string }[]): Promise<boolean> {
    saving = true;
    error = null;
    try {
      let ok = true;
      for (const c of changes) {
        const current = week.find((w) => w.id === c.id);
        if (!current) {
          ok = false;
          continue;
        }
        const saved = await api.saveWorkout({ ...current, date: c.date });
        if (!saved) ok = false;
      }
      reloadTick++;
      onPlanChanged?.();
      if (!ok) error = "Couldn't update the plan. Try again.";
      return ok;
    } finally {
      saving = false;
    }
  }

  async function move(targetIso: string) {
    const w = selected;
    if (!w) return;
    const changes = moveChanges(w, targetIso, week);
    if (!changes.length) return;
    const other = changes[1] ? week.find((x) => x.id === changes[1].id) : null;
    const before = changes.map((c) => ({ id: c.id, date: week.find((x) => x.id === c.id)?.date ?? c.date }));
    if (await apply(changes)) {
      undoChanges = before;
      const dayName = format(new Date(targetIso + 'T12:00:00'), 'EEEE');
      toast = other ? `${w.title} moved to ${dayName}. ${other.title} takes its place.` : `${w.title} moved to ${dayName}.`;
      selectedIso = targetIso;
    }
  }

  async function undo() {
    const changes = undoChanges;
    if (!changes.length) return;
    if (await apply(changes)) {
      const back = changes.find((c) => c.id === selected?.id)?.date ?? changes[0].date;
      selectedIso = back;
      toast = null;
      undoChanges = [];
    }
  }
</script>

{#snippet session()}
  <TodaySessionCard
    workout={selected}
    dayIso={selectedIso || todayIso}
    {todayIso}
    {days}
    {byIso}
    {ftp}
    {provisional}
    {saving}
    {error}
    {toast}
    onMove={move}
    onUndo={undo}
    onDismissToast={() => {
      toast = null;
      undoChanges = [];
    }}
  />
{/snippet}

{#snippet weekStrip()}
  <TodayWeekStrip {days} {byIso} selectedIso={selectedIso || todayIso} {todayIso} onSelect={(iso) => (selectedIso = iso)} />
{/snippet}

{#if landscape}
  <div class="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-5 min-h-[calc(100vh-180px)]">
    <div class="flex flex-col gap-5 min-h-0">
      {@render session()}
      {@render weekStrip()}
    </div>
    <div class="flex flex-col gap-5 min-h-0">
      {#if readiness}
        <TodayReadinessCard {...readiness} />
      {/if}
      <div class="flex-1 min-h-[320px] flex">
        <TodayCoachCard note={coachNote} fill />
      </div>
    </div>
  </div>
{:else}
  <div class="flex flex-col gap-[22px]">
    {@render session()}
    {@render weekStrip()}
    <div class="grid grid-cols-2 gap-5 items-stretch">
      {#if readiness}
        <TodayReadinessCard {...readiness} vertical />
      {/if}
      <div class="h-[420px] flex {readiness ? '' : 'col-span-2'}">
        <TodayCoachCard note={coachNote} fill />
      </div>
    </div>
  </div>
{/if}
