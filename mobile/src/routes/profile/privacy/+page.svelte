<script lang="ts">
  import SubpageHeader from '$lib/components/SubpageHeader.svelte';
  import ToggleSwitch from '$lib/components/ToggleSwitch.svelte';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { confirm } from '$lib/confirm';

  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';

  const defaultSettings = {
    share_data: false,
    marketing: false
  };

  let settings = $state({ ...defaultSettings });
  let initialized = $state(false);
  
  let saving = $state(false);

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
    } catch {
      // ignore
    }

    if (initialized) return;
    const fromProfile = athleteStore.profile?.privacy_settings;
    settings = { ...defaultSettings, ...(fromProfile ?? {}) };
    initialized = true;
  });


  async function toggleSetting(key: keyof typeof settings) {
    settings[key] = !settings[key];
    saving = true;
    await athleteStore.updateProfile({
      privacy_settings: settings
    });
    saving = false;
  }

  async function handleDeleteAccount() {
    const ok = await confirm({
      title: 'Delete account?',
      message: 'Permanently delete your account and wipe all personal data from our servers? This cannot be undone.',
      confirmText: 'Delete Account',
      cancelText: 'Cancel',
      confirmTone: 'danger'
    });
    if (ok) {
      try {
        console.log('[Privacy] Deleting account...');
        const success = await athleteStore.deleteAccount();
        if (success) {
          console.log('[Privacy] Account deleted successfully on backend. Signing out...');
          await authStore.signOut();
          console.log('[Privacy] Signed out. Redirecting to signin...');
          goto('/auth/signin');
        } else {
          console.error('[Privacy] Failed to delete account on backend.');
          alert('Failed to delete account. The server might be busy, please try again.');
        }
      } catch (err) {
        console.error('[Privacy] Error during account deletion:', err);
        alert('An unexpected error occurred. Please try again.');
      }
    }
  }
</script>

<div class="flex flex-col gap-4 pb-6">
  <SubpageHeader title="Privacy" />

  <div class="flex flex-col gap-2">
    <span class="font-mono text-[11px] tracking-[0.14em] text-text2">DATA SHARING</span>
    <section aria-label="Data sharing" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-1 flex flex-col">
      {#each [
        { key: 'share_data', title: 'Anonymous AI training', desc: 'Let Astraphe use anonymized performance data to improve coaching models.' },
        { key: 'marketing', title: 'Product updates', desc: 'Occasional emails about new features.' }
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

  <div class="flex flex-col gap-2">
    <span class="font-mono text-[11px] tracking-[0.14em] text-red">DANGER ZONE</span>
    <section aria-label="Delete account" class="flex flex-col gap-3 p-[18px] rounded-[24px] bg-red-dim border border-red/30">
      <p class="m-0 text-sm leading-[1.45] text-text0">Deleting your account removes your workouts, biometrics and coach history. This can't be undone.</p>
      <button type="button" class="h-12 rounded-[14px] border border-red/70 bg-transparent text-red text-sm font-semibold cursor-pointer" onclick={handleDeleteAccount}>Delete account</button>
    </section>
  </div>
</div>
