<script lang="ts">
  import type { Action } from 'svelte/action';
  import EmptyStateCard from '$lib/components/ui/EmptyStateCard.svelte';
  import { api } from '$lib/api';
  import { confirm } from '$lib/confirm';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { trainingStore } from '$lib/stores/trainingStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import MonthNavigator from '$lib/components/MonthNavigator.svelte';
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
  import { modalDialog } from '$lib/actions/modalDialog';

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
    /** Raw training_plans.structure intervals (numeric targets) for the session sheet. */
    intervals?: Workout['structure'];
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

    const workouts = trainingStore.workouts ?? [];
    const byId = Array.from(new Map(workouts.map((w) => [w.id, w])).values());

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
        intervals: w.structure ?? [],
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
    startIso: format(gridStart, 'yyyy-MM-dd'),
    endIso: format(gridEnd, 'yyyy-MM-dd')
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

  function onMonthChange(key: string) {
    const [y, m] = key.split('-').map(Number);
    if (key === format(new Date(), 'yyyy-MM')) {
      selectDate(new Date());
      return;
    }
    viewMonth = new Date(y, m - 1, 1);
    // Keep the selected day inside the month being shown (the day panel under the
    // calendar showed "MON 2 NOV · Nothing planned" beneath January).
    trainingStore.selectedDate = format(viewMonth, 'yyyy-MM-dd');
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

  // --- Design view (Week / Month / Session sheet) ---
  let planView = $state<'week' | 'month'>('week');
  const todayIso = format(new Date(), 'yyyy-MM-dd');
  // Week view is always the current week.
  const weekStart = startOfWeek(new Date(), { weekStartsOn: 1 });
  $effect(() => {
    if (planView !== 'week') return;
    const iso = trainingStore.selectedDate;
    const startIso = format(weekStart, 'yyyy-MM-dd');
    const endIso = format(addDays(weekStart, 6), 'yyyy-MM-dd');
    if (!iso || iso < startIso || iso > endIso) selectDate(new Date());
    // The store only holds the fetched month's grid. After browsing another month in
    // Month view, come back to a month whose grid contains this week, or the week
    // shows "Nothing planned" every day. (Either month a week touches covers it.)
    const weekMonths = [format(weekStart, 'yyyy-MM'), format(addDays(weekStart, 6), 'yyyy-MM')];
    if (!weekMonths.includes(format(viewMonth, 'yyyy-MM'))) viewMonth = startOfMonth(new Date());
  });
  const weekDays = $derived(Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)));
  const dayItems = $derived(workoutsByIso[selectedIso] ?? []);
  const laterThisWeek = $derived.by(() => {
    const out: PlannedWorkout[] = [];
    for (const d of weekDays) {
      const iso = format(d, 'yyyy-MM-dd');
      if (iso > selectedIso) out.push(...(workoutsByIso[iso] ?? []));
    }
    return out;
  });

  function durationMinutes(w: RawPlanItem): number {
    const m = /(\d+(?:\.\d+)?)/.exec(String(w.duration ?? ''));
    return m ? Math.round(Number(m[1])) : 0;
  }

  /** Session category → colour/label, matching the plan legend (VO2, threshold, endurance, recovery, strength). */
  function classify(w: RawPlanItem): { color: string; label: string } {
    const key = `${w.intensity ?? ''} ${w.type ?? ''} ${w.title ?? ''}`.toLowerCase();
    if (/\b(rest|off)\b/.test(key)) return { color: 'transparent', label: 'Rest' };
    if (/vo2|anaerobic|sprint|max/.test(key)) return { color: 'var(--zone-5)', label: 'Key session' };
    if (/threshold|sweet ?spot|tempo|interval|ftp|race/.test(key)) return { color: 'var(--zone-4)', label: 'Key session' };
    if (/strength|gym|lift|mobility|yoga|stretch/.test(key)) return { color: 'var(--text2)', label: 'Strength' };
    if (/long|endurance|aerobic|z2/.test(key)) return { color: 'var(--zone-2)', label: 'Endurance' };
    if (/recovery|easy|spin|z1|flush/.test(key)) return { color: 'var(--zone-1)', label: 'Recovery' };
    const t = (w.type ?? '').toLowerCase();
    if (t.includes('run')) return { color: 'var(--zone-1)', label: 'Run' };
    if (t.includes('bike') || t.includes('ride')) return { color: 'var(--zone-2)', label: 'Ride' };
    return { color: 'var(--blue)', label: w.type ? String(w.type) : 'Session' };
  }
  const sessionColor = (w: RawPlanItem) => classify(w).color;
  const sessionLabel = (w: RawPlanItem) => classify(w).label;
  const SESSION_LEGEND = [
    { label: 'VO2', color: 'var(--zone-5)' },
    { label: 'Threshold', color: 'var(--zone-4)' },
    { label: 'Endurance', color: 'var(--zone-2)' },
    { label: 'Recovery', color: 'var(--zone-1)' },
    { label: 'Strength', color: 'var(--text2)' }
  ];

  /** Intensity zone (1-5) from a step target like "92% FTP" or "HR Z3". */
  function targetZone(target?: string): number {
    const t = target ?? '';
    const hr = /Z\s?(\d)/i.exec(t);
    if (hr) return Math.min(5, Math.max(1, Number(hr[1])));
    const ftp = /(\d+)\s*%\s*FTP/i.exec(t);
    if (ftp) {
      const p = Number(ftp[1]);
      return p < 56 ? 1 : p < 76 ? 2 : p < 91 ? 3 : p < 106 ? 4 : 5;
    }
    return 0;
  }
  type DesignStep = { title: string; duration?: string; target?: string; note?: string; minutes: number; hard: boolean; color: string };
  function structuredSteps(w: PlannedWorkout): DesignStep[] {
    const arr = (w.blocks ?? w.structure) as PlannedWorkout['blocks'] | undefined;
    if (!Array.isArray(arr)) return [];
    return arr.map((step) => {
      if (typeof step === 'string') return { title: step, minutes: 1, hard: false, color: 'var(--bg3)' };
      const z = targetZone(step.target);
      const minutes = (() => { const m = /(\d+)/.exec(step.duration ?? ''); return m ? Number(m[1]) : 1; })();
      return {
        title: step.title ?? 'Step',
        duration: step.duration?.replace(/\s*min$/, '′'),
        target: step.target,
        note: step.note,
        minutes,
        hard: z >= 4,
        color: z > 0 ? `var(--zone-${z})` : 'var(--bg3)'
      };
    });
  }
  /** One-line summary from the coach's markdown context. */
  function plainText(md?: string): string {
    return String(md ?? '')
      .split('\n')
      .filter((l) => !l.trim().startsWith('|'))
      .join(' ')
      .replace(/[#*_>`]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 240);
  }

  const periodSummary = $derived.by(() => {
    const items =
      planView === 'week'
        ? weekDays.flatMap((d) => workoutsByIso[format(d, 'yyyy-MM-dd')] ?? [])
        : plannedWorkouts.filter((w) => isSameMonth(w.date, viewMonth));
    const mins = items.reduce((a, w) => a + durationMinutes(w), 0);
    const time = `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`;
    return `${items.length} session${items.length === 1 ? '' : 's'} · ${time}`;
  });

  // --- No plan at all (design: empty states, page 7) ---
  /** Anything planned from today over the next 8 weeks (null until checked). */
  let hasUpcoming = $state<boolean | null>(null);
  $effect(() => {
    if (authStore.tier !== 'premium') return;
    void trainingStore.workouts; // re-check after the store reloads (e.g. a plan was just built)
    let cancelled = false;
    const to = format(addDays(new Date(), 56), 'yyyy-MM-dd');
    api.getWorkouts(todayIso, to).then(
      (rows) => {
        if (!cancelled) hasUpcoming = rows.length > 0;
      },
      () => {
        if (!cancelled) hasUpcoming = true; // unknown: keep the normal calendar
      }
    );
    return () => {
      cancelled = true;
    };
  });
  /** Only for athletes with no plan at all, never for an ordinary empty week. */
  const noPlanYet = $derived(
    !trainingStore.isLoading && plannedWorkouts.length === 0 && hasUpcoming === false
  );

  const PLAN_GOALS = [
    { title: 'Raise my FTP', sub: '8–12 week build', prompt: 'Build me an 8–12 week plan to raise my FTP.' },
    { title: 'Ride a century', sub: 'Event date', prompt: 'Build me a plan to ride a century. My event date is ' },
    { title: 'Triathlon', sub: 'Swim · bike · run', prompt: 'Build me a triathlon plan covering swim, bike and run.' },
    { title: 'Stay fit', sub: 'Flexible weeks', prompt: 'Build me a flexible plan to stay fit around a busy schedule.' }
  ];
  function askCoach(prompt: string) {
    goto(`/chat?prompt=${encodeURIComponent(prompt)}`);
  }

  $effect(() => {
    if (noPlanYet) {
      resetPageHeader();
      return resetPageHeader;
    }
    pageHeader.eyebrow = periodSummary;
    pageHeader.segments = [
      { value: 'week', label: 'Week' },
      { value: 'month', label: 'Month' }
    ];
    pageHeader.segment = planView;
    pageHeader.onSegment = (v) => (planView = v as 'week' | 'month');
    return resetPageHeader;
  });

  // --- Session sheet: interactive profile + per-step detail ---
  let stepIdx = $state(0);
  let sheetExpanded = $state(false);
  let sheetMode = $state<'none' | 'move' | 'swap'>('none');
  let moveDate = $state('');
  let savingPlan = $state(false);
  let planActionError = $state<string | null>(null);
  $effect(() => {
    void selectedWorkout?.id;
    stepIdx = 0;
    sheetExpanded = false;
    sheetMode = 'none';
    planActionError = null;
  });

  // Deep link from Today: /plan?session=<id> selects that day and opens the session.
  let openedFromLink: string | null = null;
  $effect(() => {
    const wanted = $page.url.searchParams.get('session');
    if (!wanted || wanted === openedFromLink) return;
    const match = plannedWorkouts.find((w) => backendTrainingPlanId(w) === wanted);
    if (!match) return;
    openedFromLink = wanted;
    selectDate(match.date);
    openWorkout(match);
    goto('/plan', { replaceState: true, keepFocus: true, noScroll: true });
  });

  /** Other sessions in the same Monday–Sunday week, for Swap. */
  function swapCandidates(w: PlannedWorkout): PlannedWorkout[] {
    const start = startOfWeek(w.date, { weekStartsOn: 1 });
    const out: PlannedWorkout[] = [];
    for (let i = 0; i < 7; i++) {
      const iso = format(addDays(start, i), 'yyyy-MM-dd');
      for (const o of workoutsByIso[iso] ?? []) if (o.id !== w.id && backendTrainingPlanId(o)) out.push(o);
    }
    return out;
  }

  async function applySchedule(changes: { id: string; date: string }[], focusIso: string) {
    savingPlan = true;
    planActionError = null;
    try {
      const ok = await trainingStore.rescheduleWorkouts(changes, viewMonthRange.startIso, viewMonthRange.endIso);
      if (!ok) {
        planActionError = "Couldn't update the plan. Try again.";
        return;
      }
      closeWorkout();
      selectDate(parseIsoLocal(focusIso));
    } finally {
      savingPlan = false;
    }
  }

  function moveSession(w: PlannedWorkout, iso: string) {
    const id = backendTrainingPlanId(w);
    if (!id || !iso || iso === w.isoDate) return;
    return applySchedule([{ id, date: iso }], iso);
  }

  function swapSessions(a: PlannedWorkout, b: PlannedWorkout) {
    const idA = backendTrainingPlanId(a);
    const idB = backendTrainingPlanId(b);
    if (!idA || !idB) return;
    return applySchedule(
      [
        { id: idA, date: b.isoDate },
        { id: idB, date: a.isoDate }
      ],
      b.isoDate
    );
  }
  const planFtp = $derived(Number(athleteStore.profile?.ftp_watts) || 0);
  const ZONE_NAMES: Record<number, string> = { 1: 'Recovery', 2: 'Endurance', 3: 'Tempo', 4: 'Threshold', 5: 'VO2max' };
  const RPE: Record<number, string> = { 1: '1–2 / 10', 2: '3–4 / 10', 3: '5–6 / 10', 4: '7–8 / 10', 5: '9–10 / 10' };
  const PROFILE_H = 96;
  const PROFILE_TOP = 14; // the dashed 100% FTP line

  function hrRange(zone: number): string | undefined {
    const z = (athleteStore.profile?.hr_zones?.zones ?? []).find((x: { zone: number }) => x.zone === zone);
    if (!z) return undefined;
    if (z.max >= 500) return `≥ ${z.min} bpm`;
    if (z.min <= 0) return `< ${z.max + 1} bpm`;
    return `${z.min}–${z.max} bpm`;
  }
  const mmss = (mins: number) => `${String(Math.floor(mins)).padStart(2, '0')}:00`;

  type SessionStep = {
    title: string;
    note?: string;
    minutes: number;
    zone: number;
    color: string;
    watts?: string;
    pctLabel?: string;
    target?: string;
    hr?: string;
    rpe?: string;
    sub: string;
    start: string;
    window: string;
    barHeight: number;
    isRest: boolean;
    restHr?: string;
  };

  function sessionSteps(w: PlannedWorkout): SessionStep[] {
    const raw = (w.intervals ?? []).filter(Boolean);
    let t = 0;
    const base = raw.map((i) => {
      const minutes = Math.max(0, Number(i.duration_minutes) || 0);
      const pct = typeof i.target_power_percent_ftp === 'number' ? i.target_power_percent_ftp : null;
      const hrZone = typeof i.target_hr_zone === 'number' ? i.target_hr_zone : null;
      const zone = pct != null ? targetZone(`${pct}% FTP`) : hrZone ?? 0;
      const start = t;
      t += minutes;
      // Prescribed targets are a single % of FTP; show the usual ±2.5% working band.
      const watts = pct != null && planFtp
        ? `${Math.round((planFtp * (pct - 2.5)) / 100)}–${Math.round((planFtp * (pct + 2.5)) / 100)} W`
        : undefined;
      return {
        title: i.name || 'Step',
        note: i.description,
        minutes,
        zone,
        color: zone > 0 ? `var(--zone-${zone})` : 'var(--text2)',
        watts,
        pctLabel: pct != null ? `${pct}% FTP` : undefined,
        target: hrZone != null ? `Z${hrZone} HR` : undefined,
        hr: zone > 0 ? hrRange(zone) : undefined,
        rpe: zone > 0 ? RPE[zone] : undefined,
        start: mmss(start),
        window: `${mmss(start)}–${mmss(start + minutes)}`,
        barHeight: pct != null
          ? Math.max(8, Math.round((Math.min(pct, 130) / 100) * (PROFILE_H - PROFILE_TOP)))
          : zone > 0 ? 14 + zone * 12 : 20,
        sub: '',
        isRest: false
      } as SessionStep;
    });
    return base.map((s, i) => {
      const between = s.zone === 1 && (base[i - 1]?.zone ?? 0) >= 3 && (base[i + 1]?.zone ?? 0) >= 3;
      const sub = between
        ? `Easy spin${s.hr ? ` · HR ${s.hr}` : ''}`
        : [s.zone > 0 ? `Z${s.zone}` : null, s.pctLabel ?? s.target ?? null].filter(Boolean).join(' · ') || (s.note ?? '');
      return { ...s, sub, isRest: between, restHr: between ? hrRange(1) : undefined };
    });
  }

  function profileTicks(total: number): number[] {
    if (total <= 0) return [0];
    const step = total / 4;
    // Rounded to 5 min, so short sessions repeat values (15 min → 0,5,10,10,15); the
    // ticks are an each-key, so keep them unique.
    return [...new Set([0, 1, 2, 3].map((i) => Math.round((i * step) / 5) * 5).concat(total))];
  }
</script>

<div class="flex flex-col gap-4">
  {#if authStore.tier !== 'premium'}
    <EmptyStateCard icon="calendar-plus" tone="blue" eyebrow="Premium" title="Training plans are a premium feature" message="Your coach builds and adjusts a week-by-week plan around your goal and recovery. Upgrade to premium to use it." />
  {:else if noPlanYet}
    <EmptyStateCard
      icon="calendar-plus"
      tone="neutral"
      eyebrow="Nothing yet"
      title="No plan yet"
      message="Pick a goal and your coach builds your first four weeks around the days you can train. You can change anything after."
      actionLabel="Build my plan"
      onAction={() => askCoach("Build me a training plan. Here's my goal: ")}
      secondaryLabel="Add a single workout"
      onSecondary={() => askCoach('Add a single workout to my plan: ')}
    />
    <p class="font-mono text-[12px] tracking-[0.2em] text-text2 uppercase mt-2 mb-0 px-1">Or start from a goal</p>
    <div class="grid grid-cols-2 gap-3">
      {#each PLAN_GOALS as g (g.title)}
        <button
          type="button"
          class="text-left bg-bg2 border border-border rounded-[20px] px-5 py-4 cursor-pointer hover:border-text2/60 transition-colors"
          onclick={() => askCoach(g.prompt)}
        >
          <span class="block text-[17px] font-medium text-text0">{g.title}</span>
          <span class="block text-[14px] text-text2 mt-0.5">{g.sub}</span>
        </button>
      {/each}
    </div>
  {:else if planView === 'week'}
    <!-- Week strip (this week only) -->
    <div role="tablist" aria-label="Week" class="grid grid-cols-7 gap-1.5">
      {#each weekDays as d (d.toISOString())}
        {@const iso = format(d, 'yyyy-MM-dd')}
        {@const sel = iso === selectedIso}
        {@const first = (workoutsByIso[iso] ?? [])[0]}
        <button
          type="button"
          role="tab"
          aria-selected={sel}
          class="h-[72px] rounded-[14px] flex flex-col items-center justify-center gap-1 cursor-pointer {sel ? 'bg-text0 text-bg0 border border-text0' : 'bg-bg2 text-text0 border border-border'}"
          onclick={() => selectDate(d)}
        >
          <span class="font-mono text-[10px] tracking-[0.08em] opacity-75 uppercase">{format(d, 'EEE')}</span>
          <span class="text-base font-medium">{format(d, 'd')}</span>
          <span aria-hidden="true" class="w-[5px] h-[5px] rounded-full" style="background: {first ? sessionColor(first) : 'transparent'}"></span>
        </button>
      {/each}
    </div>

    {#if trainingStore.isLoading}
      <div class="h-[220px] rounded-[24px] bg-bg2 animate-pulse"></div>
    {:else if dayItems.length === 0}
      <section class="bg-bg2 border border-border rounded-[24px] p-5 flex flex-col gap-1.5">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2 uppercase">{format(selectedDate, 'EEE')} · Rest</span>
        <h2 class="m-0 font-display font-normal text-[32px] leading-[1.05]">Nothing planned</h2>
        <p class="m-0 text-sm leading-[1.45] text-text1">No sessions on this day. Ask your coach if you want to add one.</p>
      </section>
    {:else}
      {#each dayItems as w (w.id)}
        {@const steps = structuredSteps(w)}
        <section aria-label="Selected session" class="bg-bg2 border border-border rounded-[24px] p-5 flex flex-col gap-3.5">
          <div class="flex justify-between items-center">
            <span class="font-mono text-[11px] tracking-[0.14em] uppercase" style="color: var(--blue)">{format(w.date, 'EEE')} · {sessionLabel(w)}</span>
            <button type="button" class="min-h-8 flex items-center gap-1 border-0 bg-transparent p-0 font-mono text-[11px] text-text1 cursor-pointer" onclick={() => openWorkout(w)}>
              {Number.isFinite(Number(w.tss)) ? `${w.tss} TSS · ` : ''}DETAILS
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
            </button>
          </div>
          <div class="flex flex-col gap-1">
            <h2 class="m-0 font-display font-normal text-[32px] leading-[1.05]">{w.title ?? w.type ?? 'Session'}</h2>
            {#if w.context}<p class="m-0 text-sm leading-[1.45] text-text1 line-clamp-3">{plainText(w.context)}</p>{/if}
          </div>
          {#if steps.length > 0}
            <ol aria-label="Steps" class="list-none m-0 p-0 flex flex-col border-t border-border">
              {#each steps as s, i (i)}
                <li class="flex items-center gap-3 py-[11px] border-b border-border/70">
                  <span aria-hidden="true" class="w-1 h-[22px] rounded-sm shrink-0" style="background: {s.color}"></span>
                  <span class="flex-1 min-w-0 truncate text-sm">{s.title}</span>
                  {#if s.target}<span class="font-mono text-xs text-text1">{s.target}</span>{/if}
                  <span class="w-[52px] text-right font-mono text-xs text-text2">{s.duration ?? ''}</span>
                </li>
              {/each}
            </ol>
          {/if}
        </section>
      {/each}
    {/if}

    {#if laterThisWeek.length > 0}
      <section aria-label="Rest of week" class="flex flex-col gap-2">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2">LATER THIS WEEK</span>
        {#each laterThisWeek as w (w.id)}
          <button type="button" class="flex justify-between items-center px-4 py-3.5 rounded-2xl bg-bg1 border border-border text-left w-full cursor-pointer" onclick={() => openWorkout(w)}>
            <span class="flex flex-col gap-0.5 min-w-0">
              <span class="text-sm font-medium truncate">{w.title ?? w.type ?? 'Session'}{w.duration ? ` · ${w.duration}` : ''}</span>
              <span class="text-xs text-text2">{format(w.date, 'EEE')} · {sessionLabel(w).toLowerCase()}</span>
            </span>
            <span class="shrink-0 font-mono text-xs" style="color: {sessionColor(w)}">{Number.isFinite(Number(w.tss)) ? `${w.tss} TSS` : ''}</span>
          </button>
        {/each}
      </section>
    {/if}
  {:else}
    <!-- Month -->
    <section aria-label={format(viewMonth, 'MMMM yyyy')} class="bg-bg2 border border-border rounded-[24px] px-3 pt-3 pb-3.5 flex flex-col gap-2">
      <MonthNavigator value={format(viewMonth, 'yyyy-MM')} onchange={onMonthChange} />
      <div aria-hidden="true" class="grid grid-cols-7 gap-1 text-center font-mono text-[10px] tracking-[0.08em] text-text2">
        {#each ['M', 'T', 'W', 'T', 'F', 'S', 'S'] as l, i (i)}<span>{l}</span>{/each}
      </div>
      <div class="grid grid-cols-7 gap-1">
        {#each monthDays as d (d.toISOString())}
          {@const iso = format(d, 'yyyy-MM-dd')}
          {@const inMonth = isSameMonth(d, viewMonth)}
          {@const isSel = iso === selectedIso}
          {@const isToday = iso === todayIso}
          {@const past = iso < todayIso}
          {@const first = (workoutsByIso[iso] ?? [])[0]}
          <button
            type="button"
            aria-label="{format(d, 'EEEE d MMMM')}{first ? ': ' + (first.title ?? 'Session') : ''}"
            class="h-[50px] rounded-[10px] flex flex-col items-center justify-center gap-1.5 p-0 cursor-pointer border {isSel ? 'bg-bg3 border-blue' : 'bg-transparent border-transparent'}"
            onclick={() => selectDate(d)}
          >
            <span class="text-[13px] {isToday ? 'font-semibold text-blue' : inMonth ? (past ? 'font-medium text-text2' : 'font-medium text-text0') : 'font-medium text-text2/50'}">{format(d, 'd')}</span>
            <span aria-hidden="true" class="w-[18px] h-1 rounded-sm" style="background: {first ? sessionColor(first) : 'transparent'}; opacity: {inMonth && !past ? 1 : 0.35}"></span>
          </button>
        {/each}
      </div>
    </section>

    {#if dayItems.length === 0}
      <div class="flex items-center gap-3.5 px-[18px] py-4 rounded-[20px] bg-bg2 border border-border">
        <span aria-hidden="true" class="shrink-0 w-1.5 h-11 rounded-[3px] bg-bg3"></span>
        <span class="flex-1 flex flex-col gap-[3px]">
          <span class="font-mono text-[10px] tracking-[0.12em] text-text2 uppercase">{format(selectedDate, 'EEE d MMM')}</span>
          <span class="text-base font-medium">Rest day</span>
          <span class="text-xs text-text2">Nothing planned.</span>
        </span>
      </div>
    {:else}
      {#each dayItems as w (w.id)}
        <button type="button" class="flex items-center gap-3.5 px-[18px] py-4 rounded-[20px] bg-bg2 border border-border text-left w-full cursor-pointer" onclick={() => openWorkout(w)}>
          <span aria-hidden="true" class="shrink-0 w-1.5 h-11 rounded-[3px]" style="background: {sessionColor(w)}"></span>
          <span class="flex-1 min-w-0 flex flex-col gap-[3px]">
            <span class="font-mono text-[10px] tracking-[0.12em] text-text2 uppercase">{format(w.date, 'EEE d MMM')}</span>
            <span class="text-base font-medium truncate">{w.title ?? w.type ?? 'Session'}</span>
            <span class="text-xs text-text2">{[w.duration, Number.isFinite(Number(w.tss)) ? `${w.tss} TSS` : null].filter(Boolean).join(' · ')}</span>
          </span>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="text-text2"><path d="m9 6 6 6-6 6"></path></svg>
        </button>
      {/each}
    {/if}

    <div class="flex flex-wrap gap-x-3.5 gap-y-1.5 text-[11px] text-text2">
      {#each SESSION_LEGEND as l (l.label)}
        <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-2.5 h-1 rounded-sm" style="background: {l.color}"></span>{l.label}</span>
      {/each}
    </div>
  {/if}
</div>

{#if selectedWorkout}
  {@const sw = selectedWorkout}
  {@const steps = sessionSteps(sw)}
  {@const mins = durationMinutes(sw) || steps.reduce((a, s) => a + s.minutes, 0)}
  {@const ifValue = mins > 0 && Number(sw.tss) > 0 ? Math.sqrt(Number(sw.tss) / ((mins / 60) * 100)) : null}
  {@const atTarget = steps.filter((s) => s.zone >= 3).reduce((a, s) => a + s.minutes, 0)}
  {@const cur = steps[Math.min(stepIdx, Math.max(steps.length - 1, 0))]}
  <div class="fixed inset-0 z-50 flex flex-col justify-end" role="dialog" aria-modal="true" aria-labelledby="sess-title">
    <button type="button" class="absolute inset-0 bg-black/60" aria-label="Close" onclick={closeWorkout}></button>
    <div
      use:modalDialog={{ onEscape: closeWorkout }}
      class="relative overflow-y-auto outline-none bg-bg1 border-t border-border px-5 pt-2.5 flex flex-col gap-4 transition-[max-height,border-radius] duration-300 ease-out {sheetExpanded ? 'rounded-none' : 'rounded-t-[28px]'}"
      style="max-height: {sheetExpanded ? '100dvh' : '88dvh'}; height: {sheetExpanded ? '100dvh' : 'auto'}; padding-bottom: max(28px, env(safe-area-inset-bottom, 0px)); padding-top: {sheetExpanded ? 'max(10px, env(safe-area-inset-top, 0px))' : '10px'};"
      onscroll={(e) => { if (!sheetExpanded && (e.currentTarget as HTMLElement).scrollTop > 8) sheetExpanded = true; }}
    >
      <span aria-hidden="true" class="self-center w-10 h-1 rounded-sm bg-bg3"></span>

      <div class="flex justify-between items-start gap-3">
        <div class="flex flex-col gap-1.5 min-w-0">
          <span class="font-mono text-[11px] tracking-[0.14em] text-blue uppercase">{format(sw.date, 'EEE d MMM')} · {sessionLabel(sw)}{sw.type ? ` · ${sw.type}` : ''}</span>
          <h1 id="sess-title" class="m-0 font-display font-normal text-[32px] leading-[1.05]">{sw.title ?? sw.type ?? 'Session'}</h1>
        </div>
        <button type="button" aria-label="Close" class="shrink-0 w-11 h-11 rounded-full bg-bg3 border-0 text-text1 flex items-center justify-center cursor-pointer" onclick={closeWorkout}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>
        </button>
      </div>

      <section aria-label="Prescription" class="grid grid-cols-4 gap-1.5">
        {#each [
          { k: 'Duration', v: mins > 0 ? `${mins}′` : '—' },
          { k: 'TSS', v: Number.isFinite(Number(sw.tss)) ? String(sw.tss) : '—' },
          { k: 'IF', v: ifValue ? ifValue.toFixed(2) : '—' },
          { k: 'At target', v: steps.length ? `${atTarget}′` : '—' }
        ] as t (t.k)}
          <div class="bg-bg3 rounded-[14px] p-2.5 flex flex-col gap-0.5"><span class="text-[17px] font-medium">{t.v}</span><span class="text-[10px] text-text2">{t.k}</span></div>
        {/each}
      </section>

      {#if steps.length > 0 && cur}
        <!-- Interactive profile -->
        <section aria-label="Workout profile" class="flex flex-col gap-2">
          <div class="flex justify-between items-baseline">
            <span class="font-mono text-[11px] tracking-[0.14em] text-text2">PROFILE · TAP A BLOCK</span>
            {#if planFtp}<span class="font-mono text-[10px] text-text2">FTP {planFtp} W</span>{/if}
          </div>
          <div class="relative h-24">
            <span aria-hidden="true" class="absolute left-0 right-0 top-3.5 border-t border-dashed border-text2/40"></span>
            <span aria-hidden="true" class="absolute right-0 top-0 font-mono text-[9px] text-text2/70">100%</span>
            <div role="group" aria-label="Workout steps" class="absolute inset-0 flex items-end gap-0.5">
              {#each steps as s, i (i)}
                <button
                  type="button"
                  aria-label="Step {i + 1}, {s.title}: {s.minutes} minutes{s.watts ? ' at ' + s.watts : ''}"
                  aria-pressed={i === stepIdx}
                  class="h-24 p-0 border-0 bg-transparent cursor-pointer flex items-end {i === stepIdx ? 'outline outline-2 outline-offset-1 outline-text0 rounded-[5px]' : ''}"
                  style="flex: {Math.max(s.minutes, 1)} 1 0"
                  onclick={() => (stepIdx = i)}
                >
                  <span aria-hidden="true" class="block w-full rounded" style="height: {s.barHeight}px; background: {s.color}; opacity: {i === stepIdx ? 1 : 0.55}"></span>
                </button>
              {/each}
            </div>
          </div>
          <div aria-hidden="true" class="flex justify-between font-mono text-[10px] text-text2">
            {#each profileTicks(mins) as t (t)}<span>{t}′</span>{/each}
          </div>
        </section>

        <!-- Selected step -->
        <section aria-live="polite" aria-label="Selected step" class="flex flex-col gap-3 p-4 rounded-[20px] bg-bg3/60 border {cur.zone >= 3 ? 'border-text2/40' : 'border-border'}">
          <div class="flex justify-between items-start gap-2.5">
            <div class="flex flex-col gap-1 min-w-0">
              <span class="font-mono text-[10px] tracking-[0.12em] text-text2">STEP {stepIdx + 1} OF {steps.length} · {cur.window}</span>
              <h2 class="m-0 font-display font-normal text-[26px] leading-[1.05]">{cur.title}</h2>
            </div>
            {#if cur.zone > 0}
              <span class="shrink-0 px-2.5 py-1 rounded-lg font-mono text-[11px] font-medium text-bg0" style="background: {cur.color}">Z{cur.zone}</span>
            {/if}
          </div>
          <div class="flex items-baseline gap-2">
            <span class="text-[30px] font-medium tracking-[-0.02em]">{cur.watts ?? cur.target ?? '—'}</span>
            {#if cur.pctLabel}<span class="text-[13px] text-text2">{cur.pctLabel}</span>{/if}
            <span class="ml-auto font-mono text-sm">{cur.minutes} min</span>
          </div>
          <dl class="m-0 grid grid-cols-3 gap-2 pt-2.5 border-t border-border">
            <div><dt class="text-[10px] text-text2">Zone</dt><dd class="m-0 text-[13px] font-medium">{cur.zone > 0 ? `Z${cur.zone} · ${ZONE_NAMES[cur.zone]}` : '—'}</dd></div>
            <div><dt class="text-[10px] text-text2">Heart rate</dt><dd class="m-0 text-[13px] font-medium">{cur.hr ?? '—'}</dd></div>
            <div><dt class="text-[10px] text-text2">Effort (RPE)</dt><dd class="m-0 text-[13px] font-medium">{cur.rpe ?? '—'}</dd></div>
          </dl>
          {#if cur.note}<p class="m-0 text-sm leading-[1.5] text-text1">{cur.note}</p>{/if}
          {#if cur.isRest}
            <div class="flex gap-2.5 items-start px-3 py-2.5 rounded-xl bg-bg1 border border-dashed border-border">
              <span class="font-mono text-[10px] tracking-[0.1em] text-green pt-0.5">READY?</span>
              <span class="text-xs leading-[1.45] text-text1">Start the next block when your heart rate is back in {cur.restHr ?? 'Zone 1'} and breathing is conversational.</span>
            </div>
          {/if}
          <div class="flex gap-2">
            <button type="button" aria-label="Previous step" disabled={stepIdx === 0} class="flex-1 h-10 rounded-xl border border-border bg-transparent text-[13px] font-medium {stepIdx === 0 ? 'text-text2/40 cursor-default' : 'text-text0 cursor-pointer'}" onclick={() => (stepIdx = Math.max(0, stepIdx - 1))}>‹ Prev</button>
            <button type="button" aria-label="Next step" disabled={stepIdx >= steps.length - 1} class="flex-1 h-10 rounded-xl border border-border bg-transparent text-[13px] font-medium {stepIdx >= steps.length - 1 ? 'text-text2/40 cursor-default' : 'text-text0 cursor-pointer'}" onclick={() => (stepIdx = Math.min(steps.length - 1, stepIdx + 1))}>Next ›</button>
          </div>
        </section>

        <!-- Full step list -->
        <ol aria-label="All steps" class="list-none m-0 p-0 flex flex-col">
          {#each steps as s, i (i)}
            <li>
              <button
                type="button"
                aria-pressed={i === stepIdx}
                class="w-full min-h-[52px] flex items-center gap-2.5 px-2 py-1.5 border-0 border-t border-border text-text0 text-left cursor-pointer {i === stepIdx ? 'bg-bg3' : 'bg-transparent'}"
                onclick={() => (stepIdx = i)}
              >
                <span aria-hidden="true" class="shrink-0 w-1 h-[30px] rounded-sm" style="background: {s.color}"></span>
                <span class="w-10 font-mono text-[11px] text-text2">{s.start}</span>
                <span class="flex-1 min-w-0 flex flex-col gap-px">
                  <span class="text-sm font-medium truncate">{s.title}</span>
                  <span class="text-[11px] text-text2 truncate">{s.sub}</span>
                </span>
                {#if s.watts}<span class="font-mono text-xs text-text1">{s.watts}</span>{/if}
                <span class="w-[34px] text-right font-mono text-xs text-text2">{s.minutes}′</span>
              </button>
            </li>
          {/each}
        </ol>
      {/if}

      {#if sessionDetailContext.hasPrescriptionTable}
        <section aria-label="Prescription table" class="flex flex-col gap-2.5">
          <span class="font-mono text-[11px] tracking-[0.14em] text-text2">PRESCRIPTION</span>
          {#key sessionDetailContext.prescriptionMarkdown}
            <div use:enhancePrescriptionTable class="rounded-2xl overflow-hidden bg-bg3 px-2 py-2 sm:px-4 sm:py-3 {prescriptionProseClass}">
              {@html renderCoachMarkdownToSafeHtml(sessionDetailContext.prescriptionMarkdown)}
            </div>
          {/key}
        </section>
      {/if}

      {#if sessionDetailContext.coachNotes.length > 0}
        <section aria-label="Coach's notes" class="flex flex-col gap-2 px-4 py-3.5 rounded-[18px] bg-bg3">
          <span class="font-mono text-[10px] tracking-[0.12em] text-blue">COACH'S NOTES</span>
          <div class="{coachNotesMarkdownProseClass} text-[13px]">
            {@html renderCoachMarkdownToSafeHtml(sessionDetailContext.coachNotes)}
          </div>
        </section>
      {/if}

      {#if backendTrainingPlanId(sw)}
        {#if sheetMode === 'move'}
          <section aria-label="Move session" class="flex flex-col gap-3 p-4 rounded-[20px] bg-bg3/60 border border-border">
            <span class="font-mono text-[10px] tracking-[0.12em] text-text2">MOVE TO</span>
            <DatePicker bind:value={moveDate} ariaLabel="New date for this session" buttonClass="h-11 px-3 rounded-xl border border-border bg-bg1 text-sm text-text0" />
            <div class="flex gap-2">
              <button type="button" class="flex-1 h-11 rounded-xl border border-border bg-transparent text-text0 text-sm font-medium cursor-pointer" onclick={() => (sheetMode = 'none')}>Cancel</button>
              <button type="button" class="flex-1 h-11 rounded-xl border-0 bg-blue text-[#0B1420] text-sm font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default" disabled={savingPlan || !moveDate || moveDate === sw.isoDate} onclick={() => moveSession(sw, moveDate)}>{savingPlan ? 'Moving…' : 'Move here'}</button>
            </div>
          </section>
        {:else if sheetMode === 'swap'}
          {@const others = swapCandidates(sw)}
          <section aria-label="Swap session" class="flex flex-col gap-2 p-4 rounded-[20px] bg-bg3/60 border border-border">
            <span class="font-mono text-[10px] tracking-[0.12em] text-text2">SWAP DAYS WITH</span>
            {#if others.length === 0}
              <p class="m-0 text-[13px] text-text2">No other sessions this week.</p>
            {/if}
            {#each others as o (o.id)}
              <button type="button" class="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-border bg-bg1 text-left cursor-pointer disabled:opacity-40" disabled={savingPlan} onclick={() => swapSessions(sw, o)}>
                <span aria-hidden="true" class="shrink-0 w-1 h-8 rounded-sm" style="background: {sessionColor(o)}"></span>
                <span class="flex-1 min-w-0 flex flex-col">
                  <span class="font-mono text-[10px] tracking-[0.1em] text-text2 uppercase">{format(o.date, 'EEE d MMM')}</span>
                  <span class="text-sm font-medium truncate">{o.title ?? o.type ?? 'Session'}</span>
                </span>
                <span class="shrink-0 text-xs text-text2">{o.duration ?? ''}</span>
              </button>
            {/each}
            <button type="button" class="mt-1 h-11 rounded-xl border border-border bg-transparent text-text0 text-sm font-medium cursor-pointer" onclick={() => (sheetMode = 'none')}>Cancel</button>
          </section>
        {/if}
        {#if planActionError}
          <p class="m-0 text-[13px] text-red">{planActionError}</p>
        {/if}
        <div class="mt-auto flex gap-2">
          <button type="button" class="flex-1 h-12 rounded-[14px] border border-border bg-transparent text-text0 text-sm font-medium cursor-pointer {sheetMode === 'move' ? 'bg-bg3' : ''}" onclick={() => { moveDate = sw.isoDate; sheetMode = sheetMode === 'move' ? 'none' : 'move'; }}>Move</button>
          <button type="button" class="flex-1 h-12 rounded-[14px] border border-border bg-transparent text-text0 text-sm font-medium cursor-pointer {sheetMode === 'swap' ? 'bg-bg3' : ''}" onclick={() => (sheetMode = sheetMode === 'swap' ? 'none' : 'swap')}>Swap</button>
          <button
            type="button"
            aria-label="Remove from plan"
            class="w-12 h-12 shrink-0 rounded-[14px] border border-red/50 bg-transparent text-red flex items-center justify-center cursor-pointer disabled:opacity-50 disabled:pointer-events-none"
            disabled={removingPlanWorkout}
            onclick={removeSelectedTrainingPlan}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg>
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}
