<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import ScoreGauge from '$lib/components/charts/ScoreGauge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { format } from 'date-fns';
  import { calculateRecoveryScore } from '$lib/utils/biometrics';

  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));

  const trend = $derived.by(() => {
    const dates = Array.from({ length: 7 }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - (6 - i)); // 7 days ending today
      return format(d, 'yyyy-MM-dd');
    });

    return dates.map(displayDateStr => {
      // Find biometrics for the PREVIOUS day (Day N-1 data is Day N recovery)
      const d = new Date(displayDateStr + 'T12:00:00');
      d.setDate(d.getDate() - 1);
      const dataDateStr = format(d, 'yyyy-MM-dd');

      const b = athleteStore.biometrics?.series?.find((s: any) => s.date === dataDateStr);
      
      return {
        date: displayDateStr,
        day: format(new Date(displayDateStr + 'T12:00:00'), 'EE').charAt(0),
        score: b?.astrape_recovery_score || b?.recovery_score || 0,
        missing: !b || !b.recovery_score,
        data: b
      };
    });
  });

  const latestBio = $derived(trend[trend.length - 1]?.data);
  const hasData = $derived(!!latestBio || athleteStore.readiness > 0);
  const history = $derived(trend.map(t => t.score));
  const days = $derived(trend.map(t => t.day));

  const factors = $derived(latestBio ? [
    { label: 'HRV', value: latestBio.hrv_rmssd, unit: 'ms', score: Math.min(100, (latestBio.hrv_rmssd / 80) * 100), color: '#00C8A8', desc: 'Heart rate variability is a key indicator of autonomic balance.' },
    { label: 'Resting HR', value: latestBio.resting_hr, unit: 'bpm', score: Math.min(100, (60 / latestBio.resting_hr) * 100), color: '#4621FF', desc: 'Lower resting HR typically indicates better cardiovascular fitness.' },
    { label: 'Sleep Score', value: latestBio.sleep_score, unit: '%', score: latestBio.sleep_score, color: '#FFCB88', desc: 'Sleep quality based on duration and efficiency.' },
    { label: 'Blood Oxygen', value: latestBio.spo2_pct, unit: '%', score: latestBio.spo2_pct, color: '#4621FF', desc: 'SpO2 levels during sleep.' },
  ].filter(f => f.value) : []);

  let score = $derived(latestBio?.recovery_score || athleteStore.readiness);
  let color = $derived(score >= 75 ? '#00C8A8' : score >= 50 ? '#FFCB88' : '#F07178');
  let label = $derived(score >= 75 ? 'Recovered' : score >= 50 ? 'Moderate' : 'Fatigued');
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Today · {format(new Date(), 'MMM d')}</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Recovery</h1>
  </div>

  {#if !isConnected}
    <EmptyState 
      title="No Recovery Data" 
      message="Connect WHOOP, Garmin, or Apple Health to see your recovery analysis."
    />
  {:else if !hasData}
    <EmptyState 
      title="Waiting for Sync" 
      message="We're waiting for your biometric data to compute your recovery score."
      icon="⏳"
    />
  {:else}
    <!-- Main gauge card -->
    <Card style="background: linear-gradient(135deg, rgba(0,200,168,0.12), rgba(70,33,255,0.08)); border-color: rgba(0,200,168,0.25);">
      <div class="flex items-center gap-2">
        <div class="w-[140px] shrink-0 flex justify-center items-center">
          <ScoreGauge value={score} />
        </div>
        <div class="flex-1 pl-2">
          <div class="flex items-center gap-2 mb-1.5">
            <span class="text-[20px] font-bold" style="color: {color}">{label}</span>
          </div>
          <p class="text-xs text-text1 leading-relaxed mb-2.5">
            {score >= 75 ? 'Your body is well-rested and ready for high-intensity training.' : 
             score >= 50 ? 'You have moderate recovery. Consider a balanced session.' : 
             'Recovery is low. Prioritize rest or very light activity today.'}
          </p>
          <Tag color={color}>{score >= 75 ? 'READY FOR QUALITY EFFORT' : 'PROCEED WITH CAUTION'}</Tag>
        </div>
      </div>
    </Card>

    <!-- 7-day history -->
    {#if history.length > 0}
      <Card>
        <p class="text-[13px] font-semibold mb-3">7-Day Recovery Trend</p>
        <div class="flex gap-1.5 items-end h-[60px] mb-2">
          {#each history as v, i}
            {@const c = v >= 75 ? '#00C8A8' : v >= 50 ? '#FFCB88' : '#F07178'}
            {@const isToday = i === history.length - 1}
            <div class="flex-1 flex flex-col items-center gap-1">
              <span class="text-[9px] font-mono" style="color: {c}">{v}</span>
              <div class="w-full rounded-t-md transition-all duration-400 ease-out" 
                   style="background: {isToday ? c : c + '66'}; height: {(v / 100) * 52}px; box-shadow: {isToday ? `0 0 8px ${c}` : 'none'}"></div>
            </div>
          {/each}
        </div>
        <div class="flex justify-between">
          {#each days as d, i}
            <span class="flex-1 text-center text-[9px] font-mono {i === days.length - 1 ? 'text-text0' : 'text-text2'}">{d}</span>
          {/each}
        </div>
      </Card>
    {/if}

    <!-- Contributing factors -->
    {#if factors.length > 0}
      <Card>
        <p class="text-[13px] font-semibold mb-3">Contributing Factors</p>
        <div class="flex flex-col gap-0">
          {#each factors as f, i}
            <div class="py-3 {i < factors.length - 1 ? 'border-b border-border' : ''}">
              <div class="flex items-center gap-2.5">
                <div class="flex-1">
                  <div class="flex justify-between mb-1.5">
                    <span class="text-xs font-semibold">{f.label}</span>
                    <div class="flex gap-2 items-center">
                      <span class="text-[12px] font-bold font-mono" style="color: {f.color}">
                        {f.value}<span class="text-[9px] font-normal text-text2 ml-0.5">{f.unit}</span>
                      </span>
                    </div>
                  </div>
                  <div class="h-1 bg-glass2 rounded-sm overflow-hidden mb-1.5">
                    <div class="h-full rounded-sm" style="width: {f.score}%; background: {f.color}"></div>
                  </div>
                  <p class="text-[10px] text-text2 leading-relaxed">{f.desc}</p>
                </div>
              </div>
            </div>
          {/each}
        </div>
      </Card>
    {/if}

    <!-- ASTRAPE insight -->
    <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent); border-color: rgba(70,33,255,0.25);">
      <p class="text-[13px] font-semibold mb-1.5">ASTRAPE Recommendation</p>
      <p class="text-xs text-text1 leading-relaxed">
        {score >= 75 ? 'Optimal window detected. You can handle high training stress today.' : 
         score >= 50 ? 'Moderate physiological state. Maintain plan but monitor perceived exertion.' : 
         'Systemic fatigue detected. Recommend reducing intensity or taking an extra rest day.'}
      </p>
    </Card>

    <!-- Calculation Methodology -->
    <div class="px-1 mt-4 mb-6">
      <p class="text-[11px] text-text2 font-mono uppercase tracking-[0.05em] mb-3">Calculation Methodology</p>
      <div class="flex flex-col gap-4">
        <div class="flex gap-3">
          <div class="w-1 h-auto bg-teal rounded-full"></div>
          <div>
            <p class="text-xs font-semibold mb-0.5">HRV Balance (45%)</p>
            <p class="text-[10px] text-text2 leading-relaxed">We compare your current RMSSD against your 30-day rolling baseline. A higher HRV indicates a dominant parasympathetic nervous system (Rest & Digest).</p>
          </div>
        </div>
        <div class="flex gap-3">
          <div class="w-1 h-auto bg-blue rounded-full"></div>
          <div>
            <p class="text-xs font-semibold mb-0.5">Cardiac Efficiency (25%)</p>
            <p class="text-[10px] text-text2 leading-relaxed">Derived from your resting heart rate. Deviations below your baseline improve your score, while elevations indicate cardiovascular strain.</p>
          </div>
        </div>
        <div class="flex gap-3">
          <div class="w-1 h-auto bg-amber rounded-full"></div>
          <div>
            <p class="text-xs font-semibold mb-0.5">Sleep Integrity (30%)</p>
            <p class="text-[10px] text-text2 leading-relaxed">A composite of sleep duration and quality (REM + Deep). Consistent sleep cycles are the primary engine of physiological repair.</p>
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>
