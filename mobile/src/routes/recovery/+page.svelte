<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import ScoreGauge from '$lib/components/charts/ScoreGauge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';

  const history = [62, 71, 58, 80, 74, 69, 78];
  const days = ['M','T','W','T','F','S','S'];

  const factors = [
    { label: 'HRV', value: 78, unit: 'ms', score: 88, delta: '+6', color: '#00C8A8', desc: 'Above your 30-day baseline of 71ms. Strong parasympathetic response.' },
    { label: 'Resting HR', value: 52, unit: 'bpm', score: 82, delta: '-2', color: '#4621FF', desc: '2 bpm below baseline. Low resting HR indicates good cardiac efficiency.' },
    { label: 'Sleep Quality', value: 94, unit: '%', score: 91, delta: '+7', color: '#FFCB88', desc: '7.5h with 94% quality. Deep sleep at 22% — excellent for recovery.' },
    { label: 'Prior Load', value: 38, unit: 'TSS', score: 72, delta: '↓57', color: '#F07178', desc: 'Yesterday was a recovery day. Acute load dropped 57 pts from peak.' },
    { label: 'Body Temp', value: '+0.1', unit: '°F', score: 95, delta: '~', color: '#00C8A8', desc: 'Skin temp deviation minimal. No signs of illness or overheating.' },
    { label: 'SPO2', value: 98, unit: '%', score: 96, delta: '~', color: '#4621FF', desc: 'Blood oxygen within normal range all night.' },
  ];

  let score = $derived(athleteStore.readiness);
  let color = $derived(score >= 75 ? '#00C8A8' : score >= 50 ? '#FFCB88' : '#F07178');
  let label = $derived(score >= 75 ? 'Recovered' : score >= 50 ? 'Moderate' : 'Fatigued');
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Today · Apr 26</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Recovery</h1>
  </div>

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
        <p class="text-xs text-text1 leading-relaxed mb-2.5">Your body has absorbed last week's load. High HRV and quality sleep put you in the green.</p>
        <Tag color={color}>READY FOR QUALITY EFFORT</Tag>
      </div>
    </div>
  </Card>

  <!-- 7-day history -->
  <Card>
    <p class="text-[13px] font-semibold mb-3">7-Day Recovery Trend</p>
    <div class="flex gap-1.5 items-end h-[60px] mb-2">
      {#each history as v, i}
        {@const c = v >= 75 ? '#00C8A8' : v >= 50 ? '#FFCB88' : '#F07178'}
        {@const isToday = i === 6}
        <div class="flex-1 flex flex-col items-center gap-1">
          <span class="text-[9px] font-mono" style="color: {c}">{v}</span>
          <div class="w-full rounded-t-md transition-all duration-400 ease-out" 
               style="background: {isToday ? c : c + '66'}; height: {(v / 100) * 52}px; box-shadow: {isToday ? `0 0 8px ${c}` : 'none'}"></div>
        </div>
      {/each}
    </div>
    <div class="flex justify-between">
      {#each days as d, i}
        <span class="flex-1 text-center text-[9px] font-mono {i === 6 ? 'text-text0' : 'text-text2'}">{d}</span>
      {/each}
    </div>
  </Card>

  <!-- Contributing factors -->
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
                  <span class="text-[11px] font-mono {f.delta.startsWith('+') ? 'text-teal' : f.delta === '~' ? 'text-text2' : 'text-amber'}">{f.delta}</span>
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

  <!-- ASTRAPE insight -->
  <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent); border-color: rgba(70,33,255,0.25);">
    <p class="text-[13px] font-semibold mb-1.5">ASTRAPE Recommendation</p>
    <p class="text-xs text-text1 leading-relaxed">Score of 78 with HRV peaking — this is your optimal window. Attack Tuesday's VO2max session with full confidence. Tomorrow: keep it to Z2 regardless of how good you feel.</p>
  </Card>
</div>
