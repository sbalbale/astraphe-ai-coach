<script lang="ts">
  /**
   * Wide Body view: the three score tiles (design: WBody). They act as tabs, switching
   * between /recovery, /sleep and /strain; the picked day carries over via bodyDate.
   */
  import { goto } from '$app/navigation';
  import { format } from 'date-fns';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { boundedScoreCssColor } from '$lib/scoreColors';
  import { currentRecoveryState } from '$lib/utils/biometrics';
  import { baselineBefore, dayStrain, finite, formatMinutes, workoutsOn } from '$lib/utils/bodyWide';

  type Tab = 'recovery' | 'sleep' | 'strain';
  let { active, day }: { active: Tab; day: string } = $props();

  const C = 302; // 2πr for r = 48

  const series = $derived((athleteStore.biometrics?.series ?? []) as Record<string, any>[]);
  const todayStr = $derived(format(new Date(), 'yyyy-MM-dd'));
  const current = $derived(currentRecoveryState(athleteStore.biometrics?.series, athleteStore.profile?.timezone_offset_min));
  const dayRow = $derived(series.find((r) => r?.date === day) ?? null);
  /** Today with no row yet carries last night's row forward, as the Recovery page does. */
  const row = $derived(dayRow ?? (day === todayStr ? (current.row as Record<string, any> | null) : null));
  // Like the Recovery / Sleep pages, today also carries forward when its row exists but has no
  // score yet (e.g. a weight-only row saved before the overnight sync). Otherwise the tile read
  // "No score" next to a page showing yesterday's score as carried over.
  const carried = $derived(day === todayStr ? (current.row as Record<string, any> | null) : null);
  const recoveryRow = $derived(pos(row?.recovery_score) === null && carried ? carried : row);
  const sleepRow = $derived(
    pos(row?.sleep_duration_min) === null && pos(row?.sleep_score) === null && carried ? carried : row
  );

  function pos(v: unknown): number | null {
    const n = finite(v);
    return n !== null && n > 0 ? n : null;
  }

  const recovery = $derived.by(() => {
    const score = pos(recoveryRow?.recovery_score);
    if (score === null) return { value: '--', p: 0, color: 'var(--text2)', state: 'No score', blurb: 'Recovery needs an overnight reading from WHOOP or Garmin.' };
    const bits: string[] = [];
    const hrv = pos(recoveryRow?.hrv_rmssd);
    const hrvBase = baselineBefore(series, day, 'hrv_rmssd');
    if (hrv !== null && hrvBase !== null) {
      const pct = ((hrv - hrvBase) / hrvBase) * 100;
      bits.push(Math.abs(pct) < 3 ? 'HRV at baseline' : `HRV ${pct > 0 ? 'above' : 'below'} baseline`);
    }
    const rhr = pos(recoveryRow?.resting_hr);
    const rhrBase = baselineBefore(series, day, 'resting_hr');
    if (rhr !== null && rhrBase !== null) {
      const d = Math.round(rhr - rhrBase);
      bits.push(d === 0 ? 'resting HR steady' : `resting HR ${d > 0 ? 'up' : 'down'}`);
    }
    const blurb = bits.length ? bits.join(', ').replace(/^./, (c) => c.toUpperCase()) + '.' : '';
    const s = Math.round(score);
    return {
      value: `${s}%`,
      p: s,
      color: boundedScoreCssColor(s),
      state: s >= 67 ? 'Recovered' : s >= 34 ? 'Moderate' : 'Fatigued',
      blurb
    };
  });

  const sleep = $derived.by(() => {
    const mins = pos(sleepRow?.sleep_duration_min);
    const score = pos(sleepRow?.sleep_score);
    if (mins === null && score === null) return { value: '--', p: 0, color: 'var(--text2)', state: 'No sleep', blurb: 'Nothing recorded for this night.' };
    let inBed = pos(sleepRow?.sleep_in_bed_min);
    if (inBed === null && sleepRow?.sleep_bedtime && sleepRow?.sleep_wakeup) {
      const span = (Date.parse(sleepRow.sleep_wakeup) - Date.parse(sleepRow.sleep_bedtime)) / 60000;
      if (span > 0) inBed = span;
    }
    const bits: string[] = [];
    if (mins !== null && inBed !== null && inBed > 0) bits.push(`${Math.min(100, Math.round((mins / inBed) * 100))}% efficient`);
    const debt = finite(sleepRow?.sleep_debt_min);
    if (debt !== null) bits.push(debt <= 0 ? 'no sleep debt' : `${Math.round(debt)} min of debt left`);
    return {
      value: score !== null ? String(Math.round(score)) : '--',
      p: score ?? 0,
      color: score !== null ? boundedScoreCssColor(score) : 'var(--text2)',
      state: mins !== null ? `${formatMinutes(mins)} asleep` : 'Asleep: --',
      blurb: bits.length ? bits.join(' · ').replace(/^./, (c) => c.toUpperCase()) + '.' : ''
    };
  });

  const strain = $derived.by(() => {
    const ws = workoutsOn(athleteStore.workouts as Record<string, any>[] | undefined, day);
    const r = dayStrain(dayRow, ws);
    const tss = ws.reduce((a, w) => a + (pos(w?.tss) ?? 0), 0);
    const blurb = ws.length
      ? `${ws.length} workout${ws.length > 1 ? 's' : ''}${tss > 0 ? ` · ${Math.round(tss)} TSS` : ''}.`
      : r.score > 0
        ? 'No workouts; all-day activity only.'
        : 'No workouts logged.';
    return {
      value: r.score > 0 || ws.length ? String(r.score) : '--',
      p: r.score,
      color: 'var(--blue)',
      state: r.score >= 67 ? 'High' : r.score >= 34 ? 'Moderate' : r.score > 0 ? 'Light' : 'Rest',
      blurb
    };
  });

  const tiles = $derived([
    { id: 'recovery' as const, name: 'RECOVERY', href: '/recovery', ...recovery },
    { id: 'sleep' as const, name: 'SLEEP', href: '/sleep', ...sleep },
    { id: 'strain' as const, name: 'STRAIN', href: '/strain', ...strain }
  ]);

  function pick(t: Tab, href: string) {
    if (t === active) return;
    void goto(href, { keepFocus: true, noScroll: true });
  }
</script>

<div role="tablist" aria-label="Body scores" class="grid grid-cols-3 gap-4">
  {#each tiles as t (t.id)}
    {@const on = t.id === active}
    <button
      type="button"
      role="tab"
      aria-selected={on}
      class="rounded-[24px] p-5 flex gap-[18px] items-center text-left cursor-pointer text-text0 border transition-colors {on ? 'bg-accent-surface border-blue' : 'bg-bg2 border-border hover:border-popover-border'}"
      onclick={() => pick(t.id, t.href)}
    >
      <span class="relative flex-none w-[104px] h-[104px]">
        <svg width="104" height="104" viewBox="0 0 112 112" aria-hidden="true" class="block -rotate-90">
          <circle cx="56" cy="56" r="48" fill="none" stroke="var(--border)" stroke-width="8"></circle>
          {#if t.p > 0}
            <circle cx="56" cy="56" r="48" fill="none" stroke={t.color} stroke-width="8" stroke-linecap="round" stroke-dasharray="{Math.round((C * Math.min(t.p, 100)) / 100)} {C}"></circle>
          {/if}
        </svg>
        <span class="absolute inset-0 flex items-center justify-center font-display text-[38px] leading-none">{t.value}</span>
      </span>
      <span class="flex flex-col gap-1.5 min-w-0">
        <span class="font-mono text-[11px] tracking-[0.14em] {on ? 'text-text0' : 'text-text2'}">{t.name}</span>
        <span class="text-[13px] font-semibold" style="color: {t.color}">{t.state}</span>
        {#if t.blurb}<span class="text-[13px] leading-[1.45] text-text1">{t.blurb}</span>{/if}
      </span>
    </button>
  {/each}
</div>
