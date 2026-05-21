<script lang="ts">
  import Modal from './Modal.svelte';

  let {
    show,
    onClose,
    onSaved,
  }: {
    show: boolean;
    onClose: () => void;
    onSaved: (payload: object) => Promise<void>;
  } = $props();

  function yesterdayStr() {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  let nightOf = $state(yesterdayStr());
  let bedtime = $state('22:00');
  let wakeTime = $state('06:30');

  let saving = $state(false);
  let error = $state('');

  function computeTimes(): { bedtimeDt: Date; wakeupDt: Date; durationMin: number } | null {
    const [by, bm, bd] = nightOf.split('-').map(Number);
    const [bhrs, bmins] = bedtime.split(':').map(Number);
    const [whrs, wmins] = wakeTime.split(':').map(Number);

    const bedtimeDt = new Date(by, bm - 1, bd, bhrs, bmins, 0, 0);
    // Wake time on next day if wake hour <= bedtime hour (crosses midnight)
    const sameDay = whrs > bhrs || (whrs === bhrs && wmins > bmins);
    const wakeDate = sameDay ? new Date(by, bm - 1, bd) : new Date(by, bm - 1, bd + 1);
    const wakeupDt = new Date(wakeDate.getFullYear(), wakeDate.getMonth(), wakeDate.getDate(), whrs, wmins, 0, 0);

    const durationMin = Math.round((wakeupDt.getTime() - bedtimeDt.getTime()) / 60000);
    return { bedtimeDt, wakeupDt, durationMin };
  }

  const computed = $derived(computeTimes());
  const durationMin = $derived(computed?.durationMin ?? 0);

  function formatDuration(mins: number) {
    if (mins <= 0) return '--';
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  const canSubmit = $derived(
    nightOf.length === 10 &&
    bedtime.length === 5 &&
    wakeTime.length === 5 &&
    durationMin >= 30 &&
    durationMin <= 720 &&
    !saving
  );

  function resetForm() {
    nightOf = yesterdayStr();
    bedtime = '22:00';
    wakeTime = '06:30';
    error = '';
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    if (!canSubmit || !computed) return;
    error = '';

    const { bedtimeDt, wakeupDt, durationMin: durMin } = computed;
    // date = wake-up date (calendar day the sleep ended on)
    const wakeDate = wakeupDt;
    const dateStr = `${wakeDate.getFullYear()}-${String(wakeDate.getMonth() + 1).padStart(2, '0')}-${String(wakeDate.getDate()).padStart(2, '0')}`;

    const payload = {
      date: dateStr,
      source: 'manual',
      sleep_bedtime: bedtimeDt.toISOString(),
      sleep_wakeup: wakeupDt.toISOString(),
      sleep_duration_min: durMin,
      sleep_in_bed_min: durMin,
    };

    saving = true;
    try {
      await onSaved(payload);
      resetForm();
      onClose();
    } catch {
      error = 'Failed to save sleep entry. Please try again.';
    } finally {
      saving = false;
    }
  }
</script>

<Modal {show} title="Log Sleep" onClose={handleClose}>
  <form onsubmit={handleSubmit} class="flex flex-col gap-4">
    {#if error}
      <p class="text-[11px] text-red font-medium">{error}</p>
    {/if}

    <div>
      <label for="sleep-night" class="block text-[11px] text-text2 mb-1">Night of</label>
      <input
        id="sleep-night"
        type="date"
        bind:value={nightOf}
        max={todayStr()}
        class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
      />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label for="sleep-bedtime" class="block text-[11px] text-text2 mb-1">Bedtime</label>
        <input
          id="sleep-bedtime"
          type="time"
          bind:value={bedtime}
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
        />
      </div>
      <div>
        <label for="sleep-wake" class="block text-[11px] text-text2 mb-1">Wake time</label>
        <input
          id="sleep-wake"
          type="time"
          bind:value={wakeTime}
          class="w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue"
        />
      </div>
    </div>

    <div class="px-3 py-2.5 bg-glass2 border border-border rounded-xl">
      <p class="text-[10px] text-text2 font-mono uppercase tracking-wide mb-0.5">Duration</p>
      <p class="text-sm font-semibold text-text0 tabular-nums">{formatDuration(durationMin)}</p>
      {#if durationMin > 0 && durationMin < 30}
        <p class="text-[10px] text-red mt-1">Duration seems too short (min 30 min).</p>
      {:else if durationMin > 720}
        <p class="text-[10px] text-red mt-1">Duration over 12 hours — check your times.</p>
      {/if}
    </div>

    <button
      type="submit"
      disabled={!canSubmit}
      class="w-full py-3 bg-blue text-white text-sm font-semibold rounded-xl hover:bg-blue/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed mt-1"
    >
      {saving ? 'Saving…' : 'Log Sleep'}
    </button>
  </form>
</Modal>
