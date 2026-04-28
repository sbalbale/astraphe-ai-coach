<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { goto } from '$app/navigation';

  let settings = $state(athleteStore.profile?.notification_settings || {
    readiness: true,
    coach: true,
    workouts: false,
    insights: true
  });
  
  let saving = $state(false);

  function goBack() {
    goto('/profile');
  }

  async function toggleSetting(key: keyof typeof settings) {
    settings[key] = !settings[key];
    saving = true;
    await athleteStore.updateProfile({
      notification_settings: settings
    });
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
      <p class="text-[13px] font-semibold mb-3">Push Notifications</p>
      <div class="flex flex-col gap-0">
        <label class="flex justify-between items-center py-3 border-b border-border cursor-pointer group">
          <div>
            <p class="text-[13px] font-medium text-text0 group-hover:text-blue transition-colors">Daily Readiness</p>
            <p class="text-[10px] text-text2 mt-0.5">Morning alerts when your recovery score is ready.</p>
          </div>
          <input type="checkbox" checked={settings.readiness} onchange={() => toggleSetting('readiness')} disabled={saving} class="w-4 h-4 accent-blue" />
        </label>
        <label class="flex justify-between items-center py-3 border-b border-border cursor-pointer group">
          <div>
            <p class="text-[13px] font-medium text-text0 group-hover:text-teal transition-colors">Coach Messages</p>
            <p class="text-[10px] text-text2 mt-0.5">Real-time alerts when ASTRAPE updates your plan.</p>
          </div>
          <input type="checkbox" checked={settings.coach} onchange={() => toggleSetting('coach')} disabled={saving} class="w-4 h-4 accent-teal" />
        </label>
        <label class="flex justify-between items-center py-3 border-b border-border cursor-pointer group">
          <div>
            <p class="text-[13px] font-medium text-text0 group-hover:text-amber transition-colors">Workout Reminders</p>
            <p class="text-[10px] text-text2 mt-0.5">1 hour before scheduled sessions.</p>
          </div>
          <input type="checkbox" checked={settings.workouts} onchange={() => toggleSetting('workouts')} disabled={saving} class="w-4 h-4 accent-amber" />
        </label>
        <label class="flex justify-between items-center py-3 cursor-pointer group">
          <div>
            <p class="text-[13px] font-medium text-text0 group-hover:text-[#4621FF] transition-colors">Weekly Insights</p>
            <p class="text-[10px] text-text2 mt-0.5">Summary of your load, form, and sleep trends.</p>
          </div>
          <input type="checkbox" checked={settings.insights} onchange={() => toggleSetting('insights')} disabled={saving} class="w-4 h-4 accent-[#4621FF]" />
        </label>
      </div>
    </Card>

    <p class="text-center text-xs text-text2 p-4">
      Ensure push notifications are allowed in your device settings.
    </p>
  </div>
</div>
