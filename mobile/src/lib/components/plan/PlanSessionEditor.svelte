<script lang="ts">
  /**
   * Edit a planned session by hand: name, date, sport, zone, length, notes, and its blocks
   * (minutes:seconds, zone, optional %FTP), including an "add interval set" helper.
   * Strength / mobility have no blocks: one easy block for the whole session is saved.
   */
  import Modal from '$lib/components/Modal.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import DropdownSelect from '$lib/components/DropdownSelect.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import type { Workout } from '$lib/types/training';
  import { formatStepDuration } from '$lib/utils/stepDuration';
  import {
    SPORTS,
    ZONES,
    draftErrors,
    draftMinutes,
    estimateTss,
    fromDraft,
    hasBlocks,
    intervalSet,
    moveBlock,
    newBlock,
    toDraft,
    type Draft
  } from '$lib/utils/planEditor';

  let {
    workout,
    onSave,
    onClose
  }: {
    /** The session to edit; null closes the editor. */
    workout: Workout | null;
    /** Saves; resolves false when the save failed. */
    onSave: (w: Workout) => Promise<boolean>;
    onClose: () => void;
  } = $props();

  let draft = $state<Draft | null>(null);
  let saving = $state(false);
  let error = $state<string | null>(null);
  let showSet = $state(false);
  let set = $state({ reps: 6, workMin: 3, workSec: 0, workZone: 5, restMin: 2, restSec: 0 });

  $effect(() => {
    // A fresh draft each time the editor opens on a session.
    draft = workout ? toDraft(workout) : null;
    error = null;
    showSet = false;
  });

  const blocksOn = $derived(!!draft && hasBlocks(draft.sport));
  const total = $derived(draft ? draftMinutes(draft) : 0);
  const tss = $derived(draft ? estimateTss(draft) : 0);
  const zoneOptions = ZONES.map((z) => ({ value: z.value, label: z.label }));
  const blockZoneOptions = [{ value: '0', label: '—' }, ...[1, 2, 3, 4, 5].map((z) => ({ value: String(z), label: `Z${z}` }))];

  function addBlock() {
    if (!draft) return;
    draft.blocks = [...draft.blocks, newBlock('Step', 10, 2)];
  }

  function addSet() {
    if (!draft) return;
    const work = (Number(set.workMin) || 0) + (Number(set.workSec) || 0) / 60;
    const rest = (Number(set.restMin) || 0) + (Number(set.restSec) || 0) / 60;
    if (work <= 0) return;
    draft.blocks = [...draft.blocks, ...intervalSet(Number(set.reps), work, Number(set.workZone), rest)];
    showSet = false;
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (!draft || !workout || saving) return;
    const problems = draftErrors(draft);
    if (problems.length) {
      error = problems[0];
      return;
    }
    saving = true;
    error = null;
    try {
      const ok = await onSave(fromDraft(draft, workout));
      if (ok) onClose();
      else error = "Couldn't save the session. Try again.";
    } finally {
      saving = false;
    }
  }

  const field = 'w-full p-2.5 bg-glass2 border border-border rounded-lg text-sm text-text0 outline-none focus:border-blue';
  const num = 'w-full p-2 bg-glass2 border border-border rounded-lg text-sm text-text0 font-mono outline-none focus:border-blue text-center';
  const label = 'block text-[11px] text-text2 mb-1';
  const iconBtn =
    'w-8 h-8 shrink-0 rounded-lg border border-border bg-transparent text-text2 cursor-pointer hover:text-text0 hover:border-text3 disabled:opacity-30 disabled:cursor-default flex items-center justify-center';
</script>

<Modal show={!!workout && !!draft} title="Edit session" {onClose}>
  {#if draft}
    <form novalidate onsubmit={save} class="flex flex-col gap-4">
      {#if error}
        <p role="alert" class="m-0 text-[12px] text-red font-medium">{error}</p>
      {/if}

      <div>
        <label for="pse-title" class={label}>Name</label>
        <input id="pse-title" type="text" maxlength={120} bind:value={draft.title} class={field} />
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label for="pse-date" class={label}>Date</label>
          <DatePicker id="pse-date" bind:value={draft.date} ariaLabel="Session date" buttonClass="p-2.5 text-sm" />
        </div>
        <div>
          <label for="pse-sport" class={label}>Sport</label>
          <DropdownSelect id="pse-sport" bind:value={draft.sport} options={SPORTS} ariaLabel="Sport" buttonClass="p-2.5 text-sm" />
        </div>
      </div>

      {#if blocksOn}
        <div>
          <label for="pse-zone" class={label}>Main intensity</label>
          <DropdownSelect id="pse-zone" bind:value={draft.zone} options={zoneOptions} ariaLabel="Main intensity" buttonClass="p-2.5 text-sm" />
        </div>
      {/if}

      {#if !blocksOn || draft.blocks.length === 0}
        <fieldset class="m-0 p-0 border-0">
          <legend class={label}>Length</legend>
          <div class="flex gap-2">
            <div class="flex-1 relative">
              <input type="number" min="0" max="10" inputmode="numeric" aria-label="Hours" bind:value={draft.hours} class="{field} font-mono pr-8" />
              <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-text2 pointer-events-none">hr</span>
            </div>
            <div class="flex-1 relative">
              <input type="number" min="0" max="59" inputmode="numeric" aria-label="Minutes" bind:value={draft.mins} class="{field} font-mono pr-9" />
              <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-text2 pointer-events-none">min</span>
            </div>
          </div>
          {#if !blocksOn}
            <p class="m-0 mt-1.5 text-[11px] text-text2">Saved as one easy block for the whole session.</p>
          {/if}
        </fieldset>
      {/if}

      {#if blocksOn}
        <fieldset class="m-0 p-0 border-0 flex flex-col gap-2">
          <legend class={label}>Blocks</legend>
          {#if draft.blocks.length > 0}
            <div class="grid grid-cols-[minmax(0,1fr)_3.25rem_3.25rem_4.25rem_3.75rem_auto] gap-1.5 items-center text-[10px] font-mono text-text2 uppercase tracking-[0.08em] px-0.5" aria-hidden="true">
              <span>Step</span><span class="text-center">min</span><span class="text-center">sec</span><span class="text-center">Zone</span><span class="text-center">%FTP</span><span></span>
            </div>
          {/if}
          {#each draft.blocks as b, i (b.key)}
            <div class="grid grid-cols-[minmax(0,1fr)_3.25rem_3.25rem_4.25rem_3.75rem_auto] gap-1.5 items-center">
              <input type="text" aria-label="Block {i + 1} name" bind:value={b.name} class="{field} !p-2 min-w-0" />
              <input type="number" min="0" max="600" inputmode="numeric" aria-label="Block {i + 1} minutes" bind:value={b.minutes} class={num} />
              <input type="number" min="0" max="59" inputmode="numeric" aria-label="Block {i + 1} seconds" bind:value={b.seconds} class={num} />
              <select
                aria-label="Block {i + 1} zone"
                value={String(b.zone)}
                onchange={(e) => (b.zone = Number((e.currentTarget as HTMLSelectElement).value))}
                class="{num} !px-1 appearance-none"
                style={b.zone > 0 ? `border-color: var(--zone-${b.zone})` : ''}
              >
                {#each blockZoneOptions as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
              </select>
              <input type="number" min="0" max="300" inputmode="numeric" placeholder="—" aria-label="Block {i + 1} percent of FTP" bind:value={b.ftp} class={num} />
              <span class="flex gap-1">
                <button type="button" class={iconBtn} aria-label="Move block {i + 1} up" disabled={i === 0} onclick={() => draft && (draft.blocks = moveBlock(draft.blocks, i, i - 1))}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 15 6-6 6 6"></path></svg>
                </button>
                <button type="button" class={iconBtn} aria-label="Move block {i + 1} down" disabled={i === draft.blocks.length - 1} onclick={() => draft && (draft.blocks = moveBlock(draft.blocks, i, i + 1))}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>
                </button>
                <button type="button" class={iconBtn} aria-label="Remove block {i + 1}" onclick={() => draft && (draft.blocks = draft.blocks.filter((x) => x.key !== b.key))}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"></path></svg>
                </button>
              </span>
            </div>
          {/each}

          {#if showSet}
            <div class="flex flex-col gap-2 p-3 rounded-xl border border-border bg-bg2">
              <span class="text-[12px] text-text1">Interval set</span>
              <div class="flex flex-wrap items-center gap-1.5 text-[12px] text-text2">
                <input type="number" min="1" max="50" aria-label="Repeats" bind:value={set.reps} class="{num} !w-14" />
                <span>×</span>
                <input type="number" min="0" aria-label="Work minutes" bind:value={set.workMin} class="{num} !w-14" />
                <span>:</span>
                <input type="number" min="0" max="59" aria-label="Work seconds" bind:value={set.workSec} class="{num} !w-14" />
                <select aria-label="Work zone" bind:value={set.workZone} class="{num} !w-16 !px-1 appearance-none">
                  {#each [1, 2, 3, 4, 5] as z (z)}<option value={z}>Z{z}</option>{/each}
                </select>
                <span>rest</span>
                <input type="number" min="0" aria-label="Rest minutes" bind:value={set.restMin} class="{num} !w-14" />
                <span>:</span>
                <input type="number" min="0" max="59" aria-label="Rest seconds" bind:value={set.restSec} class="{num} !w-14" />
              </div>
              <div class="flex gap-2">
                <Button size="sm" full={false} onclick={addSet}>Add set</Button>
                <Button size="sm" full={false} variant="ghost" onclick={() => (showSet = false)}>Cancel</Button>
              </div>
            </div>
          {/if}

          <div class="flex gap-2">
            <Button size="sm" full={false} variant="secondary" onclick={addBlock}>Add block</Button>
            {#if !showSet}
              <Button size="sm" full={false} variant="secondary" onclick={() => (showSet = true)}>Add interval set</Button>
            {/if}
          </div>
        </fieldset>
      {/if}

      <div>
        <label for="pse-notes" class={label}>Notes</label>
        <textarea id="pse-notes" rows="4" bind:value={draft.notes} class="{field} resize-y min-h-[88px] leading-relaxed"></textarea>
      </div>

      <div class="flex items-center justify-between gap-3 pt-1">
        <span class="font-mono text-[12px] text-text2">{formatStepDuration(total)} · {tss} TSS</span>
        <span class="flex gap-2">
          <Button size="sm" full={false} variant="ghost" onclick={onClose}>Cancel</Button>
          <Button size="sm" full={false} type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
        </span>
      </div>
    </form>
  {/if}
</Modal>
