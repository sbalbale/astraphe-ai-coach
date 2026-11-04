<script lang="ts">
  /** One-tap replies under the coach's latest message ("Felt good", "Legs were heavy"). */
  let {
    replies,
    disabled = false,
    onPick
  }: { replies: string[]; disabled?: boolean; onPick: (text: string) => void } = $props();
</script>

{#if replies.length > 0}
  <ul aria-label="Quick replies" class="list-none m-0 p-0 flex gap-2 overflow-x-auto pb-0.5 [scrollbar-width:none]">
    {#each replies as q (q)}
      <li class="flex-none">
        <button
          type="button"
          {disabled}
          class="h-10 px-3.5 rounded-full border border-accent-surface-border bg-accent-surface text-text0 text-[14px] font-medium cursor-pointer disabled:opacity-50 disabled:cursor-default hover:border-blue/60"
          onclick={() => onPick(q)}
        >{q}</button>
      </li>
    {/each}
  </ul>
{/if}
