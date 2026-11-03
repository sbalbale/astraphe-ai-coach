<script lang="ts">
  /** Wide Plan header: kicker + 44 px title, ‹ › arrows, Today, Week/Month switch. */
  type View = 'week' | 'month';
  let {
    kicker,
    title,
    view,
    atToday,
    onprev,
    onnext,
    ontoday,
    onview
  }: {
    kicker: string;
    title: string;
    view: View;
    atToday: boolean;
    onprev: () => void;
    onnext: () => void;
    ontoday: () => void;
    onview: (v: View) => void;
  } = $props();

  const unit = $derived(view === 'month' ? 'month' : 'week');
  const VIEWS: { id: View; label: string }[] = [
    { id: 'week', label: 'Week' },
    { id: 'month', label: 'Month' }
  ];
</script>

<header class="flex justify-between items-end gap-6">
  <div class="flex flex-col gap-1.5 min-w-0">
    <span class="font-mono text-[12px] tracking-[0.14em] text-text2 uppercase truncate">{kicker}</span>
    <h1 class="m-0 font-display font-normal text-[44px] leading-none truncate">{title}</h1>
  </div>
  <div class="flex gap-2 items-center shrink-0">
    <button
      type="button"
      aria-label="Previous {unit}"
      class="w-10 h-10 rounded-xl border border-border bg-bg2 text-text1 flex items-center justify-center cursor-pointer hover:text-text0"
      onclick={onprev}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
    </button>
    <button
      type="button"
      aria-label="Next {unit}"
      class="w-10 h-10 rounded-xl border border-border bg-bg2 text-text1 flex items-center justify-center cursor-pointer hover:text-text0"
      onclick={onnext}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
    </button>
    <button
      type="button"
      disabled={atToday}
      class="h-10 px-3.5 rounded-xl text-[13px] font-semibold {atToday ? 'bg-bg2 border border-border text-text3 cursor-default' : 'bg-blue border-0 text-on-accent cursor-pointer'}"
      onclick={ontoday}
    >Today</button>
    <div role="tablist" aria-label="View" class="flex gap-0.5 p-[3px] rounded-xl bg-bg2 border border-border">
      {#each VIEWS as v (v.id)}
        <button
          type="button"
          role="tab"
          aria-selected={view === v.id}
          class="h-[34px] px-3 border-0 rounded-[9px] text-[12px] font-medium cursor-pointer {view === v.id ? 'bg-border text-text0' : 'bg-transparent text-text2'}"
          onclick={() => onview(v.id)}
        >{v.label}</button>
      {/each}
    </div>
  </div>
</header>
