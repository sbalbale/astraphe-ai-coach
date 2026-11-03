<script lang="ts">
  import SubpageHeader from '$lib/components/SubpageHeader.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import SelectMenu from '$lib/components/SelectMenu.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { normalizeUnits, kgToLbRoundedHalf, lbToKg, cmToFtIn, ftInToCm, type Units } from '$lib/utils/units';
  import { latestWeightKg } from '$lib/utils/biometrics';
  import { onMount } from 'svelte';

  let units = $derived<Units>(normalizeUnits((athleteStore.profile as any)?.measurement_units));

  let name = $state('');
  let email = $state(authStore.user?.email || '');
  let dob = $state('1990-05-15');
  let gender = $state<'male' | 'female'>('male');

  // canonical fields (what the backend expects); NaN = unknown, shown as an empty field
  let weightKg = $state(NaN);
  let heightCm = $state(NaN);

  // imperial display fields (only used when units === 'imperial')
  let weightLb = $state(NaN);
  let heightFt = $state(NaN);
  let heightIn = $state(NaN);

  // The same weight the Me page shows: newest reading, else the profile value.
  const currentWeightKg = $derived(
    latestWeightKg(
      athleteStore.biometrics?.series,
      athleteStore.profile?.weight_kg,
      (athleteStore.profile as { latest_weight_kg?: unknown } | null)?.latest_weight_kg
    )
  );
  const currentHeightCm = $derived(Number(athleteStore.profile?.height_cm) > 0 ? Number(athleteStore.profile?.height_cm) : NaN);

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
      weightLb = Number.isFinite(weightKg) ? kgToLbRoundedHalf(weightKg) : NaN;
      if (Number.isFinite(heightCm)) {
        const { ft, inch } = cmToFtIn(heightCm);
        heightFt = ft;
        heightIn = inch;
      } else {
        heightFt = NaN;
        heightIn = NaN;
      }
      return;
    }

    // metric: keep canonical values as the single source of truth
    weightKg = Number(weightKg);
    heightCm = Number(heightCm);
  }

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
      // The form starts from the database values, not a cached profile.
      await athleteStore.refreshProfile();
    } catch {
      // ignore
    }

    if (initialized) return;
    name = athleteStore.profile?.display_name || authStore.user?.user_metadata?.full_name || '';
    dob = athleteStore.profile?.date_of_birth || '1990-05-15';
    gender = (athleteStore.profile?.gender || 'male') === 'female' ? 'female' : 'male';

    weightKg = currentWeightKg ?? NaN;
    heightCm = currentHeightCm;
    syncDisplayFromCanonical();

    lastSyncedSig = `${units}-${currentWeightKg ?? ''}-${currentHeightCm}`;
    initialized = true;
  });

  $effect(() => {
    const sig = `${units}-${currentWeightKg ?? ''}-${currentHeightCm}`;
    if (dirty || sig === lastSyncedSig) return;

    weightKg = currentWeightKg ?? NaN;
    heightCm = currentHeightCm;
    syncDisplayFromCanonical();
    lastSyncedSig = sig;
  });


  async function handleSave(e: Event) {
    e.preventDefault();
    saving = true;
    saved = false;
    saveError = null;

    const nextWeightKg = units === 'imperial' ? lbToKg(weightLb) : Number(weightKg);
    const nextHeightCm = units === 'imperial' ? ftInToCm(heightFt, heightIn) : Number(heightCm);
    const payload: Record<string, unknown> = { display_name: name, date_of_birth: dob, gender };
    // Empty fields are left alone rather than saved as a made-up value.
    if (Number.isFinite(nextWeightKg) && nextWeightKg > 0) payload.weight_kg = nextWeightKg;
    if (Number.isFinite(nextHeightCm) && nextHeightCm > 0) payload.height_cm = nextHeightCm;
    const success = await athleteStore.updateProfile(payload);
    saving = false;
    if (success) {
      dirty = false;
      saved = true;
      // Auto-hide after a short moment so it doesn't stick forever.
      window.setTimeout(() => {
        saved = false;
      }, 2500);
    } else {
      saveError = athleteStore.lastProfileSaveError ?? 'Failed to save changes. Please try again.';
    }
  }

  const field =
    'w-full h-14 px-4 bg-bg2 border border-border rounded-[14px] text-base text-text0 outline-none focus:border-blue disabled:opacity-100';
</script>

<form onsubmit={handleSave} class="flex flex-col gap-4 pb-6">
  <SubpageHeader title="Personal info" />

  <div class="flex flex-col gap-1.5">
    <label for="name" class="text-[13px] text-text2">Full name</label>
    <input id="name" type="text" autocomplete="name" bind:value={name} class={field} />
  </div>
  <div class="flex flex-col gap-1.5">
    <label for="email" class="text-[13px] text-text2">Email</label>
    <input id="email" type="email" bind:value={email} class="{field} text-text2" disabled />
  </div>
  <div class="grid grid-cols-2 gap-3">
    <div class="flex flex-col gap-1.5">
      <label for="dob" class="text-[13px] text-text2">Date of birth</label>
      <DatePicker
        id="dob"
        bind:value={dob}
        ariaLabel="Date of birth"
        placeholder="YYYY-MM-DD"
        buttonClass="w-full h-14 px-4 pr-3 bg-bg2 border border-border rounded-[14px] text-base text-text0 outline-none focus:border-blue"
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <label for="gender" class="text-[13px] text-text2">Gender</label>
      <SelectMenu
        id="gender"
        bind:value={gender}
        options={genderOptions}
        ariaLabel="Gender"
        buttonClass="w-full h-14 px-4 pr-3 bg-bg2 border border-border rounded-[14px] text-base text-text0 outline-none focus:border-blue"
      />
    </div>
  </div>

  <span class="mt-1 font-mono text-[11px] tracking-[0.14em] text-text2">BIOMETRICS</span>
  <div class="grid grid-cols-2 gap-3">
    <div class="flex flex-col gap-1.5">
      {#if units === 'imperial'}
        <label for="height-ft" class="text-[13px] text-text2">Height (ft / in)</label>
        <div class="grid grid-cols-2 gap-2">
          <input id="height-ft" type="number" step="1" min="0" placeholder="ft" bind:value={heightFt} oninput={() => (dirty = true)} class="{field} font-mono" />
          <input id="height-in" type="number" step="1" min="0" max="11" placeholder="in" aria-label="Height inches" bind:value={heightIn} oninput={() => (dirty = true)} class="{field} font-mono" />
        </div>
      {:else}
        <label for="height-cm" class="text-[13px] text-text2">Height (cm)</label>
        <input id="height-cm" type="number" step="0.1" bind:value={heightCm} oninput={() => (dirty = true)} class="{field} font-mono" />
      {/if}
    </div>
    <div class="flex flex-col gap-1.5">
      {#if units === 'imperial'}
        <label for="weight-lb" class="text-[13px] text-text2">Weight (lb)</label>
        <input id="weight-lb" type="number" step="0.1" bind:value={weightLb} oninput={() => (dirty = true)} class="{field} font-mono" />
      {:else}
        <label for="weight-kg" class="text-[13px] text-text2">Weight (kg)</label>
        <input id="weight-kg" type="number" step="0.1" bind:value={weightKg} oninput={() => (dirty = true)} class="{field} font-mono" />
      {/if}
    </div>
  </div>
  <p class="m-0 text-xs leading-[1.45] text-text2">Weight updates automatically when a connected scale syncs.</p>

  {#if saved}
    <p class="m-0 px-4 py-3 rounded-[14px] bg-teal-dim border border-teal/30 text-[13px] text-teal">Saved.</p>
  {/if}
  {#if saveError}
    <p class="m-0 px-4 py-3 rounded-[14px] bg-red-dim border border-red/30 text-[13px] text-red">{saveError}</p>
  {/if}

  <button type="submit" disabled={saving} class="mt-4 h-14 rounded-[16px] border-0 bg-blue text-[#0B1420] text-base font-semibold cursor-pointer disabled:opacity-50">
    {saving ? 'Saving…' : 'Save'}
  </button>
</form>
