<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import SelectMenu from '$lib/components/SelectMenu.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { normalizeUnits, kgToLbRoundedHalf, lbToKg, cmToFtIn, ftInToCm, type Units } from '$lib/utils/units';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  let units = $derived<Units>(normalizeUnits((athleteStore.profile as any)?.measurement_units));

  let name = $state('');
  let email = $state(authStore.user?.email || '');
  let dob = $state('1990-05-15');
  let gender = $state<'male' | 'female'>('male');

  // canonical fields (what the backend expects)
  let weightKg = $state(75);
  let heightCm = $state(180);

  // imperial display fields (only used when units === 'imperial')
  let weightLb = $state(165);
  let heightFt = $state(5);
  let heightIn = $state(11);

  let dirty = $state(false);
  let lastSyncedSig = $state('');
  let initialized = $state(false);
  let saving = $state(false);
  let saved = $state(false);
  let saveError = $state<string | null>(null);

  const genderOptions = [
    { value: 'male', label: 'Male' },
    { value: 'female', label: 'Female' }
  ];

  function syncDisplayFromCanonical() {
    if (units === 'imperial') {
      weightLb = kgToLbRoundedHalf(weightKg);
      const { ft, inch } = cmToFtIn(heightCm);
      heightFt = ft;
      heightIn = inch;
      return;
    }

    // metric: keep canonical values as the single source of truth
    weightKg = Number(weightKg);
    heightCm = Number(heightCm);
  }

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
    } catch {
      // ignore
    }

    if (initialized) return;
    name = athleteStore.profile?.display_name || authStore.user?.user_metadata?.full_name || '';
    dob = athleteStore.profile?.date_of_birth || '1990-05-15';
    gender = (athleteStore.profile?.gender || 'male') === 'female' ? 'female' : 'male';

    weightKg = athleteStore.profile?.weight_kg ?? 75;
    heightCm = athleteStore.profile?.height_cm ?? 180;
    syncDisplayFromCanonical();

    lastSyncedSig = `${units}-${athleteStore.profile?.weight_kg ?? ''}-${athleteStore.profile?.height_cm ?? ''}`;
    initialized = true;
  });

  $effect(() => {
    const sig = `${units}-${athleteStore.profile?.weight_kg ?? ''}-${athleteStore.profile?.height_cm ?? ''}`;
    if (dirty || sig === lastSyncedSig) return;

    weightKg = athleteStore.profile?.weight_kg ?? 75;
    heightCm = athleteStore.profile?.height_cm ?? 180;
    syncDisplayFromCanonical();
    lastSyncedSig = sig;
  });

  function goBack() {
    goto('/profile');
  }

  async function handleSave(e: Event) {
    e.preventDefault();
    saving = true;
    saved = false;
    saveError = null;

    const nextWeightKg = units === 'imperial' ? lbToKg(weightLb) : Number(weightKg);
    const nextHeightCm = units === 'imperial' ? ftInToCm(heightFt, heightIn) : Number(heightCm);
    const success = await athleteStore.updateProfile({
      display_name: name,
      date_of_birth: dob,
      gender,
      weight_kg: nextWeightKg,
      height_cm: nextHeightCm
    });
    saving = false;
    if (success) {
      dirty = false;
      saved = true;
      // Auto-hide after a short moment so it doesn't stick forever.
      window.setTimeout(() => {
        saved = false;
      }, 2500);
    } else {
      saveError = 'Failed to save changes. Please try again.';
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
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Personal Info</h1>
    </div>
  </div>

  <form onsubmit={handleSave} class="flex flex-col gap-3 mt-2">
    {#if saved}
      <div class="px-3 py-2 rounded-xl border text-[12px] bg-teal-dim border-teal/30 text-teal">
        Saved successfully.
      </div>
    {/if}
    {#if saveError}
      <div class="px-3 py-2 rounded-xl border text-[12px] bg-red-dim border-red/30 text-red">
        {saveError}
      </div>
    {/if}
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
          <DatePicker
            id="dob"
            bind:value={dob}
            ariaLabel="Date of Birth"
            buttonClass="w-full p-2.5 pr-2 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
            placeholder="YYYY-MM-DD"
          />
        </div>
        <div>
          <label for="gender" class="block text-[11px] text-text2 mb-1">Gender</label>
          <SelectMenu
            id="gender"
            bind:value={gender}
            options={genderOptions}
            ariaLabel="Gender"
            buttonClass="w-full p-2.5 pr-2 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
          />
        </div>
      </div>
    </Card>

    <Card>
      <p class="text-[13px] font-semibold mb-3">Biometrics</p>
      <div class="flex gap-3">
        <div class="flex-1">
          {#if units === 'imperial'}
            <label for="weight-lb" class="block text-[11px] text-text2 mb-1">Weight (lb)</label>
            <input
              id="weight-lb"
              type="number"
              step="0.1"
              bind:value={weightLb}
              oninput={() => (dirty = true)}
              class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
            />
          {:else}
            <label for="weight-kg" class="block text-[11px] text-text2 mb-1">Weight (kg)</label>
            <input
              id="weight-kg"
              type="number"
              step="0.1"
              bind:value={weightKg}
              oninput={() => (dirty = true)}
              class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
            />
          {/if}
        </div>
        <div class="flex-1">
          {#if units === 'imperial'}
            <label for="height-ft" class="block text-[11px] text-text2 mb-1">Height</label>
            <div class="flex gap-2">
              <div class="flex-1">
                <input
                  id="height-ft"
                  type="number"
                  step="1"
                  min="0"
                  bind:value={heightFt}
                  oninput={() => (dirty = true)}
                  placeholder="ft"
                  class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
                />
              </div>
              <div class="flex-1">
                <input
                  id="height-in"
                  type="number"
                  step="1"
                  min="0"
                  max="11"
                  bind:value={heightIn}
                  oninput={() => (dirty = true)}
                  placeholder="in"
                  class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
                />
              </div>
            </div>
          {:else}
            <label for="height-cm" class="block text-[11px] text-text2 mb-1">Height (cm)</label>
            <input
              id="height-cm"
              type="number"
              step="0.1"
              bind:value={heightCm}
              oninput={() => (dirty = true)}
              class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
            />
          {/if}
        </div>
      </div>
    </Card>

    <button type="submit" disabled={saving} class="w-full py-3.5 bg-blue text-text0 font-semibold rounded-xl hover:bg-blue/90 transition-colors mt-2 disabled:opacity-50">
      {saving ? 'Saving...' : 'Save Changes'}
    </button>
  </form>
</div>
