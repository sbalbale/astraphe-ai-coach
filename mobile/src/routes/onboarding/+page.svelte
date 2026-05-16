<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import SelectMenu from '$lib/components/SelectMenu.svelte';
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

  let dob = $state('1990-05-15');
  let gender = $state<'male' | 'female'>('male');

  // canonical fields (what the backend expects)
  let weightKg = $state(75);
  let heightCm = $state(180);

  // imperial display fields (only used when units === 'imperial')
  let weightLb = $state(165);
  let heightFt = $state(5);
  let heightIn = $state(11);

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
    { value: 'male', label: 'Male' },
    { value: 'female', label: 'Female' }
  ];

  function syncDisplayFromCanonical() {
    if (units !== 'imperial') return;
    weightLb = kgToLbRoundedHalf(weightKg);
    const { ft, inch } = cmToFtIn(heightCm);
    heightFt = ft;
    heightIn = inch;
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
    dob = p?.date_of_birth || '1990-05-15';
    gender = (p?.gender || 'male') === 'female' ? 'female' : 'male';

    weightKg = p?.weight_kg ?? 75;
    heightCm = p?.height_cm ?? 180;
    if (units === 'imperial') syncDisplayFromCanonical();

    // Optional thresholds (keep blank if missing to preserve "optional")
    maxHrRaw = p?.max_hr ? String(p.max_hr) : '';
    ftpRaw = p?.ftp_watts ? String(p.ftp_watts) : '';
    pace = p?.threshold_pace ? String(p.threshold_pace) : '';

    initialized = true;
  });

  const canSubmit = $derived.by(() => {
    const haveSport = !!sport?.trim();
    const haveDob = /^\d{4}-\d{2}-\d{2}$/.test(dob);
    const haveGender = gender === 'male' || gender === 'female';
    const haveUnits = units === 'metric' || units === 'imperial';
    const haveTime = timeFormat === '12h' || timeFormat === '24h';

    const w = units === 'imperial' ? lbToKg(weightLb) : Number(weightKg);
    const h = units === 'imperial' ? ftInToCm(heightFt, heightIn) : Number(heightCm);
    const haveBio = Number.isFinite(w) && w > 0 && Number.isFinite(h) && h > 0;

    return haveSport && haveUnits && haveTime && haveDob && haveGender && haveBio && !saving;
  });

  /** Optional numeric fields use `type="number"`; bind values may be number or empty, never call .trim() blindly. */
  function optionalNumericText(v: unknown): string {
    if (v == null || v === '') return '';
    return typeof v === 'string' ? v.trim() : String(v).trim();
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
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
</script>

<div class="min-h-full flex flex-col p-6 items-center justify-center relative">
  <!-- Decor elements (match auth styling) -->
  <div class="absolute top-0 left-0 w-full h-[300px] bg-gradient-to-b from-[rgba(70,33,255,0.15)] to-transparent pointer-events-none"></div>
  <div class="absolute -top-[100px] -right-[100px] w-[320px] h-[320px] bg-teal rounded-full blur-[120px] opacity-15 pointer-events-none"></div>

  <div class="w-full max-w-sm z-10">
    <div class="mb-7 text-center">
      <p class="text-[10px] text-text2 font-mono uppercase tracking-widest mb-2">Welcome</p>
      <h1 class="text-2xl font-bold tracking-tight mb-1">Finish setup</h1>
      <p class="text-text2 text-sm">A few details to personalize your training.</p>
    </div>

    {#if saveError}
      <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg mb-4 text-xs text-text0 leading-relaxed">
        {saveError}
      </div>
    {/if}

    <form onsubmit={handleSubmit} class="flex flex-col gap-3">
      <Card>
        <p class="text-[13px] font-semibold mb-3">Preferences</p>
        <div class="flex flex-col gap-4">
          <div>
            <label for="sport" class="block text-[11px] text-text2 mb-1">Main Sport</label>
            <SelectMenu
              id="sport"
              bind:value={sport}
              options={sportOptions}
              ariaLabel="Main Sport"
              buttonClass="w-full p-2.5 pr-2 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
            />
          </div>

          <div>
            <label for="units" class="block text-[11px] text-text2 mb-1">Measurement Units</label>
            <div class="flex p-1 bg-glass2 rounded-lg border border-border">
              <button
                type="button"
                class="flex-1 py-1.5 text-xs rounded-md transition-colors {units === 'metric' ? 'bg-blue text-text0' : 'text-text2 hover:text-text0'}"
                onclick={() => setUnits('metric')}
              >
                Metric
              </button>
              <button
                type="button"
                class="flex-1 py-1.5 text-xs rounded-md transition-colors {units === 'imperial' ? 'bg-blue text-text0' : 'text-text2 hover:text-text0'}"
                onclick={() => setUnits('imperial')}
              >
                Imperial
              </button>
            </div>
          </div>

          <div>
            <label for="timeformat" class="block text-[11px] text-text2 mb-1">Time Format</label>
            <div class="flex p-1 bg-glass2 rounded-lg border border-border">
              <button
                type="button"
                class="flex-1 py-1.5 text-xs rounded-md transition-colors {timeFormat === '12h' ? 'bg-blue text-text0' : 'text-text2 hover:text-text0'}"
                onclick={() => (timeFormat = '12h')}
              >
                12-Hour
              </button>
              <button
                type="button"
                class="flex-1 py-1.5 text-xs rounded-md transition-colors {timeFormat === '24h' ? 'bg-blue text-text0' : 'text-text2 hover:text-text0'}"
                onclick={() => (timeFormat = '24h')}
              >
                24-Hour
              </button>
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <p class="text-[13px] font-semibold mb-3">About you</p>
        <div class="flex flex-col gap-4">
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
        <div class="flex flex-col gap-4">
          <div class="flex gap-3">
            <div class="flex-1">
              {#if units === 'imperial'}
                <label for="weight-lb" class="block text-[11px] text-text2 mb-1">Weight (lb)</label>
                <input
                  id="weight-lb"
                  type="number"
                  step="0.1"
                  bind:value={weightLb}
                  class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
                />
              {:else}
                <label for="weight-kg" class="block text-[11px] text-text2 mb-1">Weight (kg)</label>
                <input
                  id="weight-kg"
                  type="number"
                  step="0.1"
                  bind:value={weightKg}
                  class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
                />
              {/if}
            </div>

            <div class="flex-1">
              {#if units === 'imperial'}
                <label for="height-ft" class="block text-[11px] text-text2 mb-1">Height</label>
                <div class="flex gap-2">
                  <input
                    id="height-ft"
                    type="number"
                    step="1"
                    min="0"
                    bind:value={heightFt}
                    placeholder="ft"
                    class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
                  />
                  <input
                    id="height-in"
                    type="number"
                    step="1"
                    min="0"
                    max="11"
                    bind:value={heightIn}
                    placeholder="in"
                    class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
                  />
                </div>
              {:else}
                <label for="height-cm" class="block text-[11px] text-text2 mb-1">Height (cm)</label>
                <input
                  id="height-cm"
                  type="number"
                  step="0.1"
                  bind:value={heightCm}
                  class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
                />
              {/if}
            </div>
          </div>

          <div class="border-t border-border pt-4">
            <div class="flex items-center justify-between mb-2">
              <p class="text-[13px] font-semibold">Thresholds</p>
              <p class="text-[10px] text-text2 font-mono uppercase tracking-widest">Optional</p>
            </div>

            <div class="flex items-center justify-between gap-3">
              <div class="flex-1">
                <label for="maxhr" class="block text-[11px] text-text2 mb-1">Max HR (bpm)</label>
                <input
                  id="maxhr"
                  type="number"
                  bind:value={maxHrRaw}
                  placeholder="e.g. 190"
                  class="w-full p-2 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-red"
                />
              </div>
              <div class="flex-1">
                <label for="ftp" class="block text-[11px] text-text2 mb-1">Cycling FTP (W)</label>
                <input
                  id="ftp"
                  type="number"
                  bind:value={ftpRaw}
                  placeholder="e.g. 280"
                  class="w-full p-2 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
                />
              </div>
            </div>

            <div class="mt-4">
              <label for="pace" class="block text-[11px] text-text2 mb-1">Threshold Pace ({units === 'metric' ? '/km' : '/mile'})</label>
              <input
                id="pace"
                type="text"
                bind:value={pace}
                placeholder="e.g. 5:00"
                class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-teal"
              />
              <p class="text-[10px] text-text2 mt-2 leading-relaxed">
                Enter pace as <span class="text-text1 font-mono">mm:ss</span>. It will automatically convert if you switch units.
              </p>
            </div>
          </div>
        </div>
      </Card>

      <button
        type="submit"
        disabled={!canSubmit}
        class="w-full mt-1 py-3.5 bg-teal text-bg1 font-semibold rounded-xl hover:bg-teal/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {saving ? 'Saving...' : 'Finish Setup'}
      </button>
    </form>
  </div>
</div>

