<script lang="ts">
  /** Recording facts for one workout (design: Data tab "Recording"); only stored fields. */
  import { format } from 'date-fns';
  import type { ActivityStreams } from '$lib/services/activityService';
  import { sampleRateLabel, streamChannels } from '$lib/utils/trainingFormat';

  let {
    workout,
    streams,
    use24h = false
  }: { workout: Record<string, any>; streams: ActivityStreams | null; use24h?: boolean } = $props();

  const LABELS: Record<string, string> = {
    garmin: 'Garmin', whoop: 'WHOOP', strava: 'Strava', healthkit: 'Apple Health', intervals_icu: 'Intervals.icu', manual: 'Manual'
  };
  const label = (s: string) => LABELS[s] ?? s;

  const rows = $derived.by(() => {
    const out: { k: string; v: string }[] = [];
    const start = workout?.started_at ? new Date(workout.started_at) : null;
    if (start && !Number.isNaN(start.getTime())) {
      out.push({ k: 'Recorded', v: format(start, use24h ? 'EEE d MMM, HH:mm' : 'EEE d MMM, h:mm a') });
    }
    const primary = String(workout?.primary_source ?? workout?.source ?? '');
    if (primary) out.push({ k: 'Primary source', v: label(primary) });
    const ids = workout?.source_ids && typeof workout.source_ids === 'object' ? Object.keys(workout.source_ids) : [];
    const others = ids.filter((s) => s !== primary);
    if (others.length) out.push({ k: 'Also seen on', v: others.map(label).join(', ') });
    const channels = streamChannels(streams);
    out.push({ k: 'Streams', v: channels.length ? channels.join(' · ') : 'None stored' });
    const rate = sampleRateLabel(streams);
    if (rate) out.push({ k: 'Sample rate', v: rate });
    return out;
  });
</script>

<section aria-label="Recording" class="bg-bg2 border border-border rounded-[24px] p-4 flex flex-col gap-1 min-w-0">
  <h2 class="m-0 mb-1.5 font-display font-normal text-[22px]">Recording</h2>
  {#each rows as r (r.k)}
    <div class="flex justify-between gap-3 py-[9px] border-t border-rail-border text-[13px]">
      <span class="text-text2">{r.k}</span>
      <span class="text-right">{r.v}</span>
    </div>
  {/each}
</section>
