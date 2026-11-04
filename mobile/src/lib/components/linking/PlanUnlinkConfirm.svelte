<script lang="ts">
  /** "Unlink <workout>?" confirmation (design: Plan · link a workout, unlink sheet). */
  import { modalDialog } from '$lib/actions/modalDialog';
  import type { LinkSource } from '$lib/types/linking';
  import { unlinkText } from '$lib/utils/linking';

  let {
    workoutTitle,
    source,
    wide = false,
    busy = false,
    oncancel,
    onconfirm
  }: {
    workoutTitle: string;
    source: LinkSource | null | undefined;
    wide?: boolean;
    busy?: boolean;
    oncancel: () => void;
    onconfirm: () => void;
  } = $props();
</script>

<div
  class="fixed inset-0 z-[70] flex {wide ? 'items-center justify-center p-8' : 'flex-col justify-end'}"
  role="presentation"
>
  <button type="button" aria-label="Cancel" class="absolute inset-0 border-0 bg-black/55 cursor-default" onclick={oncancel}></button>
  <div
    role="alertdialog"
    use:modalDialog={{ onEscape: oncancel }}
    aria-modal="true"
    aria-labelledby="unlink-title"
    class="relative flex flex-col gap-3.5 bg-popover border-popover-border text-text0 {wide ? 'w-full max-w-[440px] rounded-[24px] border p-6' : 'rounded-t-[28px] border-t px-5 pt-2.5'}"
    style={wide ? undefined : 'padding-bottom: max(28px, env(safe-area-inset-bottom, 0px));'}
  >
    {#if !wide}<span aria-hidden="true" class="self-center w-10 h-[5px] rounded-sm bg-border"></span>{/if}
    <h2 id="unlink-title" class="m-0 font-display font-normal text-[28px] leading-tight">Unlink {workoutTitle}?</h2>
    <p class="m-0 text-[14px] leading-[1.55] text-text1">{unlinkText(source)}</p>
    <div class="grid grid-cols-2 gap-2">
      <button type="button" class="h-12 rounded-[14px] border border-popover-border bg-transparent text-text0 text-[15px] font-medium cursor-pointer" onclick={oncancel}>Cancel</button>
      <!-- svelte-ignore a11y_autofocus -->
      <button
        type="button"
        autofocus
        disabled={busy}
        class="h-12 rounded-[14px] border-0 bg-red text-bg0 text-[15px] font-semibold cursor-pointer disabled:opacity-50"
        onclick={onconfirm}
      >{busy ? 'Unlinking…' : 'Unlink'}</button>
    </div>
  </div>
</div>
