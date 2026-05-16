<script module lang="ts">
  export type SelectOption = { value: string; label: string };
</script>

<script lang="ts">
  let {
    id,
    value = $bindable(),
    options = [],
    disabled = false,
    ariaLabel,
    selectClass = '',
    wrapperClass = ''
  }: {
    id: string;
    value: string;
    options?: SelectOption[];
    disabled?: boolean;
    ariaLabel?: string;
    selectClass?: string;
    wrapperClass?: string;
  } = $props();

  const base =
    'w-full bg-glass2 border border-border rounded-lg text-text0 outline-none focus:border-blue appearance-none disabled:opacity-50';
</script>

<div class={"relative " + wrapperClass}>
  <select
    {id}
    bind:value
    {disabled}
    aria-label={ariaLabel}
    class={base + ' ' + (selectClass || 'p-2.5 pr-9 text-sm')}
  >
    {#each options as opt (opt.value)}
      <option value={opt.value}>{opt.label}</option>
    {/each}
  </select>

  <div class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 opacity-70">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M7 10l5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </div>
</div>

