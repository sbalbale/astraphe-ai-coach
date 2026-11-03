<script lang="ts">
  /** On/off switch (accent track with a dark knob when on), as used across the settings screens. */
  let {
    checked,
    label,
    disabled = false,
    onchange
  }: {
    checked: boolean;
    /** Accessible name; the visible label usually sits beside the switch. */
    label: string;
    disabled?: boolean;
    onchange?: (next: boolean) => void;
  } = $props();
</script>

<button
  type="button"
  role="switch"
  aria-checked={checked}
  aria-label={label}
  {disabled}
  class="relative shrink-0 w-[60px] h-[34px] rounded-full border-0 p-0 transition-colors duration-200 disabled:opacity-50 {checked ? 'bg-blue cursor-pointer' : 'bg-bg3 cursor-pointer'}"
  onclick={() => onchange?.(!checked)}
>
  <span
    aria-hidden="true"
    class="absolute top-[4px] w-[26px] h-[26px] rounded-full transition-all duration-200 {checked ? 'left-[30px] bg-bg0' : 'left-[4px] bg-text2'}"
  ></span>
</button>
