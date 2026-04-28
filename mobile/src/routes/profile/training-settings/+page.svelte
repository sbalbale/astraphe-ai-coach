<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import SelectMenu from '$lib/components/SelectMenu.svelte';
  import { goto } from '$app/navigation';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { onMount } from 'svelte';

  type Units = 'metric' | 'imperial';
  const normalizeUnits = (value: unknown): Units =>
    typeof value === 'string' && value.toLowerCase().includes('imperial') ? 'imperial' : 'metric';

  let maxHR = $state(185);
  let ftp = $state(280);
  let pace = $state('5:00');
  let sport = $state('Running');
  let units = $state<Units>('metric');
  let initialized = $state(false);
  let saving = $state(false);

  const sportOptions = [
    { value: 'Triathlon', label: 'Triathlon' },
    { value: 'Running', label: 'Running' },
    { value: 'Cycling', label: 'Cycling' },
    { value: 'Rowing', label: 'Rowing' }
  ];

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
    } catch {
      // ignore
    }

    if (initialized) return;
    maxHR = athleteStore.profile?.max_hr ?? 185;
    ftp = athleteStore.profile?.ftp_watts ?? 280;
    pace = athleteStore.profile?.threshold_pace || '5:00';
    sport = athleteStore.profile?.sport_focus?.[0] || 'Running';
    units = normalizeUnits((athleteStore.profile as any)?.measurement_units);
    initialized = true;
  });

  function goBack() {
    goto('/profile');
  }

  async function handleSave(e: Event) {
    e.preventDefault();
    saving = true;
    const success = await athleteStore.updateProfile({
      max_hr: maxHR,
      ftp_watts: ftp,
      threshold_pace: pace,
      sport_focus: [sport.toLowerCase()],
      measurement_units: units
    });
    saving = false;
    if (success) goBack();
  }
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center gap-3">
    <button onclick={goBack} class="w-8 h-8 flex items-center justify-center bg-glass border border-border rounded-lg text-text2 hover:text-text0 transition-colors cursor-pointer">
      ←
    </button>
    <div>
      <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Account</p>
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Settings</h1>
    </div>
  </div>

  <form onsubmit={handleSave} class="flex flex-col gap-3 mt-2">
    <Card>
      <p class="text-[13px] font-semibold mb-3">Primary Focus</p>
      <div class="flex flex-col gap-4">
        <div>
          <label for="sport" class="block text-[11px] text-text2 mb-1">Main Sport</label>
          <SelectMenu
            id="sport"
            bind:value={sport}
            options={sportOptions}
            ariaLabel="Main Sport"
            buttonClass="w-full p-2.5 pr-2 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
          />
        </div>
        <div>
          <label for="units" class="block text-[11px] text-text2 mb-1">Measurement Units</label>
          <div class="flex p-1 bg-glass2 rounded-lg border border-border">
            <button type="button" class="flex-1 py-1.5 text-xs rounded-md transition-colors {units === 'metric' ? 'bg-blue text-white' : 'text-text2 hover:text-text0'}" onclick={() => units = 'metric'}>Metric</button>
            <button type="button" class="flex-1 py-1.5 text-xs rounded-md transition-colors {units === 'imperial' ? 'bg-blue text-white' : 'text-text2 hover:text-text0'}" onclick={() => units = 'imperial'}>Imperial</button>
          </div>
        </div>
      </div>
    </Card>

    <Card>
      <p class="text-[13px] font-semibold mb-3">Thresholds</p>
      <div class="flex flex-col gap-4">
        <div class="flex items-center justify-between gap-3">
          <div class="flex-1">
            <label for="maxhr" class="block text-[11px] text-text2 mb-1">Max HR (bpm)</label>
            <input id="maxhr" type="number" bind:value={maxHR} class="w-full p-2 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-red" />
          </div>
          <div class="flex-1">
            <label for="ftp" class="block text-[11px] text-text2 mb-1">Cycling FTP (W)</label>
            <input id="ftp" type="number" bind:value={ftp} class="w-full p-2 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-[#4621FF]" />
          </div>
        </div>
        <div>
          <label for="pace" class="block text-[11px] text-text2 mb-1">Threshold Pace (/km)</label>
          <input id="pace" type="text" bind:value={pace} class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-teal" />
        </div>
      </div>
    </Card>

    <button type="submit" disabled={saving} class="w-full py-3.5 bg-blue text-white font-semibold rounded-xl hover:bg-[#3d1ae6] transition-colors mt-2 disabled:opacity-50">
      {saving ? 'Saving...' : 'Save Configuration'}
    </button>
  </form>
</div>
