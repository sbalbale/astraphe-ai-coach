<script lang="ts">
  /** "Check it works": sends one test push to this account's devices. */
  let {
    enabled,
    device,
    sending = false,
    result = null,
    onsend
  }: {
    enabled: boolean;
    device: string;
    sending?: boolean;
    result?: { text: string; ok: boolean } | null;
    onsend: () => void;
  } = $props();
</script>

<section aria-label="Test notification" class="bg-bg2 border border-border rounded-[24px] p-4 flex flex-col gap-2.5">
  <span class="text-[13px] leading-normal text-text1">
    {enabled ? `Sends one notification to ${device} right now. Quiet hours are skipped for tests.` : 'Turn on push above to send a test.'}
  </span>
  <button
    type="button"
    disabled={!enabled || sending}
    class="min-h-11 px-4 rounded-xl text-sm font-semibold {enabled ? 'border-0 bg-blue text-on-accent cursor-pointer disabled:opacity-60' : 'border border-border bg-transparent text-text3 cursor-default'}"
    onclick={onsend}
  >{sending ? 'Sending…' : 'Send a test notification'}</button>
  {#if result}
    <span role="status" class="text-[12px] {result.ok ? 'text-green' : 'text-amber'}">{result.text}</span>
  {/if}
</section>
