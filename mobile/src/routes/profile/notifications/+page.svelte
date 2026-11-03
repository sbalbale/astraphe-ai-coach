<script lang="ts">
  import SubpageHeader from '$lib/components/SubpageHeader.svelte';
  import ToggleSwitch from '$lib/components/ToggleSwitch.svelte';
  import { onMount } from 'svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { requestPushPermission, initPushNotifications } from '$lib/services/pushNotifications';
  import { NOTIFICATION_DEFAULTS, effectiveNotificationSettings } from '$lib/notificationSettings';

  let settings = $state({ ...NOTIFICATION_DEFAULTS } as Record<keyof typeof NOTIFICATION_DEFAULTS, boolean>);
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
    settings = effectiveNotificationSettings(fromProfile);
    initialized = true;

    // Check current permission state for the UI hint.
    if ('Notification' in window) {
      permissionGranted = Notification.permission === 'granted';
    } else {
      permissionGranted = true; // native — assume OK until the OS says otherwise
    }
  });


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
    const ok = await athleteStore.updateProfile({
      notification_settings: { ...settings }
    });
    saving = false;
    // Don't leave a toggle showing a state that wasn't saved.
    if (!ok) settings[key] = !turningOn;
  }

  async function enableNotifications() {
    const granted = await requestPushPermission();
    permissionGranted = granted;
    if (granted) {
      await initPushNotifications();
    }
  }
</script>

<div class="flex flex-col gap-4 pb-6">
  <SubpageHeader title="Notifications" />

  {#if permissionGranted === false}
    <div class="flex flex-col gap-2 px-4 py-3.5 rounded-[18px] bg-amber-dim border border-amber/30">
      <p class="m-0 text-sm font-medium text-amber">Notifications are blocked</p>
      <p class="m-0 text-xs text-text1">Allow notifications in your device or browser settings, then tap below.</p>
      <button type="button" class="self-start h-10 px-3.5 rounded-xl border border-amber/40 bg-transparent text-[13px] font-medium text-amber cursor-pointer" onclick={enableNotifications}>Enable notifications</button>
    </div>
  {:else if permissionGranted === true}
    <div class="flex items-center gap-3 px-4 py-3.5 rounded-[18px] bg-blue-dim border border-blue/25">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="shrink-0 text-blue"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"></path><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"></path></svg>
      <span class="text-sm text-text0">Push notifications are on for this device.</span>
    </div>
  {/if}

  <section aria-label="Push notifications" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-1 flex flex-col">
    {#each [
      { key: 'readiness', title: 'Daily readiness', desc: 'Morning alert when your recovery score is ready.' },
      { key: 'workouts', title: 'Workout reminders', desc: '1 hour before scheduled sessions.' },
      { key: 'coach', title: 'Coach messages', desc: 'When your coach adjusts the plan or replies.' },
      { key: 'insights', title: 'Weekly insights', desc: 'Sunday summary of load, form and sleep trends.' }
    ] as row, i (row.key)}
      <div class="flex items-center gap-4 py-3.5 {i ? 'border-t border-border' : ''}">
        <div class="flex-1 min-w-0 flex flex-col gap-0.5">
          <span class="text-base font-medium">{row.title}</span>
          <span class="text-[13px] leading-[1.4] text-text2">{row.desc}</span>
        </div>
        <ToggleSwitch
          label={row.title}
          checked={settings[row.key as keyof typeof settings]}
          disabled={saving}
          onchange={() => toggleSetting(row.key as keyof typeof settings)}
        />
      </div>
    {/each}
  </section>
</div>
