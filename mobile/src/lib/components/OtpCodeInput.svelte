<script lang="ts">
  /**
   * Six-box verification code. Visually six cells, but one real <input> laid over
   * them, so paste, SMS/email autofill (autocomplete="one-time-code") and screen
   * readers all see a single field. The cells just mirror `value`.
   */
  let {
    value = $bindable(''),
    disabled = false,
    id = 'otp-code',
  }: {
    value?: string;
    disabled?: boolean;
    id?: string;
  } = $props();

  const LENGTH = 6;
  let focused = $state(false);

  function handleInput(e: Event) {
    const target = e.currentTarget as HTMLInputElement;
    value = target.value.replace(/\D/g, '').slice(0, LENGTH);
    // Keep the field showing exactly what we accepted (letters/extra digits dropped).
    target.value = value;
  }

  const cells = $derived(Array.from({ length: LENGTH }, (_, i) => value[i] ?? ''));
  // The cell the next digit goes into (the last one once full).
  const activeIndex = $derived(Math.min(value.length, LENGTH - 1));
</script>

<div class="relative">
  <div class="grid grid-cols-6 gap-3" aria-hidden="true">
    {#each cells as digit, i (i)}
      <div
        class="h-[72px] rounded-[18px] bg-bg2 flex items-center justify-center font-mono text-[28px] text-text0 transition-colors
          {focused && i === activeIndex ? 'border-2 border-blue' : 'border border-border'} {disabled ? 'opacity-50' : ''}"
      >
        {digit}
      </div>
    {/each}
  </div>
  <input
    {id}
    type="text"
    inputmode="numeric"
    pattern="[0-9]*"
    maxlength={LENGTH}
    autocomplete="one-time-code"
    {disabled}
    {value}
    oninput={handleInput}
    onfocus={() => (focused = true)}
    onblur={() => (focused = false)}
    class="absolute inset-0 w-full h-full bg-transparent text-transparent caret-transparent border-none outline-none selection:bg-transparent cursor-text disabled:cursor-not-allowed"
  />
</div>
