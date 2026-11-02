<script lang="ts">
  import type { ActivityLap, ZoneDef } from '$lib/services/activityService';
  import {
    bpmToHrZone,
    canonicalHrZoneShortName,
    hrZoneColorForBpm,
  } from '$lib/hrZoneDisplay';
  import {
    coercePaceSport,
    formatPaceWithSuffix,
    formatSpeedFromMps,
    paceSecondsFromVelocity,
    type Units,
  } from '$lib/utils/paceChart';
  import { formatSegmentDistance } from '$lib/utils/units';

  let {
    laps,
    sport,
    zones = [],
    measurementUnits = 'metric',
  }: {
    laps: ActivityLap[];
    sport: string;
    zones?: ZoneDef[];
    measurementUnits?: Units;
  } = $props();

  let selectedLap = $state<number | null>(null);

  function lapBarColor(bpm: number | null): string {
    return hrZoneColorForBpm(zones, bpm);
  }

  function lapZoneDescription(bpm: number | null): string {
    if (bpm == null || !Number.isFinite(bpm)) return 'No HR data';
    const z = bpmToHrZone(zones, bpm);
    if (z === 0) return zones.length ? 'Outside defined zones' : 'Add HR zones in training settings';
    const canon = canonicalHrZoneShortName(z);
    if (canon) return `Z${z} · ${canon}`;
    const def = zones.find((x) => x.zone === z);
    return def?.name ? `Z${z} · ${def.name}` : `Z${z}`;
  }

  function lapAriaLabel(lap: ActivityLap, i: number): string {
    const n = lap.lap_index ?? i + 1;
    const hr = lap.average_heartrate;
    if (hr == null || !Number.isFinite(hr)) return `Lap ${n}, no average HR`;
    return `Lap ${n}, average ${Math.round(hr)} bpm, ${lapZoneDescription(hr)}`;
  }

  const totalElapsed = $derived(laps.reduce((s, l) => s + (l.elapsed_time ?? 0), 0) || 1);

  const barWidths = $derived.by(() => {
    const raw = laps.map((lap) => {
      const pct = ((lap.elapsed_time ?? 0) / totalElapsed) * 100;
      return Math.max(8, pct);
    });
    const sum = raw.reduce((s, w) => s + w, 0);
    return raw.map((w) => (w / sum) * 100);
  });

  const barGridTemplate = $derived(barWidths.map((w) => `minmax(0, ${w}fr)`).join(' '));

  function formatLapPaceOrSpeed(lap: ActivityLap): string {
    const v = lap.average_speed;
    if (v == null || v <= 0) return '—';
    const kind = coercePaceSport(sport);
    if (kind === 'row' || kind === 'run') {
      const sec = paceSecondsFromVelocity(v, sport, measurementUnits);
      return formatPaceWithSuffix(sec, sport, measurementUnits);
    }
    return formatSpeedFromMps(v, measurementUnits);
  }

  function formatDuration(sec: number): string {
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  const labelIndices = $derived.by(() => {
    if (laps.length <= 3) return laps.map((_, i) => i);
    const mid = Math.floor(laps.length / 2);
    return [0, mid, laps.length - 1];
  });
</script>

{#if laps.length >= 2}
  <div>
    <div class="mb-3 flex items-baseline justify-between">
      <h2 class="m-0 font-display font-normal text-[22px]">Laps</h2>
      <span class="font-mono text-[10px] tracking-[0.08em] text-text2 uppercase">{laps.length} laps · tap for detail</span>
    </div>

    <div class="grid h-14 min-w-0 gap-1" role="list" style="grid-template-columns: {barGridTemplate};">
      {#each laps as lap, i (lap.lap_index ?? i)}
        <button
          type="button"
          class="h-full min-w-0 rounded-lg border-0 p-0 cursor-pointer transition-opacity {selectedLap === i
            ? 'opacity-100 ring-2 ring-text0'
            : 'opacity-60 hover:opacity-90'}"
          style="background: {lapBarColor(lap.average_heartrate)};"
          aria-label={lapAriaLabel(lap, i)}
          onclick={() => (selectedLap = selectedLap === i ? null : i)}
        ></button>
      {/each}
    </div>

    <div class="relative mt-2 h-4">
      {#each labelIndices as idx (idx)}
        {@const leftPct = barWidths.slice(0, idx).reduce((s, w) => s + w, 0) + barWidths[idx] / 2}
        <span class="absolute -translate-x-1/2 font-mono text-[10px] text-text2" style="left: {leftPct}%;">
          {laps[idx].lap_index ?? idx + 1}
        </span>
      {/each}
    </div>

    {#if selectedLap != null}
      {@const lap = laps[selectedLap]}
      <div class="mt-3 grid grid-cols-[auto_1fr_1fr_1fr_1fr] items-end gap-x-4 gap-y-1 rounded-2xl bg-bg3 px-4 py-3">
        <div class="flex flex-col"><span class="text-[11px] text-text2">Lap</span><span class="font-display text-[28px] leading-none">{lap.lap_index ?? selectedLap + 1}</span></div>
        <div class="flex flex-col gap-0.5"><span class="text-[11px] text-text2">Duration</span><span class="text-[15px] font-medium">{formatDuration(lap.elapsed_time ?? 0)}</span></div>
        <div class="flex flex-col gap-0.5"><span class="text-[11px] text-text2">Distance</span><span class="text-[15px] font-medium">{formatSegmentDistance(lap.distance, measurementUnits, sport)}</span></div>
        <div class="flex flex-col gap-0.5"><span class="text-[11px] text-text2">Avg HR</span><span class="text-[15px] font-medium">{lap.average_heartrate != null ? Math.round(lap.average_heartrate) + ' bpm' : '—'}</span></div>
        <div class="flex flex-col gap-0.5">
          <span class="text-[11px] text-text2">HR zone</span>
          <span class="flex items-center gap-1.5 min-w-0 text-[15px] font-semibold">
            {#if lap.average_heartrate != null && Number.isFinite(lap.average_heartrate)}
              <span class="h-2.5 w-2.5 shrink-0 rounded-[3px]" style="background: {lapBarColor(lap.average_heartrate)}"></span>
              <span class="truncate">{lapZoneDescription(lap.average_heartrate)}</span>
            {:else}—{/if}
          </span>
        </div>
        <div class="col-span-5 mt-1 flex items-baseline justify-between border-t border-border/60 pt-2 text-xs">
          <span class="text-text2">{sport === 'row' ? 'Pace' : 'Avg speed'}</span>
          <span class="font-mono text-text1">{formatLapPaceOrSpeed(lap)}</span>
        </div>
      </div>
    {/if}
  </div>
{/if}
