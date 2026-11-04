<script lang="ts">
  /** Quiet hours: switch plus From / Until times (saved when a time is committed). */
  import ToggleSwitch from '$lib/components/ToggleSwitch.svelte';

  let {
    on,
    from,
    to,
    note,
    disabled = false,
    ontoggle,
    onchange
  }: {
    on: boolean;
    from: string;
    to: string;
    note: string;
    disabled?: boolean;
    ontoggle: () => void;
    onchange: (from: string, to: string) => void;
  } = $props();

  const field = 'h-11 px-3 rounded-xl border border-popover-border bg-bg1 text-text0 text-[15px] [color-scheme:dark] outline-none focus:border-blue';
</script>

<section aria-label="Quiet hours" class="bg-bg2 border border-border rounded-[24px] px-4 py-3.5 flex flex-col gap-3">
  <div class="flex items-center gap-3.5">
    <span class="flex-1 flex flex-col gap-[3px]">
      <span class="text-[15px] font-medium">Quiet hours</span>
      <span class="text-[12px] leading-[1.45] text-text2">{note}</span>
    </span>
    <ToggleSwitch label="Quiet hours" checked={on} {disabled} onchange={ontoggle} />
  </div>
  {#if on}
    <div class="grid grid-cols-2 gap-2">
      <label class="flex flex-col gap-1 text-[11px] text-text2">
        From
        <input type="time" value={from} {disabled} class={field} onchange={(e) => e.currentTarget.value && onchange(e.currentTarget.value, to)} />
      </label>
      <label class="flex flex-col gap-1 text-[11px] text-text2">
        Until
        <input type="time" value={to} {disabled} class={field} onchange={(e) => e.currentTarget.value && onchange(from, e.currentTarget.value)} />
      </label>
    </div>
  {/if}
</section>
