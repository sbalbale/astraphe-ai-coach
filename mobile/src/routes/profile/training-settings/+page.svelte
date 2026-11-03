<script lang="ts">
  import SubpageHeader from '$lib/components/SubpageHeader.svelte';
  import SelectMenu from '$lib/components/SelectMenu.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { convertPace, normalizeUnits, type Units } from '$lib/utils/units';
  import { onMount } from 'svelte';

  // Empty until the athlete sets them: invented values (280 W / 185 bpm / 5:00) used to
  // be saved as real anchors on any save, then drove zones, plan targets and W/kg.
  let maxHR = $state<number | null>(null);
  let restingHR = $state<number | null>(null);
  /** Writable preference — use profile.hr_zone_method, not generated profile.zone_method */
  let hrZoneMethod = $state('lthr');
  let thresholdHR = $state<number | null>(null);
  let ftp = $state<number | null>(null);
  let pace = $state('');
  const PACE_RE = /^d{1,2}:[0-5]d$/;
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
  let timeFormat = $state('12h');
  let initialized = $state(false);
  let saving = $state(false);
  let saved = $state(false);
  let saveError = $state<string | null>(null);

  const hrZoneMethodOptions: { value: string; label: string }[] = [
    { value: 'lthr', label: '5 zones from LTHR (Coggan)' },
    { value: 'hrr', label: '5 zones from HR reserve (Karvonen)' },
    { value: 'max_hr', label: '5 zones from max HR' }
  ];

  const sportOptions = [
    { value: 'triathlon', label: 'Triathlon' },
    { value: 'run', label: 'Run' },
    { value: 'bike', label: 'Bike' },
    { value: 'swim', label: 'Swim' },
    { value: 'row', label: 'Row' },
    { value: 'strength', label: 'Strength' },
    { value: 'mobility', label: 'Mobility' }
  ];

  onMount(async () => {
    try {
      await athleteStore.fetchAll();
      // The form starts from the database values, not a cached profile.
      await athleteStore.refreshProfile();
    } catch {
      // ignore
    }

    if (initialized) return;
    maxHR = Number(athleteStore.profile?.max_hr) > 0 ? Number(athleteStore.profile?.max_hr) : null;
    restingHR =
      typeof athleteStore.profile?.resting_hr === 'number' ? athleteStore.profile.resting_hr : null;
    const hm = (athleteStore.profile as { hr_zone_method?: string })?.hr_zone_method;
    if (hm === 'hrr' || hm === 'max_hr' || hm === 'lthr') {
      hrZoneMethod = hm;
    }
    thresholdHR = athleteStore.profile?.threshold_hr ?? null;
    ftp = Number(athleteStore.profile?.ftp_watts) > 0 ? Number(athleteStore.profile?.ftp_watts) : null;
    pace = athleteStore.profile?.threshold_pace || '';
    sport = coerceSportFocus(String(athleteStore.profile?.sport_focus?.[0] || 'run'));
    units = normalizeUnits((athleteStore.profile as any)?.measurement_units);
    timeFormat = (athleteStore.profile as any)?.time_format || '12h';
    initialized = true;
  });


  function setUnits(next: Units) {
    if (next === units) return;
    if (PACE_RE.test(pace)) pace = convertPace(pace, units, next);
    units = next;
  }

  async function handleSave(e: Event) {
    e.preventDefault();
    saving = true;
    saved = false;
    saveError = null;
    const updates: Record<string, unknown> = {
      sport_focus: [sport.toLowerCase()],
      measurement_units: units,
      time_format: timeFormat,
      hr_zone_method: hrZoneMethod
    };

    // Only send anchors the athlete has actually set.
    if (maxHR != null && Number(maxHR) > 0) updates.max_hr = Number(maxHR);
    if (ftp != null && Number(ftp) > 0) updates.ftp_watts = Number(ftp);
    if (pace.trim()) {
      if (!PACE_RE.test(pace.trim())) {
        saving = false;
        saveError = 'Threshold pace should look like 5:00.';
        return;
      }
      updates.threshold_pace = pace.trim();
    }

    if (restingHR != null && restingHR > 0) {
      updates.resting_hr = restingHR;
    }

    if (thresholdHR != null && thresholdHR > 0) {
      updates.threshold_hr = thresholdHR;
    }

    const success = await athleteStore.updateProfile(updates);
    saving = false;
    if (success) {
      saved = true;
      window.setTimeout(() => {
        saved = false;
      }, 2500);
    } else {
      saveError = athleteStore.lastProfileSaveError ?? 'Failed to save changes. Please try again.';
    }
  }

  const anchorInput =
    'w-[88px] h-11 px-3 rounded-xl border border-border bg-bg0 text-right font-mono text-[15px] text-text0 outline-none focus:border-blue';
</script>

<form onsubmit={handleSave} class="flex flex-col gap-4 pb-6">
  <SubpageHeader title="Training settings" />

  <div class="flex flex-col gap-2">
    <label for="sport" class="font-mono text-[11px] tracking-[0.14em] text-text2">MAIN SPORT</label>
    <SelectMenu
      id="sport"
      bind:value={sport}
      options={sportOptions}
      ariaLabel="Main sport"
      buttonClass="w-full h-14 px-4 pr-3 bg-bg2 border border-border rounded-[14px] text-base text-text0 outline-none focus:border-blue"
    />
  </div>

  <section aria-label="Performance anchors" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-1 flex flex-col">
    {#each [
      { id: 'ftp', label: 'Cycling FTP', unit: 'W' },
      { id: 'lthr', label: 'Lactate threshold HR', unit: 'bpm' },
      { id: 'maxhr', label: 'Max HR', unit: 'bpm' },
      { id: 'restinghr', label: 'Resting HR', unit: 'bpm' },
      { id: 'pace', label: 'Threshold pace', unit: units === 'metric' ? '/km' : '/mi' }
    ] as row, i (row.id)}
      <div class="flex items-center gap-3 py-2.5 {i ? 'border-t border-border' : ''}">
        <label for={row.id} class="flex-1 text-[15px]">{row.label}</label>
        {#if row.id === 'ftp'}
          <input id="ftp" type="number" inputmode="numeric" placeholder="—" bind:value={ftp} class={anchorInput} />
        {:else if row.id === 'lthr'}
          <input id="lthr" type="number" inputmode="numeric" min="100" max="220" step="1" bind:value={thresholdHR} class={anchorInput} />
        {:else if row.id === 'maxhr'}
          <input id="maxhr" type="number" inputmode="numeric" placeholder="—" bind:value={maxHR} class={anchorInput} />
        {:else if row.id === 'restinghr'}
          <input
            id="restinghr"
            type="number"
            inputmode="numeric"
            min="30"
            max="120"
            placeholder="—"
            value={restingHR ?? ''}
            oninput={(e) => {
              const v = e.currentTarget.value;
              restingHR = v === '' ? null : Number(v);
            }}
            class={anchorInput}
          />
        {:else}
          <input id="pace" type="text" inputmode="numeric" placeholder="5:00" bind:value={pace} class={anchorInput} />
        {/if}
        <span class="w-9 text-[13px] text-text2">{row.unit}</span>
      </div>
    {/each}
  </section>

  <div class="flex flex-col gap-2">
    <label for="hrzone-method" class="font-mono text-[11px] tracking-[0.14em] text-text2">HEART-RATE ZONES</label>
    <SelectMenu
      id="hrzone-method"
      bind:value={hrZoneMethod}
      options={hrZoneMethodOptions}
      ariaLabel="Heart-rate zone calculation"
      buttonClass="w-full h-14 px-4 pr-3 bg-bg2 border border-border rounded-[14px] text-base text-text0 outline-none focus:border-blue"
    />
    <p class="m-0 text-xs leading-[1.45] text-text2">Karvonen needs max and resting HR. Coggan uses your lactate threshold HR.</p>
  </div>

  <div class="grid grid-cols-2 gap-3">
    <div class="flex flex-col gap-2">
      <span class="font-mono text-[11px] tracking-[0.14em] text-text2">UNITS</span>
      <div role="radiogroup" aria-label="Units" class="grid grid-cols-2 gap-0.5 p-1 rounded-[14px] bg-bg2 border border-border">
        {#each [['metric', 'Metric'], ['imperial', 'Imperial']] as [v, l] (v)}
          <button type="button" role="radio" aria-checked={units === v} class="h-10 rounded-[10px] border-0 text-[13px] font-medium cursor-pointer {units === v ? 'bg-bg3 text-text0' : 'bg-transparent text-text2'}" onclick={() => setUnits(v as Units)}>{l}</button>
        {/each}
      </div>
    </div>
    <div class="flex flex-col gap-2">
      <span class="font-mono text-[11px] tracking-[0.14em] text-text2">TIME</span>
      <div role="radiogroup" aria-label="Time format" class="grid grid-cols-2 gap-0.5 p-1 rounded-[14px] bg-bg2 border border-border">
        {#each [['12h', '12h'], ['24h', '24h']] as [v, l] (v)}
          <button type="button" role="radio" aria-checked={timeFormat === v} class="h-10 rounded-[10px] border-0 text-[13px] font-medium cursor-pointer {timeFormat === v ? 'bg-bg3 text-text0' : 'bg-transparent text-text2'}" onclick={() => (timeFormat = v)}>{l}</button>
        {/each}
      </div>
    </div>
  </div>

  {#if saved}
    <p class="m-0 px-4 py-3 rounded-[14px] bg-teal-dim border border-teal/30 text-[13px] text-teal">Saved.</p>
  {/if}
  {#if saveError}
    <p class="m-0 px-4 py-3 rounded-[14px] bg-red-dim border border-red/30 text-[13px] text-red">{saveError}</p>
  {/if}

  <button type="submit" disabled={saving} class="mt-2 h-14 rounded-[16px] border-0 bg-blue text-[#0B1420] text-base font-semibold cursor-pointer disabled:opacity-50">
    {saving ? 'Saving…' : 'Save changes'}
  </button>
</form>
