<script lang="ts">
  /** A length typed as m:ss ("1:30", "90:00"), h:mm:ss ("1:30:00") or plain minutes ("90"). Tidied to m:ss on blur. */
  import { formatMinSec, parseMinSec } from '$lib/utils/planEditor';

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
  let invalid = $state(false);
  let focused = false;

  $effect(() => {
    // Follow outside changes (a new draft) while not typing.
    const v = value;
    if (!focused) text = formatMinSec(v);
  });

  function oninput() {
    const v = parseMinSec(text);
    invalid = v === null;
    if (v !== null) value = v;
  }

  function onblur() {
    focused = false;
    if (!invalid) text = formatMinSec(value);
  }
</script>

<input
  type="text"
  inputmode="decimal"
  autocomplete="off"
  aria-label={ariaLabel}
  aria-invalid={invalid}
  placeholder="m:ss"
  bind:value={text}
  {oninput}
  onfocus={() => (focused = true)}
  {onblur}
  class="{cls} {invalid ? '!border-red' : ''}"
/>
