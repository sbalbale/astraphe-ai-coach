<script lang="ts">
  import Modal from './Modal.svelte';
  import DropdownSelect from './DropdownSelect.svelte';
  import DatePicker from './DatePicker.svelte';
  import TimePicker from './TimePicker.svelte';

  type ActivityMode = 'add' | 'edit';
  type NumericInputValue = string | number | undefined;
  type OptionalNumberResult = { value: number | null; error: string };

  let {
    show,
    onClose,
    units = 'metric',
    onSaved,
    mode = 'add',
    workout = null,
  }: {
    show: boolean;
    onClose: () => void;
    units?: 'metric' | 'imperial';
    onSaved: (payload: object) => Promise<void | unknown>;
    mode?: ActivityMode;
    workout?: any;
  } = $props();

  const SPORT_OPTIONS = [
    { value: 'run', label: 'Run' },
    { value: 'bike', label: 'Bike' },
    { value: 'swim', label: 'Swim' },
    { value: 'row', label: 'Row' },
    { value: 'strength', label: 'Strength' },
    { value: 'mobility', label: 'Mobility' },
    { value: 'other', label: 'Other' },
  ];

  const NUMBER_INPUT_VALIDATION = [
    { id: 'act-duration-hrs', error: 'Enter a valid duration.' },
    { id: 'act-duration-mins', error: 'Enter a valid duration.' },
    { id: 'act-distance', error: 'Enter a valid distance.' },
    { id: 'act-hr', error: 'Enter a valid average heart rate.' },
    { id: 'act-avg-watts', error: 'Enter a valid average watts.' },
    { id: 'act-max-hr', error: 'Enter a valid max heart rate.' },
    { id: 'act-norm-power', error: 'Enter a valid normalized power.' }
  ];

  type ActivityFormValues = {
    sport: string;
    date: string;
    startTime: string;
    durationHrs: number;
    durationMins: number;
    title: string;
    distanceRaw: NumericInputValue;
    avgHr: NumericInputValue;
    maxHr: NumericInputValue;
    avgPowerW: NumericInputValue;
    normPowerW: NumericInputValue;
  };

  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function currentTimeStr() {
    const d = new Date();
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  function formatDateInput(d: Date) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function formatTimeInput(d: Date) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  function getWorkoutDurationSecs(w: any): number {
    const direct = w?.duration_seconds ?? w?.duration_secs;
    if (Number.isFinite(Number(direct)) && Number(direct) > 0) return Math.floor(Number(direct));

    const start = w?.started_at ? new Date(w.started_at) : null;
    const end = w?.ended_at ? new Date(w.ended_at) : null;
    if (!start || !end) return 30 * 60;

    const seconds = Math.floor((end.getTime() - start.getTime()) / 1000);
    return Number.isFinite(seconds) && seconds > 0 ? seconds : 30 * 60;
  }

  function formatOptionalNumber(value: unknown) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? String(Math.round(n)) : '';
  }

  const METERS_PER_YARD = 0.9144;
  const METERS_PER_MILE = 1609.34;

  type DistanceUnit = 'm' | 'km' | 'yd' | 'mi';

  function isSwimSport(sport: unknown) {
    const s = String(sport || '').toLowerCase();
    return s === 'swim' || s === 'swimming';
  }

  function distanceUnitForSport(sport: unknown) {
    const s = String(sport || '').toLowerCase();
    if (s === 'row' || s === 'rowing') return 'm' as const;
    if (isSwimSport(s)) return (units === 'imperial' ? ('yd' as const) : ('m' as const));
    return units === 'imperial' ? ('mi' as const) : ('km' as const);
  }

  function defaultSwimDistanceUnit(distanceM: unknown): Extract<DistanceUnit, 'm' | 'km' | 'yd' | 'mi'> {
    const meters = Number(distanceM);
    if (!Number.isFinite(meters) || meters <= 0) {
      return units === 'imperial' ? 'yd' : 'm';
    }
    if (units === 'imperial') {
      return meters < 1609.34 ? 'yd' : 'mi';
    }
    return meters < 1000 ? 'm' : 'km';
  }

  let swimDistanceUnit = $state<Extract<DistanceUnit, 'm' | 'km' | 'yd' | 'mi'>>(
    mode === 'edit' && workout ? defaultSwimDistanceUnit(workout?.distance_m) : units === 'imperial' ? 'yd' : 'm'
  );

  let lastSwimDistanceUnit = $state(swimDistanceUnit);
  $effect(() => {
    if (!isSwimSport(form.sport)) {
      lastSwimDistanceUnit = swimDistanceUnit;
      return;
    }
    if (swimDistanceUnit === lastSwimDistanceUnit) return;

    const raw = String(form.distanceRaw ?? '').trim();
    const v = Number(raw);
    if (!raw || !Number.isFinite(v) || v <= 0) {
      lastSwimDistanceUnit = swimDistanceUnit;
      return;
    }

    const toMeters = (value: number, unit: DistanceUnit) => {
      if (unit === 'm') return value;
      if (unit === 'km') return value * 1000;
      if (unit === 'yd') return value * METERS_PER_YARD;
      return value * METERS_PER_MILE; // mi
    };
    const fromMeters = (meters: number, unit: DistanceUnit) => {
      if (unit === 'm') return { value: String(Math.round(meters)), step: 'int' as const };
      if (unit === 'yd') return { value: String(Math.round(meters / METERS_PER_YARD)), step: 'int' as const };
      if (unit === 'km') return { value: Number((meters / 1000).toFixed(2)).toString(), step: 'dec' as const };
      return { value: Number((meters / METERS_PER_MILE).toFixed(2)).toString(), step: 'dec' as const };
    };

    const meters = toMeters(v, lastSwimDistanceUnit);
    form.distanceRaw = fromMeters(meters, swimDistanceUnit).value;
    lastSwimDistanceUnit = swimDistanceUnit;
  });

  function effectiveDistanceUnit(sport: unknown): DistanceUnit {
    const base = distanceUnitForSport(sport);
    if (base === 'm') return 'm';
    if (isSwimSport(sport)) return swimDistanceUnit;
    return base as Exclude<DistanceUnit, 'm' | 'yd'>;
  }

  function formatDistanceInput(distanceM: unknown, sport: unknown) {
    const meters = Number(distanceM);
    if (!Number.isFinite(meters) || meters <= 0) return '';

    const unit = effectiveDistanceUnit(sport);
    if (unit === 'm') return String(Math.round(meters));
    if (unit === 'yd') return String(Math.round(meters / METERS_PER_YARD));
    const value = unit === 'mi' ? meters / 1609.34 : meters / 1000;
    return Number(value.toFixed(2)).toString();
  }

  function defaultFormValues(): ActivityFormValues {
    return {
      sport: 'run',
      date: todayStr(),
      startTime: currentTimeStr(),
      durationHrs: 0,
      durationMins: 30,
      title: '',
      distanceRaw: '',
      avgHr: '',
      maxHr: '',
      avgPowerW: '',
      normPowerW: ''
    };
  }

  function workoutFormValues(w: any): ActivityFormValues {
    const started = w?.started_at ? new Date(w.started_at) : new Date();
    const startedAt = Number.isNaN(started.getTime()) ? new Date() : started;
    const durationMinutes = Math.max(1, Math.round(getWorkoutDurationSecs(w) / 60));

    return {
      sport: w?.sport || 'run',
      date: formatDateInput(startedAt),
      startTime: formatTimeInput(startedAt),
      durationHrs: Math.floor(durationMinutes / 60),
      durationMins: durationMinutes % 60,
      title: w?.title ?? '',
      distanceRaw: formatDistanceInput(w?.distance_m, w?.sport),
      avgHr: formatOptionalNumber(w?.avg_hr),
      maxHr: formatOptionalNumber(w?.max_hr),
      avgPowerW: formatOptionalNumber(w?.avg_power_w ?? w?.average_watts),
      normPowerW: formatOptionalNumber(w?.norm_power_w)
    };
  }

  function initialFormValues(): ActivityFormValues {
    return mode === 'edit' ? workoutFormValues(workout) : defaultFormValues();
  }

  let form = $state(initialFormValues());

  let saving = $state(false);
  let error = $state('');

  const isEditMode = $derived(mode === 'edit');
  const modalTitle = $derived(isEditMode ? 'Edit Activity' : 'Log Activity');
  const submitText = $derived(isEditMode ? 'Save Changes' : 'Log Activity');
  const totalDurationSecs = $derived((form.durationHrs || 0) * 3600 + (form.durationMins || 0) * 60);
  const distanceUnit = $derived(effectiveDistanceUnit(form.sport));
  const distanceLabel = $derived(distanceUnit);
  const distanceStep = $derived(distanceUnit === 'm' || distanceUnit === 'yd' ? 1 : 0.01);
  const distancePlaceholder = $derived(distanceUnit === 'm' || distanceUnit === 'yd' ? '0' : '0.00');
  const distanceInputMode = $derived(distanceUnit === 'm' || distanceUnit === 'yd' ? 'numeric' : 'decimal');

  const canSubmit = $derived(!saving);

  function resetForm() {
    form = defaultFormValues();
    swimDistanceUnit = units === 'imperial' ? 'yd' : 'm';
    error = '';
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  function isBlankOptionalNumber(value: NumericInputValue) {
    const raw = String(value ?? '').trim();
    return raw.length === 0;
  }

  function parseOptionalPositiveInt(
    value: NumericInputValue,
    label: string,
    min: number,
    max: number
  ): OptionalNumberResult {
    if (isBlankOptionalNumber(value)) return { value: null, error: '' };

    const n = Number(String(value).trim());
    if (!Number.isFinite(n) || !Number.isInteger(n) || n < min || n > max) {
      return { value: null, error: `Enter a valid ${label}.` };
    }

    return { value: n, error: '' };
  }

  function parseDistanceM(): OptionalNumberResult {
    const raw = String(form.distanceRaw ?? '').trim();
    if (!raw) return { value: null, error: '' };

    const d = Number(raw);
    if (!Number.isFinite(d) || d <= 0) {
      return { value: null, error: `Enter a valid distance.` };
    }

    const unit = effectiveDistanceUnit(form.sport);
    const distanceM =
      unit === 'm' ? d : unit === 'yd' ? d * METERS_PER_YARD : unit === 'mi' ? d * 1609.34 : d * 1000;
    return { value: Math.round(distanceM), error: '' };
  }

  function parseRequiredDate() {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(form.date);
    if (!match) return { value: null, error: 'Enter a valid date.' };

    const [, yearRaw, monthRaw, dayRaw] = match;
    const year = Number(yearRaw);
    const month = Number(monthRaw);
    const day = Number(dayRaw);
    const date = new Date(year, month - 1, day);
    const isCalendarDate =
      date.getFullYear() === year &&
      date.getMonth() === month - 1 &&
      date.getDate() === day;
    // In edit mode the existing workout's UTC timestamp may display as a
    // local date that differs from todayStr(), so skip the future-date guard.
    const isValid = isCalendarDate && (isEditMode || date <= new Date());

    return isValid ? { value: { year, month, day }, error: '' } : { value: null, error: 'Enter a valid date.' };
  }

  function parseRequiredTime() {
    const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(form.startTime);
    if (!match) return { value: null, error: 'Enter a valid start time.' };

    return { value: { hrs: Number(match[1]), mins: Number(match[2]) }, error: '' };
  }

  function validateDuration() {
    const hrs = Number(form.durationHrs);
    const mins = Number(form.durationMins);
    const isValid =
      Number.isInteger(hrs) &&
      Number.isInteger(mins) &&
      hrs >= 0 &&
      hrs <= 23 &&
      mins >= 0 &&
      mins <= 59 &&
      totalDurationSecs >= 60;

    return isValid ? '' : 'Enter a valid duration.';
  }

  function getBadNumberInputError(formElement: HTMLFormElement) {
    for (const { id, error } of NUMBER_INPUT_VALIDATION) {
      const input = formElement.querySelector<HTMLInputElement>(`#${id}`);
      if (input?.validity.badInput) return error;
    }

    return '';
  }

  function assignOptionalPayloadValue(
    payload: Record<string, unknown>,
    key: string,
    value: unknown,
    includeNull: boolean
  ) {
    if (value !== null && value !== '') {
      payload[key] = value;
    } else if (includeNull) {
      payload[key] = null;
    }
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = '';

    if (saving) return;

    const formElement = e.currentTarget as HTMLFormElement;
    const badNumberInputError = getBadNumberInputError(formElement);
    if (badNumberInputError) {
      error = badNumberInputError;
      return;
    }

    if (!form.sport) {
      error = 'Choose an activity type.';
      return;
    }

    const date = parseRequiredDate();
    if (date.error || !date.value) {
      error = date.error;
      return;
    }

    const time = parseRequiredTime();
    if (time.error || !time.value) {
      error = time.error;
      return;
    }

    const durationError = validateDuration();
    if (durationError) {
      error = durationError;
      return;
    }

    const distanceM = parseDistanceM();
    if (distanceM.error) {
      error = distanceM.error;
      return;
    }

    const avgHr = parseOptionalPositiveInt(form.avgHr, 'average heart rate', 40, 220);
    if (avgHr.error) {
      error = avgHr.error;
      return;
    }

    const maxHr = parseOptionalPositiveInt(form.maxHr, 'max heart rate', 40, 240);
    if (maxHr.error) {
      error = maxHr.error;
      return;
    }

    const avgPowerW = parseOptionalPositiveInt(form.avgPowerW, 'average watts', 1, 2000);
    if (avgPowerW.error) {
      error = avgPowerW.error;
      return;
    }

    const normPowerW = parseOptionalPositiveInt(form.normPowerW, 'normalized power', 1, 2000);
    if (normPowerW.error) {
      error = normPowerW.error;
      return;
    }

    // Build UTC datetimes from local date + time strings
    const { year, month, day } = date.value;
    const { hrs, mins } = time.value;
    const startedAt = new Date(year, month - 1, day, hrs, mins, 0, 0);
    const endedAt = new Date(startedAt.getTime() + totalDurationSecs * 1000);

    const payload: Record<string, unknown> = {
      sport: form.sport,
      started_at: startedAt.toISOString(),
      ended_at: endedAt.toISOString(),
      duration_seconds: totalDurationSecs,
    };
    if (!isEditMode) payload.source = 'manual';

    const includeNulls = isEditMode;
    assignOptionalPayloadValue(payload, 'title', form.title.trim() || null, includeNulls);
    assignOptionalPayloadValue(payload, 'distance_m', distanceM.value, includeNulls);
    assignOptionalPayloadValue(payload, 'avg_hr', avgHr.value, includeNulls);
    assignOptionalPayloadValue(payload, 'max_hr', maxHr.value, includeNulls);
    assignOptionalPayloadValue(payload, 'avg_power_w', avgPowerW.value, includeNulls);
    assignOptionalPayloadValue(payload, 'norm_power_w', normPowerW.value, includeNulls);

    saving = true;
    try {
      await onSaved(payload);
      resetForm();
      onClose();
    } catch {
      error = 'Failed to save activity. Please try again.';
    } finally {
      saving = false;
    }
  }
</script>

<Modal {show} title={modalTitle} onClose={handleClose}>
  <form novalidate onsubmit={handleSubmit} class="flex flex-col gap-4">
    {#if error}
      <p class="text-[11px] text-red font-medium">{error}</p>
    {/if}

    <div>
      <label for="act-sport" class="block text-[11px] text-text2 mb-1">Activity Type</label>
      <DropdownSelect
        id="act-sport"
        bind:value={form.sport}
        options={SPORT_OPTIONS}
        ariaLabel="Activity type"
        buttonClass="p-2.5 text-sm"
      />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label for="act-date" class="block text-[11px] text-text2 mb-1">Date</label>
        <DatePicker
          id="act-date"
          bind:value={form.date}
          max={isEditMode ? undefined : todayStr()}
          ariaLabel="Activity date"
          buttonClass="p-2.5 text-sm"
        />
      </div>
      <div>
        <label for="act-time" class="block text-[11px] text-text2 mb-1">Start Time</label>
        <TimePicker
          id="act-time"
          bind:value={form.startTime}
          ariaLabel="Activity start time"
          buttonClass="p-2.5 text-sm"
          minuteStep={1}
        />
      </div>
    </div>

    <fieldset>
      <legend class="block text-[11px] text-text2 mb-1">Duration</legend>
      <div class="flex gap-2 items-center">
        <div class="flex-1 relative">
          <input
            id="act-duration-hrs"
            type="number"
            min="0"
            max="23"
            bind:value={form.durationHrs}
            class="w-full p-2.5 pr-8 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
          />
          <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-text2 pointer-events-none">hr</span>
        </div>
        <div class="flex-1 relative">
          <input
            id="act-duration-mins"
            type="number"
            min="0"
            max="59"
            bind:value={form.durationMins}
            class="w-full p-2.5 pr-8 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
          />
          <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-text2 pointer-events-none">min</span>
        </div>
      </div>
      {#if totalDurationSecs > 0 && totalDurationSecs < 60}
        <p class="text-[10px] text-red mt-1">Minimum duration is 1 minute.</p>
      {/if}
    </fieldset>

    <div>
      <label for="act-title" class="block text-[11px] text-text2 mb-1">
        Title <span class="text-text2 opacity-60">(optional)</span>
      </label>
      <input
        id="act-title"
        type="text"
        bind:value={form.title}
        placeholder="e.g. Morning Run"
        maxlength={100}
        class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
      />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label for="act-distance" class="block text-[11px] text-text2 mb-1">
          Distance ({distanceLabel}) <span class="text-text2 opacity-60">(optional)</span>
        </label>
        <input
          id="act-distance"
          type="number"
          min="0"
          step={distanceStep}
          inputmode={distanceInputMode}
          bind:value={form.distanceRaw}
          placeholder={distancePlaceholder}
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
        />
        {#if isSwimSport(form.sport)}
          <div class="mt-2 flex justify-end">
            <DropdownSelect
              id="act-distance-unit"
              bind:value={swimDistanceUnit}
              ariaLabel="Swim distance unit"
              options={units === 'imperial'
                ? [
                    { value: 'yd', label: 'Yards' },
                    { value: 'mi', label: 'Miles' }
                  ]
                : [
                    { value: 'm', label: 'Meters' },
                    { value: 'km', label: 'Kilometers' }
                  ]}
              align="right"
              buttonClass="px-2 py-1 text-[11px] font-semibold rounded-full bg-glass border border-border/70 hover:border-blue/60 focus:border-blue/80 transition-colors"
              popoverClass="w-[132px]"
            />
          </div>
        {/if}
      </div>
      <div>
        <label for="act-hr" class="block text-[11px] text-text2 mb-1">
          Avg HR (bpm) <span class="text-text2 opacity-60">(optional)</span>
        </label>
        <input
          id="act-hr"
          type="number"
          min="40"
          max="220"
          bind:value={form.avgHr}
          placeholder="--"
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
        />
      </div>
      <div>
        <label for="act-avg-watts" class="block text-[11px] text-text2 mb-1">
          Average Watts <span class="text-text2 opacity-60">(optional)</span>
        </label>
        <input
          id="act-avg-watts"
          type="number"
          min="1"
          max="2000"
          bind:value={form.avgPowerW}
          placeholder="--"
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
        />
      </div>
      <div>
        <label for="act-max-hr" class="block text-[11px] text-text2 mb-1">
          Max HR (bpm) <span class="text-text2 opacity-60">(optional)</span>
        </label>
        <input
          id="act-max-hr"
          type="number"
          min="40"
          max="240"
          bind:value={form.maxHr}
          placeholder="--"
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
        />
      </div>
      <div>
        <label for="act-norm-power" class="block text-[11px] text-text2 mb-1">
          Normalized Power <span class="text-text2 opacity-60">(optional)</span>
        </label>
        <input
          id="act-norm-power"
          type="number"
          min="1"
          max="2000"
          bind:value={form.normPowerW}
          placeholder="--"
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
        />
      </div>
    </div>

    <button
      type="submit"
      disabled={!canSubmit}
      class="w-full py-3 bg-blue text-white text-sm font-semibold rounded-xl hover:bg-blue/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed mt-1"
    >
      {saving ? (isEditMode ? 'Saving Changes…' : 'Logging Activity…') : submitText}
    </button>
  </form>
</Modal>
