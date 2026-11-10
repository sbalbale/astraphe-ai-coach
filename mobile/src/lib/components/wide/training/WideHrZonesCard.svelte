<script lang="ts">
  /** Heart-rate zones for one workout: stacked bar plus Z5→Z1 rows (time and share). */
  import { HR_ZONE_HEX, canonicalHrZoneShortName, formatZoneBpmRange, hrZoneAnchorLabel } from '$lib/hrZoneDisplay';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import type { ZoneDef } from '$lib/services/activityService';
  import { formatMMSS, getHrZonePcts, getHrZonePctsTopDown, hasAnyHrZone } from '$lib/utils/trainingFormat';

  let {
    workout,
    durationSecs,
    zoneDefs,
    lthr = 0
  }: {
    workout: Record<string, any>;
    durationSecs: number;
    zoneDefs: ZoneDef[];
    lthr?: number;
  } = $props();
  // What the zones are built from (HR reserve, LTHR or max HR), not always "LTHR".
  const anchor = $derived(hrZoneAnchorLabel(athleteStore.profile as any) ?? (lthr ? `LTHR ${lthr}` : null));
</script>

<section aria-label="Heart-rate zones" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3 min-w-0">
  <div class="flex justify-between items-baseline">
    <h2 class="m-0 font-display font-normal text-[22px]">Heart-rate zones</h2>
    {#if anchor}<span class="font-mono text-[11px] text-text2">{anchor}</span>{/if}
  </div>
  {#if hasAnyHrZone(workout)}
    {@const zp = getHrZonePcts(workout)}
    <div aria-hidden="true" class="flex gap-[3px] h-2.5">
      {#each zp as p, i (i)}
        {#if (p ?? 0) > 0}<span class="rounded-[3px]" style="flex: {p} 1 0; min-width: 4px; background: var(--zone-{i + 1})"></span>{/if}
      {/each}
    </div>
    <div class="flex flex-col">
      {#each getHrZonePctsTopDown(workout) as pct, topIdx (topIdx)}
        {@const zone = 5 - topIdx}
        {@const zDef = zoneDefs.find((d) => d.zone === zone)}
        {@const zn = canonicalHrZoneShortName(zone) || zDef?.name}
        <div class="grid grid-cols-[12px_1fr_auto_auto_auto] items-center gap-2.5 py-2.5 border-t border-border text-[14px]">
          <span aria-hidden="true" class="h-2.5 w-2.5 rounded-[3px]" style="background: {HR_ZONE_HEX[zone]}"></span>
          <span class="min-w-0 truncate"><span class="font-semibold">Z{zone}</span>{#if zn}<span class="ml-1.5 text-text1">{zn}</span>{/if}</span>
          <span class="font-mono text-[11px] text-text2">{formatZoneBpmRange(zDef)}</span>
          <span class="w-9 text-right font-mono text-[12px] text-text1 tabular-nums">{pct == null ? '--' : `${Math.round(pct)}%`}</span>
          <span class="w-12 text-right font-mono text-[12px] tabular-nums">{pct == null ? '--' : formatMMSS((durationSecs * pct) / 100)}</span>
        </div>
      {/each}
    </div>
  {:else}
    <p class="m-0 text-[13px] text-text2">No zone data for this workout.</p>
  {/if}
</section>
