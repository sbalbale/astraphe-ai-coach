<script lang="ts" module>
  export type SetupStep = {
    title: string;
    detail: string;
    done: boolean;
    actionLabel?: string;
    onAction?: () => void;
  };
</script>

<script lang="ts">
  import Button from '$lib/components/ui/Button.svelte';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';

  /** New-account checklist on Today (design: empty states, page 1). */
  let { steps }: { steps: SetupStep[] } = $props();

  const doneCount = $derived(steps.filter((s) => s.done).length);
  /** The first unfinished step is the current one (sky ring + its action). */
  const currentIndex = $derived(steps.findIndex((s) => !s.done));
</script>

<section aria-labelledby="setup-title" class="bg-bg2 border border-border rounded-card px-6 pt-7 pb-2">
  <div class="flex items-baseline justify-between">
    <h2 id="setup-title" class="font-display text-[32px] leading-none text-text0 m-0">Get set up</h2>
    <span class="font-mono text-[12px] tracking-[0.14em] text-text2">{doneCount} OF {steps.length}</span>
  </div>
  <div class="flex gap-1.5 mt-5 mb-1" aria-hidden="true">
    {#each steps as s, i (i)}
      <div class="h-1 flex-1 rounded-full {s.done ? 'bg-blue' : 'bg-bg3'}"></div>
    {/each}
  </div>

  <ol class="list-none m-0 p-0">
    {#each steps as s, i (i)}
      {@const current = i === currentIndex}
      <li class="flex items-center gap-4 py-5 border-t border-border first:mt-4">
        {#if s.done}
          <span class="w-10 h-10 shrink-0 rounded-full bg-green-dim text-green flex items-center justify-center" aria-hidden="true">
            <UiIcon name="check" size={18} strokeWidth={2} />
          </span>
        {:else}
          <span
            class="w-10 h-10 shrink-0 rounded-full border flex items-center justify-center font-mono text-[15px] {current ? 'border-blue text-blue' : 'border-border text-text2'}"
            aria-hidden="true">{i + 1}</span>
        {/if}
        <div class="flex-1 min-w-0">
          <p class="m-0 text-[17px] font-medium {s.done ? 'text-text2 line-through' : 'text-text0'}">
            {s.title}<span class="sr-only">{s.done ? ' (done)' : ''}</span>
          </p>
          <p class="m-0 text-[15px] text-text2 leading-snug mt-0.5">{s.done ? 'Done' : s.detail}</p>
        </div>
        {#if current && s.actionLabel && s.onAction}
          <Button size="sm" full={false} onclick={s.onAction}>{s.actionLabel}</Button>
        {/if}
      </li>
    {/each}
  </ol>
</section>
