<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLInputAttributes } from 'svelte/elements';

  /** Labelled input in the auth / settings style: label above, 56px field, sky focus border. */
  let {
    id,
    label,
    value = $bindable(''),
    hint,
    labelAside,
    mono = false,
    class: className = '',
    ...rest
  }: {
    id: string;
    label: string;
    value?: string | number | null;
    hint?: string;
    labelAside?: Snippet;
    mono?: boolean;
    class?: string;
  } & Omit<HTMLInputAttributes, 'value' | 'id' | 'class'> = $props();
</script>

<div class={className}>
  <div class="flex items-baseline justify-between mb-2">
    <label for={id} class="text-[14px] text-text2">
      {label}
      {#if hint}<span class="block text-text2/80 text-[13px] mt-0.5">{hint}</span>{/if}
    </label>
    {#if labelAside}{@render labelAside()}{/if}
  </div>
  <input
    {id}
    bind:value
    {...rest}
    class="w-full h-14 px-5 bg-bg2 border border-border rounded-[18px] text-text0 text-[16px] outline-none transition-colors placeholder:text-text2/70 focus:border-blue {mono ? 'font-mono' : ''}"
  />
</div>
