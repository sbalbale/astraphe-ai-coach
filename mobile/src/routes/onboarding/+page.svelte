<script lang="ts">
  import DatePicker from '$lib/components/DatePicker.svelte';
  import SelectMenu from '$lib/components/SelectMenu.svelte';
  import BrandMark from '$lib/components/ui/BrandMark.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormAlert from '$lib/components/ui/FormAlert.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { convertPace, normalizeUnits, kgToLbRoundedHalf, lbToKg, cmToFtIn, ftInToCm, type Units } from '$lib/utils/units';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  let initialized = $state(false);
  let saving = $state(false);
  let saveError = $state<string | null>(null);

  const LEGACY_SPORT_FOCUS: Record<string, string> = {
    running: 'run',
    cycling: 'bike',
    swimming: 'swim',
    rowing: 'row',
    strength: 'strength',
    mobility: 'mobility'
  };

  function coerceSportFocus(raw: string): string {
    const t = raw.toLowerCase();
    return LEGACY_SPORT_FOCUS[t] ?? t;
  }

  let sport = $state('run');
  let units = $state<Units>('metric');
  let timeFormat = $state<'12h' | '24h'>('12h');

  // Start empty: "Finish setup" was enabled straight away with an invented birth date,
  // gender, 75 kg and 180 cm, which were then stored as the athlete's real data.
  let dob = $state('');
  let gender = $state<'' | 'male' | 'female'>('');

  // canonical fields (what the backend expects); NaN = not entered (empty input)
  let weightKg = $state(NaN);
  let heightCm = $state(NaN);

  // imperial display fields (only used when units === 'imperial')
  let weightLb = $state(NaN);
  let heightFt = $state(NaN);
  let heightIn = $state(NaN);

  // Optional thresholds
  let maxHrRaw = $state(''); // bpm
  let ftpRaw = $state(''); // watts
  let pace = $state(''); // mm:ss

  const sportOptions = [
    { value: 'row', label: 'Row' },
    { value: 'bike', label: 'Bike' },
    { value: 'swim', label: 'Swim' },
    { value: 'run', label: 'Run' },
    { value: 'strength', label: 'Strength' },
    { value: 'mobility', label: 'Mobility' },
    { value: 'triathlon', label: 'Triathlon' }
  ];

  const genderOptions = [
    { value: '', label: 'Select…' },
    { value: 'male', label: 'Male' },
    { value: 'female', label: 'Female' }
  ];

  // The setup form is shown in four steps; everything is still saved once, at the end.
  const STEPS = [
    {
      label: 'Preferences',
      title: 'How do you like your numbers?',
      subtitle: 'Units and time format for everything you see. You can change these later in Settings.'
    },
    {
      label: 'About you',
      title: 'A little about you',
      subtitle: 'Part of your athlete profile. You can change it later in Personal info.'
    },
    {
      label: 'Thresholds',
      title: 'Where are you starting from?',
      subtitle: "These set your zones. Skip any you don't know; you can add them later in Training settings."
    },
    {
      label: 'Body',
      title: 'Last, your body',
      subtitle: 'Weight and height for your profile. You can change them later in Personal info.'
    }
  ] as const;
  let step = $state(0);
  const current = $derived(STEPS[step]);
  const isLastStep = $derived(step === STEPS.length - 1);

  function syncDisplayFromCanonical() {
    if (units !== 'imperial') return;
    weightLb = Number.isFinite(weightKg) && weightKg > 0 ? kgToLbRoundedHalf(weightKg) : NaN;
    if (Number.isFinite(heightCm) && heightCm > 0) {
      const { ft, inch } = cmToFtIn(heightCm);
      heightFt = ft;
      heightIn = inch;
    } else {
      heightFt = NaN;
      heightIn = NaN;
    }
  }

  function applyImperialToCanonical() {
    weightKg = lbToKg(weightLb);
    heightCm = ftInToCm(heightFt, heightIn);
  }

  function setUnits(next: Units) {
    if (next === units) return;

    if (units === 'imperial') {
      applyImperialToCanonical();
    }

    if (pace.trim()) {
      pace = convertPace(pace, units, next);
    }

    units = next;
    if (units === 'imperial') syncDisplayFromCanonical();
  }

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
    } catch {
      // ignore
    }

    if (initialized) return;
    const p = athleteStore.profile;

    sport = coerceSportFocus(String(p?.sport_focus?.[0] || 'run'));
    units = normalizeUnits(p?.measurement_units);
    timeFormat = (p?.time_format === '24h' ? '24h' : '12h') as any;
    dob = p?.date_of_birth || '';
    gender = p?.gender === 'female' || p?.gender === 'male' ? p.gender : '';

    weightKg = Number(p?.weight_kg) > 0 ? Number(p?.weight_kg) : NaN;
    heightCm = Number(p?.height_cm) > 0 ? Number(p?.height_cm) : NaN;
    if (units === 'imperial') syncDisplayFromCanonical();

    // Optional thresholds (keep blank if missing to preserve "optional")
    maxHrRaw = p?.max_hr ? String(p.max_hr) : '';
    ftpRaw = p?.ftp_watts ? String(p.ftp_watts) : '';
    pace = p?.threshold_pace ? String(p.threshold_pace) : '';

    initialized = true;
  });

  const haveSport = $derived(!!sport?.trim());
  const haveUnits = $derived(units === 'metric' || units === 'imperial');
  const haveTime = $derived(timeFormat === '12h' || timeFormat === '24h');
  const haveAboutYou = $derived(/^\d{4}-\d{2}-\d{2}$/.test(dob) && (gender === 'male' || gender === 'female'));
  const haveBio = $derived.by(() => {
    const w = units === 'imperial' ? lbToKg(weightLb) : Number(weightKg);
    const h = units === 'imperial' ? ftInToCm(heightFt, heightIn) : Number(heightCm);
    return Number.isFinite(w) && w > 0 && Number.isFinite(h) && h > 0;
  });

  const canSubmit = $derived(haveSport && haveUnits && haveTime && haveAboutYou && haveBio && !saving);

  /** Whether the current step's required fields are filled (later steps can't be skipped to). */
  const stepComplete = $derived.by(() => {
    if (step === 0) return haveUnits && haveTime;
    if (step === 1) return haveAboutYou;
    if (step === 2) return haveSport;
    return canSubmit;
  });

  function back() {
    saveError = null;
    if (step > 0) step -= 1;
  }

  /** Optional numeric fields use `type="number"`; bind values may be number or empty, never call .trim() blindly. */
  function optionalNumericText(v: unknown): string {
    if (v == null || v === '') return '';
    return typeof v === 'string' ? v.trim() : String(v).trim();
  }

  /** Enter / Continue: advance a step, or save on the last one. */
  function handleFormSubmit(e: Event) {
    e.preventDefault();
    if (!stepComplete) return;
    if (!isLastStep) {
      step += 1;
      return;
    }
    void handleSubmit();
  }

  async function handleSubmit() {
    saveError = null;
    saving = true;
    try {
      const nextWeightKg = units === 'imperial' ? lbToKg(weightLb) : Number(weightKg);
      const nextHeightCm = units === 'imperial' ? ftInToCm(heightFt, heightIn) : Number(heightCm);

      const payload: Record<string, unknown> = {
        sport_focus: [String(sport).toLowerCase()],
        measurement_units: units,
        time_format: timeFormat,
        date_of_birth: dob,
        gender,
        weight_kg: nextWeightKg,
        height_cm: nextHeightCm
      };

      const maxHrStr = optionalNumericText(maxHrRaw);
      const maxHr = Number(maxHrStr);
      if (maxHrStr && Number.isFinite(maxHr) && maxHr > 0) payload.max_hr = maxHr;

      const ftpStr = optionalNumericText(ftpRaw);
      const ftp = Number(ftpStr);
      if (ftpStr && Number.isFinite(ftp) && ftp > 0) payload.ftp_watts = ftp;

      const paceTrim = pace.trim();
      if (paceTrim) payload.threshold_pace = paceTrim;

      const success = await athleteStore.updateProfile(payload);
      if (success) {
        goto('/dashboard', { replaceState: true });
      } else {
        saveError = 'Failed to save your setup. Please try again.';
      }
    } catch {
      saveError = 'Something went wrong while saving. Please try again.';
    } finally {
      saving = false;
    }
  }

  const fieldClass =
    'w-full h-14 px-5 bg-bg2 border border-border rounded-[18px] text-[16px] text-text0 outline-none focus:border-blue transition-colors placeholder:text-text2/70';
  const segBtn = (on: boolean) =>
    `h-12 rounded-[14px] text-[16px] font-medium border-none cursor-pointer transition-colors ${on ? 'bg-bg3 text-text0' : 'bg-transparent text-text2 hover:text-text1'}`;
</script>

<div
  class="min-h-full flex flex-col bg-bg0 px-6"
  style="padding-top: max(24px, env(safe-area-inset-top, 0px)); padding-bottom: max(24px, env(safe-area-inset-bottom, 0px));"
>
  <form onsubmit={handleFormSubmit} class="w-full max-w-md mx-auto flex-1 flex flex-col">
    <BrandMark size={40} wordmark class="mt-6 mb-8" />

    <div class="grid grid-cols-4 gap-2" aria-hidden="true">
      {#each STEPS as s, i (s.label)}
        <div class="h-1 rounded-full {i <= step ? 'bg-blue' : 'bg-border'}"></div>
      {/each}
    </div>
    <p class="font-mono text-[12px] tracking-[0.22em] uppercase text-text2 mt-4">
      Step {step + 1} of {STEPS.length} · {current.label}
    </p>

    <h1 class="font-display text-[44px] leading-[1.05] text-text0 mt-5 mb-3">{current.title}</h1>
    <p class="text-[17px] text-text1 leading-relaxed mb-8">{current.subtitle}</p>

    {#if step === 0}
      <div class="flex flex-col gap-6">
        <div>
          <span id="units-label" class="block text-[14px] text-text2 mb-2">Measurement units</span>
          <div role="group" aria-labelledby="units-label" class="grid grid-cols-2 gap-1 p-1.5 bg-bg2 border border-border rounded-[18px]">
            <button type="button" aria-pressed={units === 'metric'} class={segBtn(units === 'metric')} onclick={() => setUnits('metric')}>Metric</button>
            <button type="button" aria-pressed={units === 'imperial'} class={segBtn(units === 'imperial')} onclick={() => setUnits('imperial')}>Imperial</button>
          </div>
        </div>
        <div>
          <span id="timeformat-label" class="block text-[14px] text-text2 mb-2">Time format</span>
          <div role="group" aria-labelledby="timeformat-label" class="grid grid-cols-2 gap-1 p-1.5 bg-bg2 border border-border rounded-[18px]">
            <button type="button" aria-pressed={timeFormat === '12h'} class={segBtn(timeFormat === '12h')} onclick={() => (timeFormat = '12h')}>12-hour</button>
            <button type="button" aria-pressed={timeFormat === '24h'} class={segBtn(timeFormat === '24h')} onclick={() => (timeFormat = '24h')}>24-hour</button>
          </div>
        </div>
      </div>
    {:else if step === 1}
      <div class="flex flex-col gap-6">
        <div>
          <label for="dob" class="block text-[14px] text-text2 mb-2">Date of birth</label>
          <DatePicker id="dob" bind:value={dob} ariaLabel="Date of birth" buttonClass={fieldClass} placeholder="YYYY-MM-DD" />
        </div>
        <div>
          <label for="gender" class="block text-[14px] text-text2 mb-2">Gender</label>
          <SelectMenu id="gender" bind:value={gender} options={genderOptions} ariaLabel="Gender" buttonClass={fieldClass} />
        </div>
      </div>
    {:else if step === 2}
      <div class="flex flex-col gap-6">
        <div>
          <span id="sport-label" class="block text-[14px] text-text2 mb-2">Main sport</span>
          <div role="group" aria-labelledby="sport-label" class="grid grid-cols-4 gap-1 p-1.5 bg-bg2 border border-border rounded-[18px]">
            {#each sportOptions as opt (opt.value)}
              <button type="button" aria-pressed={sport === opt.value} class="{segBtn(sport === opt.value)} text-[14px]" onclick={() => (sport = opt.value)}>
                {opt.label}
              </button>
            {/each}
          </div>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="ftp" class="block text-[14px] text-text2 mb-2">Cycling FTP (W)</label>
            <input id="ftp" type="number" inputmode="numeric" bind:value={ftpRaw} placeholder="e.g. 280" class="{fieldClass} font-mono" />
          </div>
          <div>
            <label for="maxhr" class="block text-[14px] text-text2 mb-2">Max HR (bpm)</label>
            <input id="maxhr" type="number" inputmode="numeric" bind:value={maxHrRaw} placeholder="e.g. 190" class="{fieldClass} font-mono" />
          </div>
        </div>

        <div>
          <label for="pace" class="block text-[14px] text-text2 mb-2">
            Threshold pace <span class="text-text2/80">· optional</span>
          </label>
          <input
            id="pace"
            type="text"
            bind:value={pace}
            placeholder={`mm:ss ${units === 'metric' ? '/km' : '/mi'}`}
            class="{fieldClass} font-mono max-w-[calc(50%-0.5rem)]"
          />
        </div>
      </div>
    {:else}
      <div class="grid grid-cols-2 gap-4">
        <div>
          {#if units === 'imperial'}
            <label for="weight-lb" class="block text-[14px] text-text2 mb-2">Weight (lb)</label>
            <input id="weight-lb" type="number" step="0.1" inputmode="decimal" bind:value={weightLb} class="{fieldClass} font-mono" />
          {:else}
            <label for="weight-kg" class="block text-[14px] text-text2 mb-2">Weight (kg)</label>
            <input id="weight-kg" type="number" step="0.1" inputmode="decimal" bind:value={weightKg} class="{fieldClass} font-mono" />
          {/if}
        </div>
        <div>
          {#if units === 'imperial'}
            <label for="height-ft" class="block text-[14px] text-text2 mb-2">Height</label>
            <div class="flex gap-2">
              <input id="height-ft" type="number" step="1" min="0" inputmode="numeric" bind:value={heightFt} placeholder="ft" aria-label="Height, feet" class="{fieldClass} font-mono px-4" />
              <input id="height-in" type="number" step="1" min="0" max="11" inputmode="numeric" bind:value={heightIn} placeholder="in" aria-label="Height, inches" class="{fieldClass} font-mono px-4" />
            </div>
          {:else}
            <label for="height-cm" class="block text-[14px] text-text2 mb-2">Height (cm)</label>
            <input id="height-cm" type="number" step="0.1" inputmode="decimal" bind:value={heightCm} class="{fieldClass} font-mono" />
          {/if}
        </div>
      </div>
    {/if}

    {#if saveError}
      <FormAlert class="mt-6">{saveError}</FormAlert>
    {/if}

    <div class="mt-auto pt-10 flex gap-3">
      {#if step > 0}
        <Button variant="secondary" full={false} class="w-[120px] shrink-0" onclick={back} disabled={saving}>Back</Button>
      {/if}
      <Button type="submit" full={false} class="flex-1" disabled={!stepComplete}>
        {#if isLastStep}{saving ? 'Saving…' : 'Finish setup'}{:else}Continue{/if}
      </Button>
    </div>
  </form>
</div>
