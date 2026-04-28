<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';

  let settings = $state(athleteStore.profile?.settings?.privacy || {
    share_activity: false,
    share_metrics: false,
    public_profile: false,
    data_training: true
  });
  let saving = $state(false);

  function goBack() {
    goto('/profile');
  }

  async function handleSave() {
    saving = true;
    const currentSettings = athleteStore.profile?.settings || {};
    const success = await api.patch('/v1/athlete/profile', {
      settings: {
        ...currentSettings,
        privacy: settings
      }
    });

    if (success) {
      await athleteStore.fetchAll();
      goBack();
    } else {
      alert('Failed to save privacy settings.');
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
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Privacy</h1>
    </div>
  </div>

  <div class="flex flex-col gap-3 mt-2">
    <Card>
      <div class="flex flex-col gap-5">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-[13px] font-medium">Public Profile</p>
            <p class="text-[10px] text-text2">Allow other athletes to find you</p>
          </div>
          <button class="w-10 h-5 rounded-full transition-colors relative {settings.public_profile ? 'bg-blue' : 'bg-glass2 border border-border'}" onclick={() => settings.public_profile = !settings.public_profile}>
            <div class="absolute top-0.5 {settings.public_profile ? 'right-0.5' : 'left-0.5'} w-4 h-4 rounded-full bg-white transition-all shadow-sm"></div>
          </button>
        </div>

        <div class="flex items-center justify-between">
          <div>
            <p class="text-[13px] font-medium">Share Metrics</p>
            <p class="text-[10px] text-text2">Allow sharing HRV/Sleep in club feeds</p>
          </div>
          <button class="w-10 h-5 rounded-full transition-colors relative {settings.share_metrics ? 'bg-blue' : 'bg-glass2 border border-border'}" onclick={() => settings.share_metrics = !settings.share_metrics}>
            <div class="absolute top-0.5 {settings.share_metrics ? 'right-0.5' : 'left-0.5'} w-4 h-4 rounded-full bg-white transition-all shadow-sm"></div>
          </button>
        </div>

        <div class="flex items-center justify-between">
          <div>
            <p class="text-[13px] font-medium">Model Training</p>
            <p class="text-[10px] text-text2">Use anonymized data to improve AI</p>
          </div>
          <button class="w-10 h-5 rounded-full transition-colors relative {settings.data_training ? 'bg-blue' : 'bg-glass2 border border-border'}" onclick={() => settings.data_training = !settings.data_training}>
            <div class="absolute top-0.5 {settings.data_training ? 'right-0.5' : 'left-0.5'} w-4 h-4 rounded-full bg-white transition-all shadow-sm"></div>
          </button>
        </div>
      </div>
    </Card>

    <button onclick={handleSave} disabled={saving} class="w-full py-3.5 bg-blue text-white font-semibold rounded-xl hover:bg-[#3d1ae6] transition-colors mt-2 disabled:opacity-50">
      {saving ? 'Saving...' : 'Save Settings'}
    </button>
  </div>
</div>
