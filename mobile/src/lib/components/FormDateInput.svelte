<script lang="ts">
  let {
    id,
    type = 'date',
    value = $bindable(),
    max,
    disabled = false,
    ariaLabel,
    inputClass = '',
    wrapperClass = ''
  }: {
    id: string;
    type?: 'date' | 'month';
    value: string;
    max?: string;
    disabled?: boolean;
    ariaLabel?: string;
    inputClass?: string;
    wrapperClass?: string;
  } = $props();

  const base =
    'w-full bg-glass2 border border-border rounded-lg text-text0 outline-none focus:border-blue disabled:opacity-50 appearance-none';
</script>

<div class={"relative " + wrapperClass}>
  <input
    {id}
    {type}
    bind:value
    {disabled}
    max={max}
    aria-label={ariaLabel}
    class={base + ' ' + (inputClass || 'p-2.5 pr-9 text-sm')}
  />

  <div class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 opacity-70">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M7 10l5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </div>
</div>

