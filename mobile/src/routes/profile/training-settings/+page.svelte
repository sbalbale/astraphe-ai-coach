<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';

  let maxHR = $state(athleteStore.profile?.max_hr || 185);
  let thresholdHR = $state(athleteStore.profile?.threshold_hr || 161);
  let ftp = $state(athleteStore.profile?.ftp_watts || 280);
  let pace = $state(athleteStore.profile?.threshold_pace || '5:00');
  let sport = $state(athleteStore.profile?.primary_sport || 'Triathlon');
  let units = $state('Metric');
  let saving = $state(false);

  function goBack() {
    goto('/profile');
  }

  async function handleSave() {
    saving = true;
    const success = await api.patch('/v1/athlete/profile', {
      max_hr: maxHR,
      threshold_hr: thresholdHR,
      ftp_watts: ftp,
      threshold_pace: pace,
      primary_sport: sport
    });

    if (success) {
      await athleteStore.fetchAll(); // Refresh store to update zones etc.
      goBack();
    } else {
      alert('Failed to save training settings.');
    }
    saving = false;
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

  <form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="flex flex-col gap-3 mt-2">
    <Card>
      <p class="text-[13px] font-semibold mb-3">Primary Focus</p>
      <div class="flex flex-col gap-4">
        <div>
          <label for="sport" class="block text-[11px] text-text2 mb-1">Main Sport</label>
          <select id="sport" bind:value={sport} class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue appearance-none">
            <option>Triathlon</option>
            <option>Running</option>
            <option>Cycling</option>
            <option>Rowing</option>
          </select>
        </div>
        <div>
          <label for="units" class="block text-[11px] text-text2 mb-1">Measurement Units</label>
          <div class="flex p-1 bg-glass2 rounded-lg border border-border">
            <button type="button" class="flex-1 py-1.5 text-xs rounded-md transition-colors {units === 'Metric' ? 'bg-blue text-white' : 'text-text2 hover:text-text0'}" onclick={() => units = 'Metric'}>Metric</button>
            <button type="button" class="flex-1 py-1.5 text-xs rounded-md transition-colors {units === 'Imperial' ? 'bg-blue text-white' : 'text-text2 hover:text-text0'}" onclick={() => units = 'Imperial'}>Imperial</button>
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
            <label for="thr" class="block text-[11px] text-text2 mb-1">Threshold HR</label>
            <input id="thr" type="number" bind:value={thresholdHR} class="w-full p-2 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue" />
          </div>
        </div>
        <div class="flex items-center justify-between gap-3">
          <div class="flex-1">
            <label for="ftp" class="block text-[11px] text-text2 mb-1">Cycling FTP (W)</label>
            <input id="ftp" type="number" bind:value={ftp} class="w-full p-2 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-[#4621FF]" />
          </div>
          <div class="flex-1">
            <label for="pace" class="block text-[11px] text-text2 mb-1">Threshold Pace (/km)</label>
            <input id="pace" type="text" bind:value={pace} class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-teal" />
          </div>
        </div>
      </div>
    </Card>

    <button type="submit" disabled={saving} class="w-full py-3.5 bg-blue text-white font-semibold rounded-xl hover:bg-[#3d1ae6] transition-colors mt-2 disabled:opacity-50">
      {saving ? 'Saving...' : 'Save Configuration'}
    </button>
  </form>
</div>
