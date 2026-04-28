<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import FormDateInput from '$lib/components/FormDateInput.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  let name = $state('');
  let email = $state(authStore.user?.email || '');
  let dob = $state('1990-05-15');
  let weight = $state(75);
  let height = $state(180);
  let initialized = $state(false);
  let saving = $state(false);

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
    } catch {
      // ignore
    }

    if (initialized) return;
    name = athleteStore.profile?.display_name || authStore.user?.user_metadata?.full_name || '';
    dob = athleteStore.profile?.date_of_birth || '1990-05-15';
    weight = athleteStore.profile?.weight_kg ?? 75;
    height = athleteStore.profile?.height_cm ?? 180;
    initialized = true;
  });

  function goBack() {
    goto('/profile');
  }

  async function handleSave(e: Event) {
    e.preventDefault();
    saving = true;
    const success = await athleteStore.updateProfile({
      display_name: name,
      date_of_birth: dob,
      weight_kg: weight,
      height_cm: height
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
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Personal Info</h1>
    </div>
  </div>

  <form onsubmit={handleSave} class="flex flex-col gap-3 mt-2">
    <Card>
      <div class="flex flex-col gap-4">
        <div>
          <label for="name" class="block text-[11px] text-text2 mb-1">Full Name</label>
          <input id="name" type="text" bind:value={name} class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue" />
        </div>
        <div>
          <label for="email" class="block text-[11px] text-text2 mb-1">Email</label>
          <input id="email" type="email" bind:value={email} class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue opacity-50" disabled />
        </div>
        <div>
          <label for="dob" class="block text-[11px] text-text2 mb-1">Date of Birth</label>
          <FormDateInput id="dob" type="date" bind:value={dob} ariaLabel="Date of Birth" />
        </div>
      </div>
    </Card>

    <Card>
      <p class="text-[13px] font-semibold mb-3">Biometrics</p>
      <div class="flex gap-3">
        <div class="flex-1">
          <label for="weight" class="block text-[11px] text-text2 mb-1">Weight (kg)</label>
          <input id="weight" type="number" step="0.1" bind:value={weight} class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue" />
        </div>
        <div class="flex-1">
          <label for="height" class="block text-[11px] text-text2 mb-1">Height (cm)</label>
          <input id="height" type="number" step="0.1" bind:value={height} class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue" />
        </div>
      </div>
    </Card>

    <button type="submit" disabled={saving} class="w-full py-3.5 bg-blue text-white font-semibold rounded-xl hover:bg-[#3d1ae6] transition-colors mt-2 disabled:opacity-50">
      {saving ? 'Saving...' : 'Save Changes'}
    </button>
  </form>
</div>
