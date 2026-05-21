<script lang="ts">
  import Modal from './Modal.svelte';
  import FormSelect from './FormSelect.svelte';

  let {
    show,
    onClose,
    units = 'metric',
    onSaved,
  }: {
    show: boolean;
    onClose: () => void;
    units?: 'metric' | 'imperial';
    onSaved: (payload: object) => Promise<void>;
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

  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function currentTimeStr() {
    const d = new Date();
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  let sport = $state('run');
  let date = $state(todayStr());
  let startTime = $state(currentTimeStr());
  let durationHrs = $state(0);
  let durationMins = $state(30);
  let title = $state('');
  let distanceRaw = $state('');
  let avgHr = $state('');

  let saving = $state(false);
  let error = $state('');

  const totalDurationSecs = $derived(durationHrs * 3600 + durationMins * 60);
  const distanceLabel = $derived(units === 'imperial' ? 'mi' : 'km');

  const canSubmit = $derived(
    sport.length > 0 &&
    date.length === 10 &&
    startTime.length === 5 &&
    totalDurationSecs >= 60 &&
    !saving
  );

  function resetForm() {
    sport = 'run';
    date = todayStr();
    startTime = currentTimeStr();
    durationHrs = 0;
    durationMins = 30;
    title = '';
    distanceRaw = '';
    avgHr = '';
    error = '';
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    if (!canSubmit) return;
    error = '';

    // Build UTC datetimes from local date + time strings
    const [year, month, day] = date.split('-').map(Number);
    const [hrs, mins] = startTime.split(':').map(Number);
    const startedAt = new Date(year, month - 1, day, hrs, mins, 0, 0);
    const endedAt = new Date(startedAt.getTime() + totalDurationSecs * 1000);

    let distanceM: number | null = null;
    if (distanceRaw) {
      const d = parseFloat(distanceRaw);
      if (Number.isFinite(d) && d > 0) {
        distanceM = units === 'imperial' ? d * 1609.34 : d * 1000;
      }
    }

    const payload: Record<string, unknown> = {
      source: 'manual',
      sport,
      started_at: startedAt.toISOString(),
      ended_at: endedAt.toISOString(),
      duration_seconds: totalDurationSecs,
    };
    if (title.trim()) payload.title = title.trim();
    if (distanceM !== null) payload.distance_m = Math.round(distanceM);
    if (avgHr) {
      const hr = parseInt(avgHr, 10);
      if (hr > 0) payload.avg_hr = hr;
    }

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

<Modal {show} title="Log Activity" onClose={handleClose}>
  <form onsubmit={handleSubmit} class="flex flex-col gap-4">
    {#if error}
      <p class="text-[11px] text-red font-medium">{error}</p>
    {/if}

    <div>
      <label for="act-sport" class="block text-[11px] text-text2 mb-1">Activity Type</label>
      <FormSelect id="act-sport" bind:value={sport} options={SPORT_OPTIONS} />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label for="act-date" class="block text-[11px] text-text2 mb-1">Date</label>
        <input
          id="act-date"
          type="date"
          bind:value={date}
          max={todayStr()}
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
        />
      </div>
      <div>
        <label for="act-time" class="block text-[11px] text-text2 mb-1">Start Time</label>
        <input
          id="act-time"
          type="time"
          bind:value={startTime}
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
        />
      </div>
    </div>

    <div>
      <label class="block text-[11px] text-text2 mb-1">Duration</label>
      <div class="flex gap-2 items-center">
        <div class="flex-1 relative">
          <input
            type="number"
            min="0"
            max="23"
            bind:value={durationHrs}
            class="w-full p-2.5 pr-8 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
          />
          <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-text2 pointer-events-none">hr</span>
        </div>
        <div class="flex-1 relative">
          <input
            type="number"
            min="0"
            max="59"
            bind:value={durationMins}
            class="w-full p-2.5 pr-8 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
          />
          <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-text2 pointer-events-none">min</span>
        </div>
      </div>
      {#if totalDurationSecs > 0 && totalDurationSecs < 60}
        <p class="text-[10px] text-red mt-1">Minimum duration is 1 minute.</p>
      {/if}
    </div>

    <div>
      <label for="act-title" class="block text-[11px] text-text2 mb-1">
        Title <span class="text-text2 opacity-60">(optional)</span>
      </label>
      <input
        id="act-title"
        type="text"
        bind:value={title}
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
          step="0.1"
          bind:value={distanceRaw}
          placeholder="0.0"
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue"
        />
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
          bind:value={avgHr}
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
      {saving ? 'Saving…' : 'Log Activity'}
    </button>
  </form>
</Modal>
