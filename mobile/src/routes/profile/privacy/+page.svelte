<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { confirm } from '$lib/confirm';

  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';

  const defaultSettings = {
    share_data: true,
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

  function goBack() {
    goto('/profile');
  }

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
      <p class="text-[13px] font-semibold mb-3">Data Sharing</p>
      <div class="flex flex-col gap-0">
        <label class="flex justify-between items-center py-3 border-b border-border cursor-pointer group">
          <div class="pr-4">
            <p class="text-[13px] font-medium text-text0 transition-colors">Anonymous AI Training</p>
            <p class="text-[10px] text-text2 mt-1 leading-relaxed">Allow ASTRAPE to use your anonymized performance data to improve our global coaching models.</p>
          </div>
          <input type="checkbox" checked={settings.share_data} onchange={() => toggleSetting('share_data')} disabled={saving} class="w-4 h-4 accent-teal shrink-0" />
        </label>
        <label class="flex justify-between items-center py-3 cursor-pointer group">
          <div class="pr-4">
            <p class="text-[13px] font-medium text-text0 transition-colors">Product Updates</p>
            <p class="text-[10px] text-text2 mt-1 leading-relaxed">Receive occasional emails about new features and platform updates.</p>
          </div>
          <input type="checkbox" checked={settings.marketing} onchange={() => toggleSetting('marketing')} disabled={saving} class="w-4 h-4 accent-teal shrink-0" />
        </label>
      </div>
    </Card>

    <Card class="border-red/30 !bg-gradient-to-br from-red/5 via-transparent to-transparent">
      <p class="text-[13px] font-semibold text-red mb-2">Danger Zone</p>
      <p class="text-[11px] text-text1 leading-relaxed mb-4">
        Permanently delete your account and wipe all personal data from our servers. This action is irreversible and you will lose all your coaching history, connected integrations, and AI models.
      </p>
      <button onclick={handleDeleteAccount} class="w-full py-2.5 bg-red-dim border border-red text-red text-xs font-semibold rounded-lg hover:bg-red hover:text-text0 transition-colors cursor-pointer">
        Delete Account
      </button>
    </Card>
  </div>
</div>
