<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import LineChart from '$lib/components/charts/LineChart.svelte';
  import DonutChart from '$lib/components/charts/DonutChart.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';

  let metric = $state('load');
  const tabs = ['load', 'pace', 'zones', 'history'];
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Performance</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Analysis</h1>
  </div>

  <!-- Metric Tabs -->
  <div class="flex gap-1.5 overflow-x-auto pb-0.5 shrink-0">
    {#each tabs as tab}
      <Pill active={metric === tab} onclick={() => metric = tab}>
        {tab.charAt(0).toUpperCase() + tab.slice(1)}
      </Pill>
    {/each}
  </div>

  {#if metric === 'load'}
    <div class="grid grid-cols-2 gap-2.5">
      <Card style="background: linear-gradient(135deg, rgba(0,200,168,0.12), transparent);">
        <MetricBadge label="Fitness (CTL)" value={athleteStore.ctl} color="var(--teal)" sub="↑ 7 pts / 4 weeks" />
      </Card>
      <Card style="background: linear-gradient(135deg, rgba(255,203,136,0.12), transparent);">
        <MetricBadge label="Fatigue (ATL)" value={athleteStore.atl} color="var(--amber)" sub="↓ 57 pts from peak" />
      </Card>
      <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);">
        <MetricBadge label="Form (TSB)" value={athleteStore.tsb > 0 ? `+${athleteStore.tsb}` : athleteStore.tsb} color="#4621FF" sub="Optimal race window" />
      </Card>
      <Card style="background: linear-gradient(135deg, rgba(240,113,120,0.12), transparent);">
        <MetricBadge label="Weekly TSS" value={389} color="var(--red)" sub="↑ 12% vs last week" />
      </Card>
    </div>
    
    {#if athleteStore.metrics?.trainingLoadData}
      <Card>
        <p class="text-[13px] font-semibold mb-3">7-Day Load</p>
        <MultiLineChart data={athleteStore.metrics.trainingLoadData} height={120} />
      </Card>
    {/if}
    
    <Card>
      <p class="text-[13px] font-semibold mb-1">AI Insight</p>
      <p class="text-xs text-text1 leading-relaxed p-2.5 bg-blue-dim rounded-xl border-l-2 border-blue">
        Your CTL trajectory is ideal — 7pt gain over 4 weeks. TSB of +28 means you're primed. I recommend a hard effort this week before resuming your build block.
      </p>
    </Card>
  {/if}

  {#if metric === 'pace'}
    {#if athleteStore.metrics?.paceData}
      <Card>
        <p class="text-[13px] font-semibold mb-1">Last Long Run — Pace/km</p>
        <p class="text-[11px] text-text2 mb-3">Apr 24 · 10km · avg 5:38/km</p>
        <LineChart data={athleteStore.metrics.paceData} yKey="pace" color="#4621FF" height={100} labels={athleteStore.metrics.paceData.map((d: any) => d.dist > 0 ? d.dist+'km' : '')} />
      </Card>
    {/if}
    <div class="grid grid-cols-3 gap-2.5">
      <Card style="padding: 12px 14px;">
        <MetricBadge label="Avg Pace" value="5:38" unit="/km" color="#4621FF" />
      </Card>
      <Card style="padding: 12px 14px;">
        <MetricBadge label="Best km" value="5:12" unit="/km" color="var(--teal)" />
      </Card>
      <Card style="padding: 12px 14px;">
        <MetricBadge label="Avg HR" value="148" unit="bpm" color="var(--red)" />
      </Card>
    </div>
    <Card>
      <p class="text-[13px] font-semibold mb-1">Running Economy</p>
      <p class="text-xs text-text1 leading-relaxed p-2.5 bg-teal-dim rounded-xl border-l-2 border-teal">
        Pace/HR ratio improved 3.2% vs last month. Your aerobic efficiency is trending up — a strong indicator of fitness adaptation.
      </p>
    </Card>
  {/if}

  {#if metric === 'zones'}
    {#if athleteStore.metrics?.zoneData}
      <Card>
        <div class="flex gap-5 items-center">
          <DonutChart data={athleteStore.metrics.zoneData} size={100} />
          <div class="flex-1 flex flex-col gap-2">
            {#each athleteStore.metrics.zoneData as z}
              <div class="flex items-center gap-2">
                <div class="w-2 h-2 rounded-full shrink-0" style="background: {z.color}"></div>
                <span class="text-xs text-text1 flex-1">{z.zone}</span>
                <div class="flex-[2] h-1 bg-glass2 rounded overflow-hidden">
                  <div class="h-full rounded" style="width: {z.pct}%; background: {z.color}"></div>
                </div>
                <span class="text-[11px] font-mono w-8 text-right" style="color: {z.color}">{z.pct}%</span>
              </div>
            {/each}
          </div>
        </div>
      </Card>
    {/if}
    <Card style="background: linear-gradient(135deg, rgba(0,200,168,0.1), transparent);">
      <p class="text-[13px] font-semibold mb-2">Distribution Score</p>
      <div class="flex items-center gap-3">
        <RadialProgress value={84} max={100} size={56} color="var(--teal)" label="84" />
        <div>
          <p class="text-[14px] font-semibold text-teal">Excellent</p>
          <p class="text-xs text-text1 leading-relaxed">Polarized 80/20 model. Zone 2 at 42% — on point. Reduce Z3 slightly next week.</p>
        </div>
      </div>
    </Card>
  {/if}

  {#if metric === 'history'}
    <div class="flex flex-col gap-2.5">
      {#if athleteStore.plan?.workouts}
        {#each athleteStore.plan.workouts as w}
          <Card style="padding: 12px 14px;">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl shrink-0 flex items-center justify-center text-[18px]
                {w.type === 'Run' ? 'bg-blue-dim border border-blue-glow' : 
                 w.type === 'Bike' ? 'bg-teal-dim border border-[rgba(0,200,168,0.3)]' : 
                 'bg-amber-dim border border-[rgba(255,203,136,0.3)]'}">
                {w.type === 'Run' ? '🏃' : w.type === 'Bike' ? '🚴' : '💪'}
              </div>
              <div class="flex-1">
                <p class="text-[13px] font-semibold">{w.title}</p>
                <p class="text-[11px] text-text2">{w.date} · {w.duration}</p>
              </div>
              <div class="text-right">
                <p class="text-[16px] font-bold {w.load > 75 ? 'text-red' : w.load > 55 ? 'text-amber' : 'text-teal'}">{w.load}</p>
                <p class="text-[9px] text-text2 font-mono">TSS</p>
              </div>
            </div>
          </Card>
        {/each}
      {/if}
    </div>
  {/if}
</div>
