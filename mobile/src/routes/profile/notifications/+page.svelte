<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';

  let settings = $state(athleteStore.profile?.settings?.notifications || {
    push: true,
    email: false,
    coach_insights: true,
    weekly_summary: true,
    load_alerts: true
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
        notifications: settings
      }
    });

    if (success) {
      await athleteStore.fetchAll();
      goBack();
    } else {
      alert('Failed to save notification settings.');
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
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Notifications</h1>
    </div>
  </div>

  <div class="flex flex-col gap-3 mt-2">
    <Card>
      <div class="flex flex-col gap-5">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-[13px] font-medium">Push Notifications</p>
            <p class="text-[10px] text-text2">Alerts for readiness and load</p>
          </div>
          <button class="w-10 h-5 rounded-full transition-colors relative {settings.push ? 'bg-blue' : 'bg-glass2 border border-border'}" onclick={() => settings.push = !settings.push}>
            <div class="absolute top-0.5 {settings.push ? 'right-0.5' : 'left-0.5'} w-4 h-4 rounded-full bg-white transition-all shadow-sm"></div>
          </button>
        </div>

        <div class="flex items-center justify-between">
          <div>
            <p class="text-[13px] font-medium">Email Updates</p>
            <p class="text-[10px] text-text2">Weekly training summaries</p>
          </div>
          <button class="w-10 h-5 rounded-full transition-colors relative {settings.email ? 'bg-blue' : 'bg-glass2 border border-border'}" onclick={() => settings.email = !settings.email}>
            <div class="absolute top-0.5 {settings.email ? 'right-0.5' : 'left-0.5'} w-4 h-4 rounded-full bg-white transition-all shadow-sm"></div>
          </button>
        </div>

        <div class="flex items-center justify-between">
          <div>
            <p class="text-[13px] font-medium">AI Coach Insights</p>
            <p class="text-[10px] text-text2">Daily training recommendations</p>
          </div>
          <button class="w-10 h-5 rounded-full transition-colors relative {settings.coach_insights ? 'bg-blue' : 'bg-glass2 border border-border'}" onclick={() => settings.coach_insights = !settings.coach_insights}>
            <div class="absolute top-0.5 {settings.coach_insights ? 'right-0.5' : 'left-0.5'} w-4 h-4 rounded-full bg-white transition-all shadow-sm"></div>
          </button>
        </div>
      </div>
    </Card>

    <button onclick={handleSave} disabled={saving} class="w-full py-3.5 bg-blue text-white font-semibold rounded-xl hover:bg-[#3d1ae6] transition-colors mt-2 disabled:opacity-50">
      {saving ? 'Saving...' : 'Save Preferences'}
    </button>
  </div>
</div>
