<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { goto } from '$app/navigation';

  let shareData = $state(true);
  let marketing = $state(false);

  function goBack() {
    goto('/profile');
  }

  function handleDeleteAccount() {
    if (confirm('Are you sure you want to permanently delete your account? This action cannot be undone.')) {
      // API call to delete account goes here
      alert('Account deletion requested.');
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
          <input type="checkbox" bind:checked={shareData} class="w-4 h-4 accent-teal shrink-0" />
        </label>
        <label class="flex justify-between items-center py-3 cursor-pointer group">
          <div class="pr-4">
            <p class="text-[13px] font-medium text-text0 transition-colors">Product Updates</p>
            <p class="text-[10px] text-text2 mt-1 leading-relaxed">Receive occasional emails about new features and platform updates.</p>
          </div>
          <input type="checkbox" bind:checked={marketing} class="w-4 h-4 accent-teal shrink-0" />
        </label>
      </div>
    </Card>

    <Card style="border-color: rgba(240,113,120,0.3); background: linear-gradient(135deg, rgba(240,113,120,0.05), transparent);">
      <p class="text-[13px] font-semibold text-red mb-2">Danger Zone</p>
      <p class="text-[11px] text-text1 leading-relaxed mb-4">
        Permanently delete your account and wipe all personal data from our servers. This action is irreversible and you will lose all your coaching history, connected integrations, and AI models.
      </p>
      <button onclick={handleDeleteAccount} class="w-full py-2.5 bg-red-dim border border-red text-red text-xs font-semibold rounded-lg hover:bg-red hover:text-white transition-colors cursor-pointer">
        Delete Account
      </button>
    </Card>
  </div>
</div>
