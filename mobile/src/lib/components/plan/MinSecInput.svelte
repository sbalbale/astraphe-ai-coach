<script lang="ts">
  /**
   * A length typed as digits that fill in from the right, like a timer: "30" = 0:30,
   * "130" = 1:30, "13000" = 1:30:00. The colons appear as you type (the number pad has
   * none). Tidied on blur: m:ss under 2 hours, h:mm:ss from 2 hours (so "90" becomes 1:30).
   */
  import { formatMinSec, formatTimeDigits, minutesToTimeDigits, timeDigits, timeDigitsToMinutes } from '$lib/utils/planEditor';

  let {
    value = $bindable(0),
    ariaLabel,
    class: cls = ''
  }: {
    /** Minutes (1:30 = 1.5). */
    value: number;
    ariaLabel: string;
    class?: string;
  } = $props();

  let text = $state(formatMinSec(value));
  let focused = false;

  $effect(() => {
    // Follow outside changes (a new draft) while not typing.
    const v = value;
    if (!focused) text = formatMinSec(v);
  });

  function oninput(e: Event) {
    const el = e.currentTarget as HTMLInputElement;
    const digits = timeDigits(el.value);
    text = formatTimeDigits(digits);
    el.value = text;
    // Digits are added and removed at the end, so keep the caret there.
    el.setSelectionRange(text.length, text.length);
    value = timeDigitsToMinutes(digits);
  }

  function onfocus(e: FocusEvent) {
    focused = true;
    const el = e.currentTarget as HTMLInputElement;
    text = formatTimeDigits(minutesToTimeDigits(value));
    el.value = text;
    requestAnimationFrame(() => el.setSelectionRange(text.length, text.length));
  }

  function onblur() {
    focused = false;
    text = formatMinSec(value);
  }
</script>

<input
  type="text"
  inputmode="numeric"
  pattern="[0-9]*"
  autocomplete="off"
  aria-label={ariaLabel}
  placeholder="0:00"
  value={text}
  {oninput}
  {onfocus}
  {onblur}
  class={cls}
/>
