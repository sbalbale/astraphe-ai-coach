<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { requestPushPermission, initPushNotifications } from '$lib/services/pushNotifications';

  const defaultSettings = {
    readiness: true,
    coach: true,
    workouts: false,
    insights: true
  };

  let settings = $state({ ...defaultSettings });
  let initialized = $state(false);
  let saving = $state(false);
  let permissionGranted = $state<boolean | null>(null);

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
    } catch {
      // ignore; UI can still function with defaults
    }

    if (initialized) return;
    const fromProfile = athleteStore.profile?.notification_settings;
    settings = { ...defaultSettings, ...(fromProfile ?? {}) };
    initialized = true;

    // Check current permission state for the UI hint.
    if ('Notification' in window) {
      permissionGranted = Notification.permission === 'granted';
    } else {
      permissionGranted = true; // native — assume OK until the OS says otherwise
    }
  });

  function goBack() {
    goto('/profile');
  }

  async function toggleSetting(key: keyof typeof settings) {
    const turningOn = !settings[key];
    settings[key] = turningOn;

    // If the user is enabling something for the first time, request permission
    // and register the token so notifications actually arrive.
    if (turningOn && permissionGranted !== true) {
      const granted = await requestPushPermission();
      permissionGranted = granted;
      if (granted) {
        await initPushNotifications();
      }
    }

    saving = true;
    await athleteStore.updateProfile({
      notification_settings: settings
    });
    saving = false;
  }

  async function enableNotifications() {
    const granted = await requestPushPermission();
    permissionGranted = granted;
    if (granted) {
      await initPushNotifications();
    }
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

  {#if permissionGranted === false}
    <div class="bg-amber/10 border border-amber/30 rounded-xl p-4 flex flex-col gap-2">
      <p class="text-[13px] font-semibold text-amber">Notifications are blocked</p>
      <p class="text-[11px] text-text2">Enable notifications in your device or browser settings, then tap below to activate.</p>
      <button onclick={enableNotifications} class="mt-1 self-start px-3 py-1.5 bg-amber/20 border border-amber/40 rounded-lg text-[12px] font-medium text-amber hover:bg-amber/30 transition-colors cursor-pointer">
        Enable Notifications
      </button>
    </div>
  {/if}

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
            <p class="text-[13px] font-medium text-text0 group-hover:text-blue transition-colors">Weekly Insights</p>
            <p class="text-[10px] text-text2 mt-0.5">Summary of your load, form, and sleep trends.</p>
          </div>
          <input type="checkbox" checked={settings.insights} onchange={() => toggleSetting('insights')} disabled={saving} class="w-4 h-4 accent-blue" />
        </label>
      </div>
    </Card>

    <p class="text-center text-xs text-text2 p-4">
      {#if permissionGranted === true}
        Push notifications are active on this device.
      {:else}
        Ensure push notifications are allowed in your device settings.
      {/if}
    </p>
  </div>
</div>
