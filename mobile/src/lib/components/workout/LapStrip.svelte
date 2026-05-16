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
  <div class="bg-glass2 border border-border rounded-2xl p-4">
    <p class="text-[11px] font-semibold text-text1 mb-3 font-sans">Laps</p>

    <div class="relative flex gap-0.5 h-7" role="list">
      {#each laps as lap, i (lap.lap_index ?? i)}
        {@const widthPct = barWidths[i]}
        <button
          type="button"
          class="h-full rounded-sm min-w-[8px] border-0 p-0 cursor-pointer transition-opacity {selectedLap === i
            ? 'opacity-100 ring-1 ring-white/40'
            : 'opacity-90 hover:opacity-100'}"
          style="width: {widthPct}%; background: {lapBarColor(lap.average_heartrate)};"
          aria-label={lapAriaLabel(lap, i)}
          onclick={() => (selectedLap = selectedLap === i ? null : i)}
        ></button>
      {/each}
    </div>

    {#if selectedLap != null}
      {@const lap = laps[selectedLap]}
      <div
        class="mt-2 p-2 rounded-lg bg-glass border border-border text-[10px] font-mono text-text1 grid grid-cols-2 gap-x-3 gap-y-1"
      >
        <span class="text-text2">Lap</span><span>{lap.lap_index ?? selectedLap + 1}</span>
        <span class="text-text2">Distance</span
        ><span>{formatSegmentDistance(lap.distance, measurementUnits, sport)}</span>
        <span class="text-text2">Avg HR</span><span>{lap.average_heartrate != null ? Math.round(lap.average_heartrate) : '—'}</span>
        <span class="text-text2">HR zone</span>
        <span class="flex items-center gap-1.5 min-w-0">
          {#if lap.average_heartrate != null && Number.isFinite(lap.average_heartrate)}
            <span
              class="w-2 h-2 rounded-sm shrink-0 border border-border/40"
              style="background: {lapBarColor(lap.average_heartrate)}"
            ></span>
            <span class="truncate">{lapZoneDescription(lap.average_heartrate)}</span>
          {:else}
            <span>—</span>
          {/if}
        </span>
        <span class="text-text2">{sport === 'row' ? 'Pace' : 'Avg speed'}</span><span>{formatLapPaceOrSpeed(lap)}</span>
        <span class="text-text2">Duration</span><span>{formatDuration(lap.elapsed_time ?? 0)}</span>
      </div>
    {/if}

    <div class="relative mt-2 h-4">
      {#each labelIndices as idx (idx)}
        {@const leftPct = barWidths.slice(0, idx).reduce((s, w) => s + w, 0) + barWidths[idx] / 2}
        <span
          class="absolute -translate-x-1/2 text-[9px] font-mono text-text2"
          style="left: {leftPct}%;"
        >
          {laps[idx].lap_index ?? idx + 1}
        </span>
      {/each}
    </div>
  </div>
{/if}
