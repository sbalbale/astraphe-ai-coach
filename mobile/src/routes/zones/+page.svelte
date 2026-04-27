<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';

  let sport = $state('run');
  let editZone: number | null = $state(null);

  // Fallbacks if profile not loaded
  const maxHR = $derived(athleteStore.profile?.max_hr || 185);
  const thresholdHR = $derived(athleteStore.profile?.threshold_hr || 161);
  const ftp = $derived(athleteStore.profile?.ftp_watts || 280);

  const runZones = $derived([
    { zone: 1, name: 'Recovery', lo: Math.round(maxHR * 0.6), hi: Math.round(maxHR * 0.7), color: '#4621FF', desc: 'Conversational pace. Full sentences easy.' },
    { zone: 2, name: 'Aerobic', lo: Math.round(maxHR * 0.7), hi: Math.round(maxHR * 0.8), color: '#00C8A8', desc: 'Nose breathing. Could talk in short sentences.' },
    { zone: 3, name: 'Tempo', lo: Math.round(maxHR * 0.8), hi: Math.round(maxHR * 0.87), color: '#FFCB88', desc: 'Comfortably hard. Only short phrases possible.' },
    { zone: 4, name: 'Threshold', lo: Math.round(maxHR * 0.87), hi: Math.round(maxHR * 0.93), color: '#F07178', desc: 'Hard effort. Only a few words per breath.' },
    { zone: 5, name: 'VO2max', lo: Math.round(maxHR * 0.93), hi: maxHR, color: '#FF4791', desc: 'Max effort. Unsustainable beyond ~8 min.' },
  ]);
  
  const bikeZones = $derived([
    { zone: 1, name: 'Active Recovery', lo: 0, hi: Math.round(ftp * 0.55), color: '#4621FF', desc: '<55% FTP. Very easy spinning.' },
    { zone: 2, name: 'Endurance', lo: Math.round(ftp * 0.55) + 1, hi: Math.round(ftp * 0.75), color: '#00C8A8', desc: '56–75% FTP. All-day sustainable.' },
    { zone: 3, name: 'Tempo', lo: Math.round(ftp * 0.75) + 1, hi: Math.round(ftp * 0.90), color: '#FFCB88', desc: '76–90% FTP. Moderate to hard.' },
    { zone: 4, name: 'Lactate', lo: Math.round(ftp * 0.90) + 1, hi: Math.round(ftp * 1.05), color: '#F07178', desc: '91–105% FTP. Very hard.' },
    { zone: 5, name: 'VO2max', lo: Math.round(ftp * 1.05) + 1, hi: Math.round(ftp * 1.20), color: '#FF4791', desc: '106–120% FTP. Severe.' },
  ]);

  const rowZones = $derived([
    { zone: 1, name: 'Steady State', lo: 0, hi: Math.round(ftp * 0.55), color: '#4621FF', desc: 'UT2. Low intensity endurance.' },
    { zone: 2, name: 'Endurance', lo: Math.round(ftp * 0.55) + 1, hi: Math.round(ftp * 0.70), color: '#00C8A8', desc: 'UT1. Building aerobic capacity.' },
    { zone: 3, name: 'AT (Anaerobic)', lo: Math.round(ftp * 0.70) + 1, hi: Math.round(ftp * 0.85), color: '#FFCB88', desc: 'Threshold work. Hard but controlled.' },
    { zone: 4, name: 'Transport', lo: Math.round(ftp * 0.85) + 1, hi: Math.round(ftp * 0.95), color: '#F07178', desc: 'High intensity. 2k pace intervals.' },
    { zone: 5, name: 'Anaerobic', lo: Math.round(ftp * 0.95) + 1, hi: Math.round(ftp * 1.10), color: '#FF4791', desc: 'Sprint / Max effort.' },
  ]);
  
  let zones = $derived(sport === 'run' ? runZones : sport === 'bike' ? bikeZones : rowZones);

  const weekTotals = [
    { label: 'Z1', mins: 82, color: '#4621FF' },
    { label: 'Z2', mins: 191, color: '#00C8A8' },
    { label: 'Z3', mins: 100, color: '#FFCB88' },
    { label: 'Z4', mins: 59, color: '#F07178' },
    { label: 'Z5', mins: 23, color: '#FF4791' },
  ];
  const totalMins = weekTotals.reduce((s, z) => s + z.mins, 0);
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Heart Rate & Power</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Zones</h1>
  </div>

  <!-- Sport toggle -->
  <div class="flex gap-1.5">
    {#each ['run', 'bike', 'rowing'] as s}
      <Pill active={sport === s} onclick={() => sport = s}>
        {s === 'run' ? '🏃 Running' : s === 'bike' ? '🚴 Cycling' : '🚣 Rowing'}
      </Pill>
    {/each}
  </div>

  <!-- Anchor values -->
  <div class="grid grid-cols-2 gap-2.5">
    <Card style="background: linear-gradient(135deg, rgba(240,113,120,0.12), transparent);">
      <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em] mb-1">{sport === 'run' ? 'Max HR' : 'FTP'}</p>
      <p class="text-[26px] font-bold text-red tracking-[-0.02em] leading-tight">
        {sport === 'run' ? maxHR : ftp}
        <span class="text-[13px] font-normal text-text2 ml-1">{sport === 'run' ? 'bpm' : 'W'}</span>
      </p>
      <p class="text-[10px] text-text2 mt-0.5">ASTRAPE Computed</p>
    </Card>
    <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);">
      <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em] mb-1">{sport === 'run' ? 'Threshold HR' : 'W/kg'}</p>
      <p class="text-[26px] font-bold text-[#4621FF] tracking-[-0.02em] leading-tight">
        {sport === 'run' ? thresholdHR : (ftp / (athleteStore.profile?.weight_kg || 75)).toFixed(1)}
        <span class="text-[13px] font-normal text-text2 ml-1">{sport === 'run' ? 'bpm' : 'w/kg'}</span>
      </p>
      <p class="text-[10px] text-text2 mt-0.5">{athleteStore.profile?.weight_kg || 75}kg body weight</p>
    </Card>
  </div>

  <!-- Zone Bars -->
  <Card>
    <p class="text-[13px] font-semibold mb-3.5">Zone Definitions</p>
    <div class="flex flex-col gap-2.5">
      {#each zones as z, i}
        <button 
          class="flex flex-col text-left bg-transparent border-none p-0 cursor-pointer w-full text-text0"
          onclick={() => editZone = editZone === i ? null : i}
        >
          <div class="flex items-center gap-2.5 mb-1.5 w-full">
            <div class="w-7 h-7 rounded-lg border flex items-center justify-center shrink-0" 
                 style="background: {z.color}20; border-color: {z.color}50;">
              <span class="text-[11px] font-bold font-mono" style="color: {z.color}">Z{z.zone}</span>
            </div>
            <div class="flex-1">
              <div class="flex justify-between items-center mb-1">
                <span class="text-[12px] font-semibold">{z.name}</span>
                <span class="text-[11px] font-mono" style="color: {z.color}">{z.lo}–{z.hi}{sport === 'run' ? ' bpm' : 'W'}</span>
              </div>
              <div class="h-1.25 bg-glass2 rounded overflow-hidden">
                <div class="h-full rounded" 
                     style="width: {((z.hi - z.lo) / (sport === 'run' ? maxHR : ftp * 1.2)) * 100}%; margin-left: {(z.lo / (sport === 'run' ? maxHR : ftp * 1.2)) * 100}%; background: {z.color};"></div>
              </div>
            </div>
          </div>
          {#if editZone === i}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="ml-[38px] p-2 px-2.5 bg-glass rounded-lg border-l-2 mt-1 w-[calc(100%-38px)]" style="border-color: {z.color}" onclick={(e) => e.stopPropagation()}>
              <p class="text-[11px] text-text1 leading-relaxed mb-2">{z.desc}</p>
              <div class="flex gap-2">
                <div class="flex-1">
                  <p class="text-[9px] text-text2 font-mono mb-1">LOW</p>
                  <input type="number" value={z.lo} class="w-full px-2 py-1.5 bg-glass2 border border-border rounded-md text-text0 text-[13px] font-mono outline-none focus:border-[var(--blue)] transition-colors" />
                </div>
                <div class="flex-1">
                  <p class="text-[9px] text-text2 font-mono mb-1">HIGH</p>
                  <input type="number" value={z.hi} class="w-full px-2 py-1.5 bg-glass2 border border-border rounded-md text-text0 text-[13px] font-mono outline-none focus:border-[var(--blue)] transition-colors" />
                </div>
              </div>
            </div>
          {/if}
        </button>
      {/each}
    </div>
  </Card>

  <!-- Weekly distribution -->
  <Card>
    <p class="text-[13px] font-semibold mb-3">This Week's Distribution</p>
    <div class="flex h-8 rounded-lg overflow-hidden gap-0.5 mb-3">
      {#each weekTotals as z}
        <div class="flex items-center justify-center" style="flex: {z.mins}; background: {z.color};">
          {#if z.mins > 30}
            <span class="text-[9px] font-mono text-black font-bold">{Math.round(z.mins / totalMins * 100)}%</span>
          {/if}
        </div>
      {/each}
    </div>
    <div class="flex flex-col gap-1.5">
      {#each weekTotals as z}
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full shrink-0" style="background: {z.color};"></div>
          <span class="text-[11px] text-text1 flex-1">{z.label}</span>
          <div class="flex-[3] h-1 bg-glass2 rounded-sm overflow-hidden">
            <div class="h-full rounded-sm" style="width: {(z.mins / totalMins) * 100}%; background: {z.color};"></div>
          </div>
          <span class="text-[10px] font-mono w-[38px] text-right" style="color: {z.color}">{z.mins}min</span>
        </div>
      {/each}
    </div>
    <div class="mt-3 p-2.5 bg-teal-dim rounded-xl border-l-2 border-teal">
      <p class="text-xs text-text1 leading-relaxed">Z2 at 42% — strong aerobic base work. Polarized model target met. Slight Z3 creep (22%) — keep easy days easy.</p>
    </div>
  </Card>
</div>
