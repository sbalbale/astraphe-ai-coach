<script lang="ts">
  /** Coach texts (Photon) are being replaced by push: stop them, or turn them back on. */
  let {
    texts,
    debriefOn,
    disabled = false,
    onchange
  }: {
    texts: 'active' | 'off';
    debriefOn: boolean;
    disabled?: boolean;
    onchange: (next: 'active' | 'off') => void;
  } = $props();
</script>

<section aria-label="Text messages" class="bg-bg2 border border-border rounded-[24px] p-4 flex flex-col gap-2.5">
  {#if texts === 'active'}
    <span class="text-[15px] font-medium">Coach texts are moving to the app</span>
    <span class="text-[13px] leading-normal text-text1">
      If your coach texts you after workouts, those texts are being replaced. Debriefs now arrive as a push that opens a coach chat, so you can reply in the app. Stop the texts whenever you're ready.
    </span>
  {:else}
    <span class="text-[15px] font-medium">Texts are off</span>
    <span class="text-[13px] leading-normal text-text1">
      No more coach texts. Debriefs arrive as push notifications{debriefOn ? '.' : ' — turn on Post-workout debrief to get them.'}
    </span>
  {/if}
  <div class="flex gap-2 flex-wrap">
    <button
      type="button"
      {disabled}
      class="min-h-11 px-4 rounded-xl border border-popover-border bg-transparent text-text0 text-sm font-medium cursor-pointer disabled:opacity-50"
      onclick={() => onchange(texts === 'active' ? 'off' : 'active')}
    >{texts === 'active' ? 'Stop texts now' : 'Turn texts back on'}</button>
  </div>
</section>
