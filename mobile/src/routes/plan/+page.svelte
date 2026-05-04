<script lang="ts">
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import {
    addDays,
    endOfMonth,
    endOfWeek,
    format,
    isSameDay,
    isSameMonth,
    startOfMonth,
    startOfWeek
  } from 'date-fns';

  type AgendaView = 'day' | 'week';

  type RawPlanItem = {
    type?: string;
    title?: string;
    duration?: string;
    tss?: number | string;
    note?: string;
    goal?: string;
    context?: string;
    status?: string;
    intensity?: string;
    blocks?: Array<string | { title?: string; duration?: string; target?: string; note?: string }>;
    structure?: Array<string | { title?: string; duration?: string; target?: string; note?: string }>;
  };

  type PlannedWorkout = RawPlanItem & {
    id: string;
    isoDate: string; // yyyy-MM-dd (local)
    date: Date;
    dayKey?: string;
  };

  const dow = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  let selectedDate = $state<Date>(new Date());
  let agendaView = $state<AgendaView>('day');
  let selectedWorkout = $state<PlannedWorkout | null>(null);

  // Current month shown in the calendar (can be navigated independently).
  let viewMonth = $state<Date>(startOfMonth(new Date()));

  const planObj = $derived.by(() => athleteStore.plan?.plan as Record<string, RawPlanItem> | undefined);

  const plannedWorkouts = $derived.by<PlannedWorkout[]>(() => {
    const p = planObj;
    if (!p) return [];

    const y = viewMonth.getFullYear();
    const m = viewMonth.getMonth();

    const out: PlannedWorkout[] = [];
    for (const k of Object.keys(p)) {
      const item = p[k] ?? {};
      const dayNum = Number(k);
      if (!Number.isFinite(dayNum)) continue;

      const d = new Date(y, m, dayNum);
      if (Number.isNaN(d.getTime())) continue;

      const isoDate = format(d, 'yyyy-MM-dd');
      out.push({
        id: `${isoDate}:${k}`,
        isoDate,
        date: d,
        dayKey: k,
        ...item
      });
    }

    out.sort((a, b) => a.date.getTime() - b.date.getTime());
    return out;
  });

  const workoutsByIso = $derived.by(() => {
    const map: Record<string, PlannedWorkout[]> = {};
    for (const w of plannedWorkouts) {
      const arr = map[w.isoDate] ?? [];
      arr.push(w);
      map[w.isoDate] = arr;
    }
    return map;
  });

  const selectedIso = $derived(format(selectedDate, 'yyyy-MM-dd'));
  const selectedRange = $derived.by(() => {
    if (agendaView === 'day') {
      const start = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), selectedDate.getDate());
      const end = start;
      return { start, end };
    }
    const start = startOfWeek(selectedDate, { weekStartsOn: 1 });
    const end = endOfWeek(selectedDate, { weekStartsOn: 1 });
    return { start, end };
  });

  const agendaItems = $derived.by(() => {
    if (agendaView === 'day') return workoutsByIso[selectedIso] ?? [];
    const out: PlannedWorkout[] = [];
    for (let d = selectedRange.start; d <= selectedRange.end; d = addDays(d, 1)) {
      const iso = format(d, 'yyyy-MM-dd');
      const items = workoutsByIso[iso];
      if (items?.length) out.push(...items);
    }
    return out;
  });

  const gridStart = $derived(startOfWeek(startOfMonth(viewMonth), { weekStartsOn: 1 }));
  const gridEnd = $derived(endOfWeek(endOfMonth(viewMonth), { weekStartsOn: 1 }));
  const monthDays = $derived.by(() => {
    const out: Date[] = [];
    for (let d = gridStart; d <= gridEnd; d = addDays(d, 1)) out.push(d);
    return out;
  });

  const sportIcon = (w: RawPlanItem) => {
    const t = (w.type ?? '').toLowerCase();
    if (t.includes('run')) return '🏃';
    if (t.includes('bike') || t.includes('ride') || t.includes('cycle')) return '🚴';
    if (t.includes('swim')) return '🏊';
    if (t.includes('rest') || t.includes('off')) return '💤';
    if (t.includes('strength') || t.includes('gym')) return '💪';
    return '🎯';
  };

  const indicatorClass = (w: RawPlanItem) => {
    const intensity = (w.intensity ?? '').toLowerCase();
    const type = (w.type ?? '').toLowerCase();
    const title = (w.title ?? '').toLowerCase();
    const key = `${intensity} ${type} ${title}`;

    if (key.includes('endurance') || key.includes('easy') || key.includes('z2')) return 'bg-blue';
    if (key.includes('threshold') || key.includes('vo2') || key.includes('interval')) return 'bg-red';
    if (key.includes('recovery') || key.includes('rest')) return 'bg-teal';
    if (type.includes('run')) return 'bg-blue';
    if (type.includes('bike')) return 'bg-teal';
    return 'bg-amber';
  };

  const surfacePill =
    'inline-flex items-center gap-1 rounded-full border border-border bg-glass2 px-1 py-1 text-[12px] font-mono';

  function toggleView(v: AgendaView) {
    agendaView = v;
  }

  function selectDate(d: Date) {
    selectedDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (d.getFullYear() !== viewMonth.getFullYear() || d.getMonth() !== viewMonth.getMonth()) {
      viewMonth = startOfMonth(d);
    }
  }

  function openWorkout(w: PlannedWorkout) {
    selectedWorkout = w;
  }

  function closeWorkout() {
    selectedWorkout = null;
  }

  const stepsFor = (w: PlannedWorkout) => {
    const arr = (w.blocks ?? w.structure) as PlannedWorkout['blocks'] | undefined;
    if (Array.isArray(arr) && arr.length) return arr;
    const duration = (w.duration ?? '').toString().trim();
    const t = (w.type ?? '').toString().trim();
    return [
      `Warm up — 10 min easy (${t || 'session'})`,
      `Main set — ${duration || 'Work'} @ target (see coach notes)`,
      'Cool down — 5–10 min easy + mobility'
    ];
  };
</script>

<div class="flex flex-col gap-4">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">AI Orchestrated</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Plan</h1>
  </div>

  {#if authStore.tier !== 'premium'}
    <EmptyState
      title="Premium required"
      message="You must be a premium member to access the Training Plan feature."
      icon="🔒"
    />
  {:else if plannedWorkouts.length === 0}
    <EmptyState
      title="No Active Plan"
      message="Ask the AI Coach to generate a training plan based on your goals and current fitness."
      actionLabel="Go to Chat"
      icon="📋"
    />
  {:else}
    <div class="md:grid md:grid-cols-12 md:gap-6 flex flex-col gap-4">
      <!-- Calendar (desktop col-span-7) -->
      <div class="md:col-span-7">
        <div class="bg-glass border border-border rounded-2xl p-4">
          <div class="flex items-center justify-between mb-3">
            <div>
              <div class="text-[12px] text-slate-400 font-mono">Month</div>
              <div class="text-[16px] font-semibold">{format(viewMonth, 'MMMM yyyy')}</div>
            </div>
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="w-9 h-9 rounded-xl bg-glass2 border border-border/50 hover:bg-glass transition-colors"
                aria-label="Previous month"
                onclick={() => (viewMonth = new Date(viewMonth.getFullYear(), viewMonth.getMonth() - 1, 1))}
              >
                ‹
              </button>
              <button
                type="button"
                class="w-9 h-9 rounded-xl bg-glass2 border border-border/50 hover:bg-glass transition-colors"
                aria-label="Next month"
                onclick={() => (viewMonth = new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 1))}
              >
                ›
              </button>
            </div>
          </div>

          <div class="grid grid-cols-7 gap-2 mb-2">
            {#each dow as d (d)}
              <div class="text-[10px] text-slate-400 font-mono text-center py-1">{d}</div>
            {/each}
          </div>

          <div class="grid grid-cols-7 gap-2">
            {#each monthDays as d (d.toISOString())}
              {@const inMonth = isSameMonth(d, viewMonth)}
              {@const isSelected = isSameDay(d, selectedDate)}
              {@const iso = format(d, 'yyyy-MM-dd')}
              {@const items = workoutsByIso[iso] ?? []}
              <button
                type="button"
                class={[
                  'h-[64px] rounded-2xl border transition-colors text-left px-2.5 py-2 relative overflow-hidden',
                  inMonth ? 'border-border bg-glass2/30 hover:bg-glass2' : 'border-border/40 bg-transparent opacity-60 hover:opacity-80',
                  isSelected ? 'border-blue bg-[linear-gradient(135deg,rgba(70,33,255,0.18),transparent)]' : ''
                ].join(' ')}
                aria-label={format(d, 'yyyy-MM-dd')}
                onclick={() => selectDate(d)}
              >
                <div class="flex items-start justify-between">
                  <div class={['text-[12px] font-mono', isSelected ? 'text-text0' : 'text-text1'].join(' ')}>
                    {format(d, 'd')}
                  </div>
                  {#if items.length > 0}
                    <div class="flex items-center gap-1.5">
                      {#each items.slice(0, 3) as w (w.id)}
                        <span class={['w-2 h-2 rounded-full', indicatorClass(w)].join(' ')}></span>
                      {/each}
                      {#if items.length > 3}
                        <span class="text-[10px] text-slate-400 font-mono">+{items.length - 3}</span>
                      {/if}
                    </div>
                  {/if}
                </div>

                {#if items.length > 0}
                  {@const tss = Number(items[0]?.tss)}
                  <div class="absolute bottom-1.5 left-2.5 right-2.5 flex items-end justify-between">
                    <div class="text-[10px] text-slate-400 truncate">{items[0]?.title ?? items[0]?.type ?? 'Session'}</div>
                    <div class={['text-[10px] font-mono', Number.isFinite(tss) ? 'text-text0' : 'text-slate-400'].join(' ')}>
                      {Number.isFinite(tss) ? `${tss} TSS` : ''}
                    </div>
                  </div>
                {/if}
              </button>
            {/each}
          </div>
        </div>
      </div>

      <!-- Agenda (desktop col-span-5) -->
      <div class="md:col-span-5">
        <div class="bg-glass border border-border rounded-2xl p-4">
          <div class="flex items-center justify-between gap-3 mb-3">
            <div class="min-w-0">
              <div class="text-[12px] text-slate-400 font-mono">Agenda</div>
              <div class="text-[16px] font-semibold truncate">
                {#if agendaView === 'day'}
                  {format(selectedDate, 'EEE, MMM d')}
                {:else}
                  {format(selectedRange.start, 'MMM d')} – {format(selectedRange.end, 'MMM d')}
                {/if}
              </div>
            </div>

            <div class={surfacePill} role="tablist" aria-label="Agenda view">
              <button
                type="button"
                class={[
                  'px-3 py-1 rounded-full transition-colors',
                  agendaView === 'day' ? 'bg-blue text-white' : 'text-text0 hover:bg-glass'
                ].join(' ')}
                role="tab"
                aria-selected={agendaView === 'day'}
                onclick={() => toggleView('day')}
              >
                Day
              </button>
              <button
                type="button"
                class={[
                  'px-3 py-1 rounded-full transition-colors',
                  agendaView === 'week' ? 'bg-blue text-white' : 'text-text0 hover:bg-glass'
                ].join(' ')}
                role="tab"
                aria-selected={agendaView === 'week'}
                onclick={() => toggleView('week')}
              >
                Week
              </button>
            </div>
          </div>

          {#if agendaItems.length === 0}
            <div class="bg-glass2 border border-border rounded-xl p-4">
              <div class="text-[13px] font-semibold">Nothing scheduled</div>
              <div class="text-[12px] text-slate-400 mt-1">
                {#if agendaView === 'day'}
                  No workouts planned for this day.
                {:else}
                  No workouts planned for this week.
                {/if}
              </div>
            </div>
          {:else}
            <div class="flex flex-col gap-3">
              {#each agendaItems as w (w.id)}
                {@const tss = Number(w?.tss)}
                <button
                  type="button"
                  class="bg-glass2 border border-border rounded-xl p-4 text-left hover:border-blue transition-colors cursor-pointer"
                  onclick={() => openWorkout(w)}
                >
                  <div class="flex items-start justify-between gap-3">
                    <div class="flex items-center gap-2 min-w-0">
                      <div class="w-8 h-8 rounded-xl bg-glass border border-border/60 flex items-center justify-center shrink-0">
                        <span class="text-[14px]">{sportIcon(w)}</span>
                      </div>
                      <div class="min-w-0">
                        <div class="text-[14px] font-semibold truncate">{w.title ?? w.type ?? 'Session'}</div>
                        <div class="text-[11px] text-slate-400 font-mono">
                          {agendaView === 'week' ? format(w.date, 'EEE • ') : ''}{w.duration ?? '—'}
                        </div>
                      </div>
                    </div>

                    <div class="text-right shrink-0">
                      <div class={['text-[12px] font-mono', Number.isFinite(tss) ? 'text-text0' : 'text-slate-400'].join(' ')}>
                        {Number.isFinite(tss) ? `${tss} TSS` : '-- TSS'}
                      </div>
                      <div class="text-[10px] text-slate-400 mt-0.5">
                        <span class={['inline-block w-2 h-2 rounded-full mr-1.5 align-middle', indicatorClass(w)].join(' ')}></span>
                        {w.type ?? 'Workout'}
                      </div>
                    </div>
                  </div>
                </button>
              {/each}
            </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</div>

{#if selectedWorkout}
  <!-- Modal / Drawer (simple centered overlay) -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center p-4"
    role="dialog"
    aria-modal="true"
    aria-label="Session details"
  >
    <button
      type="button"
      class="absolute inset-0 bg-black/60"
      aria-label="Close"
      onclick={closeWorkout}
    ></button>

    <div class="relative w-full max-w-[720px] bg-glass border border-border rounded-2xl p-5 shadow-[0_20px_60px_rgba(0,0,0,0.6)]">
      <div class="flex items-start justify-between gap-4 mb-4">
        <div class="min-w-0">
          <div class="text-[12px] text-slate-400 font-mono">
            {format(selectedWorkout.date, 'EEE, MMM d')} • {selectedWorkout.duration ?? '—'}
          </div>
          <div class="text-[18px] font-semibold truncate">{selectedWorkout.title ?? selectedWorkout.type ?? 'Session'}</div>
        </div>

        <button
          type="button"
          class="w-10 h-10 rounded-xl bg-glass2 border border-border/60 hover:bg-glass transition-colors"
          aria-label="Close modal"
          onclick={closeWorkout}
        >
          ✕
        </button>
      </div>

      <div class="grid gap-4">
        <div class="bg-glass2 border border-border rounded-xl p-4">
          <div class="text-[12px] text-slate-400 font-mono mb-1">AI context</div>
          <div class="text-[13px] text-text0 leading-relaxed">
            {selectedWorkout.note ?? selectedWorkout.goal ?? selectedWorkout.context ?? 'No additional context provided for this session yet.'}
          </div>
        </div>

        <div class="bg-glass2 border border-border rounded-xl p-4">
          <div class="text-[12px] text-slate-400 font-mono mb-2">Structure</div>
          <ol class="list-decimal pl-5 grid gap-2">
            {#each stepsFor(selectedWorkout) as step, i (i)}
              <li class="text-[13px] text-text0">
                {#if typeof step === 'string'}
                  <span>{step}</span>
                {:else}
                  <div class="grid gap-0.5">
                    <div class="font-semibold">{step.title ?? 'Step'}</div>
                    <div class="text-[12px] text-slate-400">
                      {#if step.duration}
                        <span class="font-mono text-text0">{step.duration}</span>
                      {/if}
                      {#if step.target}
                        <span class="font-mono text-text0">{step.target}</span>
                      {/if}
                      {#if step.note}
                        <span>{step.note}</span>
                      {/if}
                    </div>
                  </div>
                {/if}
              </li>
            {/each}
          </ol>
          {#if !(selectedWorkout.blocks?.length || selectedWorkout.structure?.length)}
            <div class="text-[11px] text-slate-400 mt-3">
              Scaffolded outline (replace with real blocks when available).
            </div>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}
