<script lang="ts">
  /**
   * Wide Today: the selected day's session (design: WToday "Session").
   * Move reschedules within the week (swapping with that day's session); Swap / Add a session
   * hand the change to the coach, which can pick an alternative workout.
   */
  import { resolve } from '$app/paths';
  import { format } from 'date-fns';
  import { navTo } from '$lib/nav';
  import type { Workout } from '$lib/types/training';
  import {
    ZONE_RANGE_LABEL,
    profileBars,
    sessionTarget,
    sportLabel,
    statDuration,
    zoneNumber
  } from './todayWide';

  let {
    workout,
    dayIso,
    todayIso,
    days,
    byIso,
    ftp,
    provisional = false,
    saving = false,
    error = null,
    toast = null,
    onMove,
    onUndo,
    onDismissToast
  }: {
    workout: Workout | null;
    dayIso: string;
    todayIso: string;
    days: Date[];
    byIso: Record<string, Workout[]>;
    ftp: number;
    /** Today's readiness hasn't synced yet. */
    provisional?: boolean;
    saving?: boolean;
    error?: string | null;
    toast?: string | null;
    onMove: (targetIso: string) => void;
    onUndo: () => void;
    onDismissToast: () => void;
  } = $props();

  const day = $derived(new Date(dayIso + 'T12:00:00'));
  const isToday = $derived(dayIso === todayIso);
  const dayLabel = $derived(isToday ? 'TODAY' : format(day, 'EEE d MMM').toUpperCase());
  const kicker = $derived(
    workout
      ? [dayLabel, sportLabel(workout.sport), ZONE_RANGE_LABEL[workout.primary_zone] ?? ''].filter(Boolean).join(' · ')
      : `${dayLabel} · REST`
  );
  const bars = $derived(profileBars(workout));
  const canMove = $derived(!!workout && !workout.completed);

  let menu = $state<'move' | null>(null);
  $effect(() => {
    void dayIso;
    menu = null;
  });

  const moveTargets = $derived(
    days
      .map((d) => format(d, 'yyyy-MM-dd'))
      .filter((iso) => iso !== dayIso)
      .map((iso) => {
        const other = (byIso[iso] ?? []).find((w) => !w.completed);
        const past = iso < todayIso;
        return {
          iso,
          label: format(new Date(iso + 'T12:00:00'), 'EEEE d MMM'),
          hint: past ? 'In the past' : other ? `Swaps with ${other.title.toLowerCase()}` : 'Nothing planned',
          zone: other ? zoneNumber(other.primary_zone) : 0,
          disabled: past
        };
      })
  );

  function swap() {
    const when = isToday ? 'today' : `on ${format(day, 'EEEE d MMM')}`;
    const prompt = workout
      ? `Swap my ${workout.title} ${when} for something else.`
      : `Add a session to my plan ${when}: `;
    navTo(`/chat?prompt=${encodeURIComponent(prompt)}`);
  }

  function pick(iso: string) {
    menu = null;
    onMove(iso);
  }

  const ghost =
    'h-[46px] px-[18px] rounded-[14px] border border-popover-border bg-transparent text-text0 text-[14px] font-medium cursor-pointer hover:border-text3 disabled:opacity-50 disabled:cursor-default';
</script>

<section aria-label="Session" class="relative z-[4] bg-bg2 border border-border rounded-[28px] p-[26px] flex flex-col gap-[18px]">
  <div class="flex justify-between items-center gap-4">
    <span class="font-mono text-[11px] tracking-[0.14em] text-blue uppercase">{kicker}{provisional && isToday && workout ? ' · PROVISIONAL' : ''}</span>
    {#if workout}
      <a
        href={resolve(`/plan?session=${encodeURIComponent(workout.id)}`)}
        class="flex items-center gap-1 text-[13px] text-text1 no-underline hover:text-text0"
      >Session details<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg></a>
    {/if}
  </div>

  <div class="flex justify-between gap-6 items-end flex-wrap">
    <div class="flex flex-col gap-1.5 max-w-[360px] min-w-0">
      <h2 class="m-0 font-display font-normal text-[44px] leading-none">{workout ? workout.title : 'Rest day'}</h2>
      <p class="m-0 text-[15px] leading-normal text-text1">
        {#if !workout}
          Nothing planned. Sleep in, eat well, maybe a walk. Ask your coach if you want to add something.
        {:else if provisional && isToday}
          Your coach will confirm or adjust this once recovery comes in. Training before then? Go by feel and ease off if it feels harder than it should.
        {:else}
          {workout.description}
        {/if}
      </p>
    </div>
    {#if workout}
      <dl class="m-0 flex gap-7">
        <div class="flex flex-col-reverse gap-0.5"><dt class="text-[12px] text-text2">Duration</dt><dd class="m-0 text-[28px] font-medium tracking-[-0.02em]">{statDuration(workout.duration_minutes)}</dd></div>
        <div class="flex flex-col-reverse gap-0.5"><dt class="text-[12px] text-text2">Target</dt><dd class="m-0 text-[28px] font-medium tracking-[-0.02em]">{sessionTarget(workout, ftp)}</dd></div>
        <div class="flex flex-col-reverse gap-0.5"><dt class="text-[12px] text-text2">TSS</dt><dd class="m-0 text-[28px] font-medium tracking-[-0.02em]">{workout.projected_tss ? Math.round(workout.projected_tss) : '—'}</dd></div>
      </dl>
    {/if}
  </div>

  <div role="img" aria-label={workout ? `${workout.title} workout profile` : 'No session'} class="flex items-end gap-[3px] h-24">
    {#each bars as b, i (i)}
      <span
        class="block rounded-[5px]"
        style="flex: {b.grow} 1 0; height: {b.pct}%; background: {b.zone > 0 ? `var(--zone-${b.zone})` : 'var(--text2)'}"
        title={b.name || undefined}
      ></span>
    {/each}
  </div>

  <div class="relative flex gap-2.5 items-center">
    <button type="button" class={ghost} onclick={swap}>{workout ? 'Swap' : 'Add a session'}</button>
    {#if canMove}
      <button
        type="button"
        class={ghost}
        aria-expanded={menu === 'move'}
        aria-haspopup="menu"
        disabled={saving}
        onclick={() => (menu = menu === 'move' ? null : 'move')}
      >{saving ? 'Moving…' : 'Move'}</button>
    {/if}
    {#if menu === 'move'}
      <div class="fixed inset-0 z-[3]" aria-hidden="true" onclick={() => (menu = null)}></div>
      <div
        role="menu"
        aria-label="Move to"
        class="absolute left-0 top-[54px] z-30 w-[340px] p-2 rounded-[18px] bg-popover border border-popover-border shadow-[0_18px_44px_rgba(0,0,0,0.5)] flex flex-col gap-0.5"
      >
        <span class="px-2.5 py-1.5 font-mono text-[10px] tracking-[0.14em] text-text2">MOVE TO</span>
        {#each moveTargets as t (t.iso)}
          <button
            type="button"
            role="menuitem"
            disabled={t.disabled}
            class="flex items-center gap-2.5 p-2.5 border-0 rounded-xl bg-transparent text-text0 text-[14px] text-left cursor-pointer hover:bg-border disabled:opacity-40 disabled:cursor-default disabled:hover:bg-transparent"
            onclick={() => pick(t.iso)}
          >
            <span aria-hidden="true" class="flex-none w-1 h-[30px] rounded-sm" style="background: {t.zone ? `var(--zone-${t.zone})` : 'var(--bg3)'}"></span>
            <span class="flex-1 flex flex-col gap-px"><span>{t.label}</span><span class="text-[12px] text-text2">{t.hint}</span></span>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  {#if error}
    <p role="alert" class="m-0 text-[13px] text-red">{error}</p>
  {/if}
  {#if toast}
    <div role="status" class="flex items-center gap-3 px-3.5 py-2.5 rounded-[14px] bg-accent-surface border border-accent-surface-border text-[13px]">
      <span class="flex-1">{toast}</span>
      <button type="button" class="h-[30px] px-2.5 border-0 rounded-[9px] bg-transparent text-blue text-[13px] font-semibold cursor-pointer disabled:opacity-50" disabled={saving} onclick={onUndo}>Undo</button>
      <button type="button" aria-label="Dismiss" class="w-[30px] h-[30px] border-0 rounded-[9px] bg-transparent text-text2 cursor-pointer" onclick={onDismissToast}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>
      </button>
    </div>
  {/if}
</section>
