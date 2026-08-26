<script lang="ts">
  let {
    value = $bindable(''),
    disabled = false,
    id = 'otp-code'
  }: {
    value?: string;
    disabled?: boolean;
    id?: string;
  } = $props();

  function handleInput(e: Event) {
    const target = e.currentTarget as HTMLInputElement;
    value = target.value.replace(/\D/g, '').slice(0, 6);
  }
</script>

<input
  {id}
  type="text"
  inputmode="numeric"
  pattern="[0-9]*"
  maxlength="6"
  autocomplete="one-time-code"
  {disabled}
  {value}
  oninput={handleInput}
  placeholder="000000"
  class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text0 font-mono text-2xl tracking-[0.5em] text-center outline-none focus:border-teal focus:bg-glass2 transition-colors placeholder:text-text2 disabled:opacity-50"
/>
