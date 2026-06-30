<script lang="ts">
  import type { Action } from 'svelte/action';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { confirm } from '$lib/confirm';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { trainingStore } from '$lib/stores/trainingStore.svelte';
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
  import {
    extractFirstGfmPipeTable,
    renderCoachMarkdownToSafeHtml
  } from '$lib/coachMarkdown';
  import type { Workout } from '$lib/types/training';

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
  };

  const dow = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  let agendaView = $state<AgendaView>('day');
  let selectedWorkout = $state<PlannedWorkout | null>(null);
  let removingPlanWorkout = $state(false);

  /** Real `training_plans.id` when this row comes from `/v1/training-plans` (`ai:<uuid>` display ids). */
  function backendTrainingPlanId(w: PlannedWorkout | null): string | null {
    const id = w?.id ?? '';
    if (!id.startsWith('ai:')) return null;
    return id.slice(3);
  }

  // Current month shown in the calendar (can be navigated independently).
  let viewMonth = $state<Date>(startOfMonth(new Date()));

  function parseIsoLocal(value: string): Date {
    // Local noon avoids timezone/DST edges shifting the date.
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!m) return new Date(NaN);
    const year = Number(m[1]);
    const monthIndex = Number(m[2]) - 1;
    const day = Number(m[3]);
    return new Date(year, monthIndex, day, 12, 0, 0, 0);
  }

  const selectedDate = $derived.by(() =>
    parseIsoLocal(trainingStore.selectedDate || format(new Date(), 'yyyy-MM-dd'))
  );

  const plannedWorkouts = $derived.by<PlannedWorkout[]>(() => {
    const intervalTarget = (i: Workout['structure'][number]): string | undefined => {
      const parts: string[] = [];
      if (typeof i.target_hr_zone === 'number') parts.push(`HR Z${i.target_hr_zone}`);
      if (typeof i.target_power_percent_ftp === 'number') parts.push(`${i.target_power_percent_ftp}% FTP`);
      return parts.length ? parts.join(' • ') : undefined;
    };

    const byId = Array.from(new Map(trainingStore.workouts.map((w) => [w.id, w])).values());

    return byId
      .map((w) => ({
        id: `ai:${w.id}`,
        isoDate: w.date,
        date: parseIsoLocal(w.date),
        title: w.title,
        type: w.sport,
        duration: w.duration_minutes != null ? `${w.duration_minutes} min` : undefined,
        tss: w.projected_tss,
        context: w.description,
        structure: (w.structure ?? []).map((i) => ({
          title: i.name,
          duration: i.duration_minutes != null ? `${i.duration_minutes} min` : undefined,
          target: intervalTarget(i),
          note: i.description
        }))
      }))
      .sort((a, b) => a.date.getTime() - b.date.getTime());
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

  const selectedIso = $derived(trainingStore.selectedDate);
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
    if (t === 'mobility' || t.includes('mobil') || t.includes('yoga') || t.includes('stretch'))
      return '🧘';
    return '⭐';
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

  const viewMonthRange = $derived.by(() => ({
    startIso: format(startOfMonth(viewMonth), 'yyyy-MM-dd'),
    endIso: format(endOfMonth(viewMonth), 'yyyy-MM-dd')
  }));

  $effect(() => {
    if (authStore.tier !== 'premium') return;
    trainingStore.fetchWorkouts(viewMonthRange.startIso, viewMonthRange.endIso);
  });

  function toggleView(v: AgendaView) {
    agendaView = v;
  }

  function selectDate(d: Date) {
    trainingStore.selectedDate = format(d, 'yyyy-MM-dd');
    if (d.getFullYear() !== viewMonth.getFullYear() || d.getMonth() !== viewMonth.getMonth()) {
      viewMonth = startOfMonth(d);
    }
  }

  function jumpToToday() {
    selectDate(new Date());
  }

  function openWorkout(w: PlannedWorkout) {
    selectedWorkout = w;
  }

  function closeWorkout() {
    selectedWorkout = null;
    removingPlanWorkout = false;
  }

  async function removeSelectedTrainingPlan() {
    const planId = backendTrainingPlanId(selectedWorkout);
    if (!planId) return;
    const ok = await confirm({
      title: 'Remove from plan?',
      message:
        'This session will be removed from your calendar. You can add or schedule workouts again anytime.',
      confirmText: 'Remove',
      cancelText: 'Cancel',
      confirmTone: 'danger'
    });
    if (!ok) return;
    removingPlanWorkout = true;
    try {
      const deleted = await trainingStore.deleteTrainingPlan(
        planId,
        viewMonthRange.startIso,
        viewMonthRange.endIso
      );
      if (deleted) closeWorkout();
    } finally {
      removingPlanWorkout = false;
    }
  }

  /** Copy header labels onto tbody cells for the stacked mobile layout (`::before { content: attr(data-label) }`). */
  const enhancePrescriptionTable: Action<HTMLElement> = (node) => {
    const run = () => {
      const table = node.querySelector('table');
      if (!table) return;
      const headers = [...table.querySelectorAll('thead th')].map(
        (th) => th.textContent?.trim() ?? ''
      );
      for (const tr of table.querySelectorAll('tbody tr')) {
        tr.querySelectorAll('td').forEach((td, i) => {
          td.setAttribute('data-label', headers[i] ?? `Column ${i + 1}`);
        });
      }
    };
    queueMicrotask(run);
    return { update: run };
  };

  const SESSION_CONTEXT_FALLBACK = 'No additional context provided for this session yet.';

  /**
   * Desktop (sm+): fixed table + column weights. Mobile: thead hidden, one card per tbody row,
   * each cell is label-above-value (needs `enhancePrescriptionTable` for `data-label`).
   */
  const prescriptionProseClass =
    [
      'prose prose-invert max-w-none prose-table:my-0 prose-th:text-blue prose-th:font-mono',
      'text-[13px] leading-relaxed text-text0 [&_table]:my-0 [&_table]:w-full [&_table]:border-collapse',
      /* Mobile: stack — no squeezed fixed columns */
      'max-sm:[&_table]:block max-sm:[&_thead]:hidden max-sm:[&_tbody]:block max-sm:[&_table]:border-0',
      'max-sm:[&_tbody_tr]:block max-sm:[&_tbody_tr]:mb-3 max-sm:[&_tbody_tr]:last:mb-0 max-sm:[&_tbody_tr]:rounded-lg max-sm:[&_tbody_tr]:border max-sm:[&_tbody_tr]:border-border/45 max-sm:[&_tbody_tr]:bg-glass max-sm:[&_tbody_tr]:p-3',
      'max-sm:[&_tbody_td]:flex max-sm:[&_tbody_td]:min-w-0 max-sm:[&_tbody_td]:flex-col max-sm:[&_tbody_td]:items-stretch max-sm:[&_tbody_td]:gap-1 max-sm:[&_tbody_td]:border-0 max-sm:[&_tbody_td]:py-2.5 max-sm:[&_tbody_td]:px-0 max-sm:[&_tbody_td]:first:pt-0 max-sm:[&_tbody_td]:last:pb-0',
      'max-sm:[&_tbody_td]:[word-break:normal] max-sm:[&_tbody_td]:before:font-mono max-sm:[&_tbody_td]:before:text-[11px] max-sm:[&_tbody_td]:before:uppercase max-sm:[&_tbody_td]:before:tracking-wide max-sm:[&_tbody_td]:before:text-text1 max-sm:[&_tbody_td]:before:leading-snug max-sm:[&_tbody_td]:before:content-[attr(data-label)] max-sm:[&_tbody_td]:before:text-left',
      'max-sm:[&_tbody_td]:not(:last-child):border-b max-sm:[&_tbody_td]:not(:last-child):border-border/30',
      /* Desktop table */
      'sm:[&_table]:table-fixed sm:[&_table]:min-w-0',
      'sm:[&_th]:align-top sm:[&_td]:align-top sm:[&_th]:[word-break:normal] sm:[&_td]:[word-break:normal]',
      'sm:[&_th:nth-child(1)]:w-[16%] sm:[&_th:nth-child(2)]:w-[14%] sm:[&_th:nth-child(3)]:w-[22%] sm:[&_th:nth-child(4)]:min-w-0 sm:[&_th:nth-child(4)]:w-[48%]',
      'sm:[&_table]:rounded-none sm:[&_table]:border sm:[&_table]:border-border/50',
      'sm:[&_thead]:border-b sm:[&_thead]:border-border/50 sm:[&_thead]:bg-blue/10',
      'sm:[&_thead_th]:border-border/40 sm:[&_thead_th]:px-3 sm:[&_thead_th]:py-2 sm:[&_thead_th]:text-left',
      'sm:[&_tbody_td]:border-t sm:[&_tbody_td]:border-border/35 sm:[&_tbody_td]:px-3 sm:[&_tbody_td]:py-2',
      'sm:[&_tbody_tr:nth-child(even)]:bg-glass',
      'sm:[&_th:nth-child(2)]:text-center sm:[&_td:nth-child(2)]:text-center sm:[&_th:nth-child(2)]:font-mono sm:[&_td:nth-child(2)]:font-mono',
      'sm:[&_th:nth-child(3)]:text-center sm:[&_td:nth-child(3)]:text-center sm:[&_th:nth-child(3)]:font-mono sm:[&_td:nth-child(3)]:font-mono'
    ].join(' ');

  const coachNotesMarkdownProseClass =
    'prose prose-invert max-w-none text-[14px] leading-relaxed text-text0 prose-p:my-2 prose-ul:my-2';

  const sessionDetailContext = $derived.by(() => {
    const w = selectedWorkout;
    if (!w) {
      return {
        coachNotes: '',
        prescriptionMarkdown: '',
        hasPrescriptionTable: false,
        contextIsMarkdownTable: false
      };
    }
    const rawContext = w.note ?? w.goal ?? w.context ?? SESSION_CONTEXT_FALLBACK;
    const { tableMarkdown, remainder } = extractFirstGfmPipeTable(rawContext);
    const hasPrescriptionTable = Boolean(tableMarkdown?.length);
    return {
      coachNotes: remainder,
      prescriptionMarkdown: tableMarkdown ?? '',
      hasPrescriptionTable,
      contextIsMarkdownTable: hasPrescriptionTable
    };
  });

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
  {:else}
    <div class="md:grid md:grid-cols-12 md:gap-6 flex flex-col gap-4">
      <!-- Calendar (desktop col-span-7) -->
      <div class="md:col-span-7">
        <div class="bg-glass border border-border rounded-2xl p-4">
          <div class="flex items-center justify-between mb-3">
            <div>
              <div class="text-[12px] text-text1 font-mono">Month</div>
              <div class="text-[16px] font-semibold">{format(viewMonth, 'MMMM yyyy')}</div>
            </div>
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="h-9 px-2.5 rounded-xl bg-glass2 border border-border/50 hover:bg-glass transition-colors text-[12px] font-mono text-text1 whitespace-nowrap"
                aria-label="Jump to today"
                onclick={jumpToToday}
              >
                Today
              </button>
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
              <div class="text-[10px] text-text1 font-mono text-center py-1">{d}</div>
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
                  'h-14 sm:h-16 md:h-[64px] rounded-2xl border transition-colors relative overflow-hidden flex flex-col items-center justify-start pt-1.5',
                  inMonth ? 'border-border bg-glass2/30 hover:bg-glass2' : 'border-border/40 bg-transparent opacity-60 hover:opacity-80',
                  isSelected ? 'border-blue bg-[linear-gradient(135deg,rgba(70,33,255,0.18),transparent)]' : ''
                ].join(' ')}
                aria-label={format(d, 'yyyy-MM-dd')}
                onclick={() => selectDate(d)}
              >
                <div class={['text-sm font-medium', isSelected ? 'text-text0' : 'text-text1'].join(' ')}>
                  {format(d, 'd')}
                </div>

                {#if items.length > 0}
                  <div class="mt-0.5 flex items-center gap-1">
                    {#each items.slice(0, 3) as w (w.id)}
                      <span class={['w-1.5 h-1.5 rounded-full', indicatorClass(w)].join(' ')}></span>
                    {/each}
                    {#if items.length > 3}
                      <span class="text-[9px] sm:text-[10px] leading-none text-text1 font-mono">+{items.length - 3}</span>
                    {/if}
                  </div>

                  {@const tss = Number(items[0]?.tss)}
                  <div class="mt-auto pb-1 text-[9px] sm:text-[10px] leading-none text-text2 font-mono">
                    <span class="hidden sm:inline">{Number.isFinite(tss) ? `${tss} TSS` : ''}</span>
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
              <div class="text-[12px] text-text1 font-mono">Agenda</div>
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
                  agendaView === 'day' ? 'bg-blue text-text0' : 'text-text0 hover:bg-glass'
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
                  agendaView === 'week' ? 'bg-blue text-text0' : 'text-text0 hover:bg-glass'
                ].join(' ')}
                role="tab"
                aria-selected={agendaView === 'week'}
                onclick={() => toggleView('week')}
              >
                Week
              </button>
            </div>
          </div>

          {#if trainingStore.isLoading}
            <div class="bg-glass2 border border-border rounded-xl p-4">
              <div class="animate-pulse grid gap-3">
                <div class="h-4 w-40 rounded bg-border/50"></div>
                <div class="h-3 w-full rounded bg-border/40"></div>
                <div class="h-3 w-11/12 rounded bg-border/40"></div>
                <div class="h-3 w-10/12 rounded bg-border/40"></div>
              </div>
            </div>
          {:else if agendaItems.length === 0}
            <div class="bg-glass2 border border-border rounded-xl p-4">
              <div class="text-[13px] font-semibold">Nothing scheduled</div>
              <div class="text-[12px] text-text1 mt-1">
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
                        <div class="text-[11px] text-text1 font-mono">
                          {agendaView === 'week' ? format(w.date, 'EEE • ') : ''}{w.duration ?? '—'}
                        </div>
                      </div>
                    </div>

                    <div class="text-right shrink-0">
                      <div class={['text-[12px] font-mono', Number.isFinite(tss) ? 'text-text0' : 'text-text1'].join(' ')}>
                        {Number.isFinite(tss) ? `${tss} TSS` : '-- TSS'}
                      </div>
                      <div class="text-[10px] text-text1 mt-0.5">
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
    class="fixed inset-0 z-50 flex items-start sm:items-center justify-center p-4 pt-16 sm:pt-4"
    role="dialog"
    aria-modal="true"
    aria-label="Session details"
  >
    <button
      type="button"
      class="absolute inset-0 bg-bg0/80 backdrop-blur-sm"
      aria-label="Close"
      onclick={closeWorkout}
    ></button>

    <div
      class="relative w-full min-w-0 max-w-[720px] max-h-[85vh] overflow-y-auto bg-bg1/95 border border-border rounded-2xl p-4 sm:p-5 shadow-2xl"
    >
      <div class="flex items-start justify-between gap-4 mb-7">
        <div class="min-w-0">
          <div class="text-[12px] text-text1 font-mono">
            {format(selectedWorkout.date, 'EEE, MMM d')} • {selectedWorkout.duration ?? '—'}
          </div>
          <div class="text-[18px] font-semibold truncate">{selectedWorkout.title ?? selectedWorkout.type ?? 'Session'}</div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          {#if backendTrainingPlanId(selectedWorkout)}
            <button
              type="button"
              class="rounded-xl border px-3 py-2 text-[13px] font-medium transition-colors border-red/55 text-red hover:bg-red-dim disabled:opacity-50 disabled:pointer-events-none"
              disabled={removingPlanWorkout}
              onclick={removeSelectedTrainingPlan}
            >
              {removingPlanWorkout ? 'Removing…' : 'Remove from plan'}
            </button>
          {/if}
          <button
            type="button"
            class="w-10 h-10 rounded-xl bg-glass2 border border-border/60 hover:bg-glass transition-colors"
            aria-label="Close modal"
            onclick={closeWorkout}
          >
            ✕
          </button>
        </div>
      </div>

      <div class="grid gap-6">
        {#if sessionDetailContext.hasPrescriptionTable}
          <div class="space-y-3">
            <h3 class="text-[12px] text-text1 font-mono uppercase tracking-widest">Prescription</h3>
            <div class="min-w-0 w-full">
              {#key sessionDetailContext.prescriptionMarkdown}
                <div
                  use:enhancePrescriptionTable
                  class="rounded-xl overflow-hidden bg-glass2 border border-border/50 px-2 py-2 sm:px-4 sm:py-3 {prescriptionProseClass}"
                >
                  {@html renderCoachMarkdownToSafeHtml(sessionDetailContext.prescriptionMarkdown)}
                </div>
              {/key}
            </div>
          </div>
          {#if sessionDetailContext.coachNotes.length > 0}
            <div class="bg-glass2 border border-border rounded-xl p-4">
              <h3 class="text-[12px] text-text1 font-mono mb-1">Coach's Notes</h3>
              <div class={coachNotesMarkdownProseClass}>
                {@html renderCoachMarkdownToSafeHtml(sessionDetailContext.coachNotes)}
              </div>
            </div>
          {/if}
        {:else}
          <div class="bg-glass2 border border-border rounded-xl p-4">
            <h3 class="text-[12px] text-text1 font-mono mb-1">Coach's Notes</h3>
            <p class="text-[14px] leading-relaxed text-text0">{sessionDetailContext.coachNotes}</p>
          </div>
        {/if}

        {#if !sessionDetailContext.contextIsMarkdownTable && stepsFor(selectedWorkout).length > 0}
          <div class="space-y-3">
            <h3 class="text-[12px] text-text1 font-mono uppercase tracking-widest">Technical Blocks</h3>
            <div class="bg-glass2 border border-border rounded-xl p-4">
              <ol class="list-decimal pl-5 grid gap-2">
                {#each stepsFor(selectedWorkout) as step, i (i)}
                  <li class="text-[13px] text-text0">
                    {#if typeof step === 'string'}
                      <span>{step}</span>
                    {:else}
                      <div class="grid gap-0.5">
                        <div class="font-semibold">{step.title ?? 'Step'}</div>
                        <div class="text-[12px] text-text1">
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
                <div class="text-[11px] text-text1 mt-3">
                  Scaffolded outline (replace with real blocks when available).
                </div>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}
