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

  /** What each provider contributes, for the one-line summary under its name. */
  const SOURCE_PROVIDES: Record<string, string> = {
    garmin: 'GPS · Streams · Power · Laps',
    strava: 'Activity title · Segments',
    whoop: 'Strain · Recovery · HRV',
    healthkit: 'Heart rate · Workouts',
    intervals_icu: 'Intervals · Power · Laps',
    manual: 'Logged by hand',
  };

  const sources = $derived(Object.keys(effectiveSourceIds));
  const primary = $derived(workout?.primary_source ?? workout?.source ?? '');
  const merged = $derived(sources.length > 1);
</script>

<div class="flex flex-col gap-1">
  <div class="mb-1 flex items-baseline justify-between">
    <h2 class="m-0 font-display font-normal text-[22px]">Data sources</h2>
    {#if merged}<span class="font-mono text-[10px] tracking-[0.08em] text-text2 uppercase">⟷ Merged</span>{/if}
  </div>

  {#each sources as source (source)}
    {@const meta = SOURCE_META[source] ?? { label: source, color: '#6B7280', icon: '?' }}
    <div class="flex items-center gap-3 border-t border-border py-3">
      <span aria-hidden="true" class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-bg3 font-mono text-sm text-text1">{meta.icon}</span>
      <div class="flex min-w-0 flex-col gap-0.5">
        <span class="flex items-center gap-2 text-base font-medium">
          {meta.label}
          {#if source === primary}
            <span class="rounded-lg border border-blue/40 bg-blue-dim px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-blue">Primary</span>
          {/if}
        </span>
        <span class="truncate text-[13px] text-text2">{SOURCE_PROVIDES[source] ?? ''}</span>
      </div>
    </div>
  {/each}

  {#if sources.length > 0}
    <button
      type="button"
      class="mt-1 flex h-10 items-center gap-1.5 border-0 bg-transparent p-0 text-sm text-text1 cursor-pointer"
      onclick={() => (expanded = !expanded)}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="transition-transform duration-150 {expanded ? 'rotate-90' : ''}"><path d="m9 6 6 6-6 6"></path></svg>
      {expanded ? 'Hide IDs' : 'Show IDs'}
    </button>

    {#if expanded}
      <div class="space-y-0.5 pl-5 font-mono text-[11px] text-text2">
        {#each sources as source (source)}
          {@const raw = effectiveSourceIds[source]}
          <p class="m-0">
            <span class="text-text1">{source}:</span>
            {Array.isArray(raw) ? raw.join(', ') : String(raw ?? '—')}
          </p>
        {/each}
      </div>
    {/if}
  {/if}
</div>
