<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';

  let sport = $state('all');
  let editZone: number | null = $state(null);

  const hasProfile = $derived(!!athleteStore.profile);
  
  // Fallbacks if profile not loaded
  const maxHR = $derived(athleteStore.profile?.max_hr || 190);
  const restingHR = $derived(athleteStore.profile?.resting_hr || 50);
  const hrr = $derived(maxHR - restingHR);

  const hrZones = $derived([
    { zone: 1, name: 'Recovery', lo: Math.round(restingHR + hrr * 0.5), hi: Math.round(restingHR + hrr * 0.6), color: '#4621FF', desc: 'Active recovery. Minimal stress.' },
    { zone: 2, name: 'Aerobic', lo: Math.round(restingHR + hrr * 0.6) + 1, hi: Math.round(restingHR + hrr * 0.7), color: '#00C8A8', desc: 'Endurance. Optimized for fat metabolism.' },
    { zone: 3, name: 'Tempo', lo: Math.round(restingHR + hrr * 0.7) + 1, hi: Math.round(restingHR + hrr * 0.8), color: '#FFCB88', desc: 'Moderate. Improving aerobic capacity.' },
    { zone: 4, name: 'Threshold', lo: Math.round(restingHR + hrr * 0.8) + 1, hi: Math.round(restingHR + hrr * 0.9), color: '#F07178', desc: 'Hard. Lactate threshold development.' },
    { zone: 5, name: 'VO2max', lo: Math.round(restingHR + hrr * 0.9) + 1, hi: maxHR, color: '#FF4791', desc: 'Max effort. Building peak power.' },
  ]);
  
  let zones = $derived(hrZones);

  
  // Filter activities
  const sportOptions = [
    { id: 'all', label: '🌍 Overview' },
    { id: 'run', label: '🏃 Run' },
    { id: 'bike', label: '🚴 Bike' },
    { id: 'swim', label: '🏊 Swim' },
    { id: 'gym', label: '💪 Gym' },
    { id: 'rowing', label: '🚣 Row' },
    { id: 'other', label: '🏁 Other' }
  ];

  const filteredWorkouts = $derived(
    sport === 'all' 
      ? athleteStore.workouts 
      : athleteStore.workouts.filter(w => w.sport?.toLowerCase() === sport)
  );

  const hasWorkouts = $derived(filteredWorkouts.length > 0);

  // Memoize distribution calculation
  const distribution = $derived.by(() => {
    if (!hasWorkouts) return [0, 0, 0, 0, 0];
    
    let totals = [0, 0, 0, 0, 0];
    let validCount = 0;
    
    // Use a single pass over workouts
    for (let i = 0; i < filteredWorkouts.length; i++) {
      const w = filteredWorkouts[i];
      if (w.hr_zone_1_pct !== null) {
        totals[0] += (w.hr_zone_1_pct || 0);
        totals[1] += (w.hr_zone_2_pct || 0);
        totals[2] += (w.hr_zone_3_pct || 0);
        totals[3] += (w.hr_zone_4_pct || 0);
        totals[4] += (w.hr_zone_5_pct || 0);
        validCount++;
      }
    }
    
    if (validCount === 0) return [0, 0, 0, 0, 0];
    
    const count = validCount;
    
    // Normalize to sum to exactly 100%
    let rounded = totals.map(t => Math.round(t / count));
    let sum = rounded.reduce((a, b) => a + b, 0);
    
    if (sum !== 100 && sum > 0) {
      // Adjust the largest zone to make it exactly 100%
      let maxIdx = rounded.indexOf(Math.max(...rounded));
      rounded[maxIdx] += (100 - sum);
    }
    
    return rounded;
  });
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Heart Rate & Power</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Zones</h1>
  </div>

  {#if athleteStore.loading && !athleteStore.initialLoadDone}
    <div class="flex-1 flex flex-col items-center justify-center py-20 opacity-40">
      <div class="w-6 h-6 border-2 border-blue border-t-transparent rounded-full animate-spin mb-4"></div>
      <p class="text-[10px] font-mono tracking-widest uppercase">Syncing Biometrics...</p>
    </div>
  {:else if !hasProfile}
    <EmptyState 
      title="No Profile Data" 
      message="Complete your athlete profile to compute personalized training zones."
      actionLabel="Go to Profile"
      icon="👤"
    />
  {:else}
    <!-- Sport toggle -->
    <div class="flex gap-1.5 overflow-x-auto pb-1 no-scrollbar shrink-0">
      {#each sportOptions as s}
        <Pill active={sport === s.id} onclick={() => sport = s.id}>
          {s.label}
        </Pill>
      {/each}
    </div>

    <!-- Anchor values -->
    <div class="grid grid-cols-2 gap-2.5">
      <Card style="background: linear-gradient(135deg, rgba(240,113,120,0.12), transparent);">
        <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em] mb-1">Max Heart Rate</p>
        <p class="text-[26px] font-bold text-red tracking-[-0.02em] leading-tight">
          {maxHR}
          <span class="text-[13px] font-normal text-text2 ml-1">bpm</span>
        </p>
        <p class="text-[10px] text-text2 mt-0.5">Profile Baseline</p>
      </Card>
      <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);">
        <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em] mb-1">Resting Heart Rate</p>
        <p class="text-[26px] font-bold text-[#4621FF] tracking-[-0.02em] leading-tight">
          {restingHR}
          <span class="text-[13px] font-normal text-text2 ml-1">bpm</span>
        </p>
        <p class="text-[10px] text-text2 mt-0.5">HRR: {hrr} bpm</p>
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
                  <span class="text-[11px] font-mono" style="color: {z.color}">{z.lo}–{z.hi} bpm</span>
                </div>
                <div class="h-1.25 bg-glass2 rounded overflow-hidden">
                  <div class="h-full rounded" 
                       style="width: {((z.hi - z.lo) / maxHR) * 100}%; margin-left: {(z.lo / maxHR) * 100}%; background: {z.color};"></div>
                </div>
              </div>
            </div>
            {#if editZone === i}
              <div class="ml-[38px] p-2 px-2.5 bg-glass rounded-lg border-l-2 mt-1 w-[calc(100%-38px)]" style="border-color: {z.color}">
                <p class="text-[11px] text-text1 leading-relaxed mb-2">{z.desc}</p>
              </div>
            {/if}
          </button>
        {/each}
      </div>
    </Card>

    <!-- Weekly distribution -->
    <Card>
      <p class="text-[13px] font-semibold mb-3">Time in Zones ({sport === 'all' ? 'All Activities' : sport.toUpperCase()})</p>
      {#if !hasWorkouts}
        <div class="flex flex-col items-center justify-center py-6 opacity-60">
          <p class="text-xs text-text2">No training distribution data for this selection.</p>
        </div>
      {:else}
        <div class="flex flex-col gap-3">
          <div class="h-6 w-full flex rounded-lg overflow-hidden border border-border/50">
            {#each distribution as pct, i}
              {@const colors = ['#4621FF', '#00C8A8', '#FFCB88', '#F07178', '#FF4791']}
              <div class="h-full transition-all duration-500" style="width: {pct}%; background: {colors[i]};" title="Z{i+1}: {pct}%"></div>
            {/each}
          </div>
          
          <div class="grid grid-cols-2 gap-x-4 gap-y-2">
            {#each distribution as pct, i}
              {@const colors = ['#4621FF', '#00C8A8', '#FFCB88', '#F07178', '#FF4791']}
              {@const labels = ['Z1 Recovery', 'Z2 Aerobic', 'Z3 Tempo', 'Z4 Threshold', 'Z5 Anaerobic']}
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1.5">
                  <div class="w-2 h-2 rounded-full" style="background: {colors[i]}"></div>
                  <span class="text-[10px] text-text1">{labels[i]}</span>
                </div>
                <span class="text-[10px] font-mono font-bold" style="color: {colors[i]}">{pct}%</span>
              </div>
            {/each}
          </div>
          
          <p class="text-[10px] text-text2 italic mt-1 text-center">
            Average distribution across {filteredWorkouts.length} {sport === 'all' ? 'activities' : sport} sessions.
          </p>
        </div>
      {/if}
    </Card>
  {/if}
</div>
