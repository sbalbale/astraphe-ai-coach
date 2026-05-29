<script lang="ts">
  let { workout }: { workout: any } = $props();

  let expanded = $state(false);

  const SOURCE_META: Record<string, { label: string; color: string; icon: string }> = {
    strava: { label: 'Strava', color: '#FC4C02', icon: 'S' },
    whoop: { label: 'WHOOP', color: '#00C4CC', icon: 'W' },
    garmin: { label: 'Garmin', color: '#009CDE', icon: 'G' },
    healthkit: { label: 'HealthKit', color: '#FF2D55', icon: '♥' },
    manual: { label: 'Manual', color: '#6B7280', icon: 'M' },
  };

  const effectiveSourceIds = $derived.by((): Record<string, string | string[]> => {
    const raw = workout?.source_ids;
    if (raw && typeof raw === 'object' && Object.keys(raw).length > 0) {
      return raw;
    }
    // Fallback for cached/list payloads missing source_ids (legacy API responses).
    const out: Record<string, string | string[]> = {};
    const legacy = workout?.primary_source || workout?.source;
    if (!legacy) return out;
    if (legacy === 'strava' && workout?.strava_activity_id != null) {
      out.strava = [String(workout.strava_activity_id)];
    } else if (workout?.external_id != null) {
      out[legacy] = String(workout.external_id);
    } else {
      out[legacy] = '—';
    }
    return out;
  });

  const sources = $derived(Object.keys(effectiveSourceIds));
  const primary = $derived(workout?.primary_source ?? workout?.source ?? '');
  const merged = $derived(sources.length > 1);
</script>

<div class="space-y-2">
  <p class="text-[10px] font-mono text-text2 uppercase tracking-widest">Data Sources</p>

  <div class="flex flex-wrap items-center gap-2">
    {#if merged}
      <span class="text-[10px] text-text2 opacity-40 font-mono">⟷ Merged</span>
    {/if}

    {#each sources as source (source)}
      {@const meta = SOURCE_META[source] ?? { label: source, color: '#6B7280', icon: '?' }}
      {@const ids = effectiveSourceIds[source]}
      <div class="flex flex-wrap items-center gap-1.5">
        <span
          class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border"
          style="color: {meta.color}; border-color: {meta.color}66; background: {meta.color}14;"
        >
          <span
            class="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold"
            style="background: {meta.color}28; color: {meta.color};"
          >{meta.icon}</span>
          {meta.label}
          {#if source === primary}
            <span class="text-[9px] uppercase tracking-wider opacity-80">Primary</span>
          {/if}
        </span>

        {#if source === 'strava' && workout.strava_activity_id}
          <span class="text-[9px] font-mono text-text2">GPS · Streams</span>
        {/if}
        {#if source === 'whoop' && ids}
          <span class="text-[9px] font-mono text-text2">Recovery · HRV</span>
        {/if}
      </div>
    {/each}
  </div>

  {#if sources.length > 0}
    <button
      type="button"
      class="flex items-center gap-1 text-[10px] font-mono text-text2 bg-transparent border-none p-0 cursor-pointer"
      onclick={() => (expanded = !expanded)}
    >
      <span
        class="inline-block text-[8px] leading-none transition-transform duration-150 {expanded
          ? ''
          : '-rotate-90'}"
        aria-hidden="true">▼</span
      >
      {expanded ? 'Hide IDs' : 'Show IDs'}
    </button>

    {#if expanded}
      <div class="font-mono text-[10px] text-text2 space-y-0.5 pl-1">
        {#each sources as source (source)}
          {@const raw = effectiveSourceIds[source]}
          <p>
            <span class="text-text1">{source}:</span>
            {Array.isArray(raw) ? raw.join(', ') : String(raw ?? '—')}
          </p>
        {/each}
      </div>
    {/if}
  {/if}
</div>
