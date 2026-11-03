<script lang="ts">
  /**
   * Wide Today: the coach's note for today plus quick prompts. Chips and the composer open
   * the coach with the question in the composer (/chat?prompt=…) rather than answering inline.
   */
  import { resolve } from '$app/paths';
  import { navTo } from '$lib/nav';

  let { note, fill = false }: { note: string; fill?: boolean } = $props();

  const CHIPS = ['Legs feel heavy', 'Only have 45 min', 'What should I eat?'];
  let question = $state('');

  function ask(text: string) {
    const q = text.trim();
    if (!q) return;
    navTo(`/chat?prompt=${encodeURIComponent(q.slice(0, 2000))}`);
  }

  function submit(e: SubmitEvent) {
    e.preventDefault();
    ask(question);
  }
</script>

<section
  aria-label="Coach"
  class="bg-bg1 border border-border rounded-[24px] p-5 flex flex-col gap-3 min-h-0 {fill ? 'flex-1' : 'h-full'}"
>
  <div class="flex justify-between items-center">
    <span class="flex items-center gap-2 font-mono text-[11px] tracking-[0.14em] text-blue">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"></path></svg>
      COACH
    </span>
    <a href={resolve('/chat')} class="text-[12px] text-text1 no-underline hover:text-text0">Open full chat</a>
  </div>
  <div class="flex-1 min-h-0 overflow-y-auto">
    <p class="m-0 text-[15px] leading-[1.55] text-text0/90">{note}</p>
  </div>
  <div class="flex flex-wrap gap-2">
    {#each CHIPS as c (c)}
      <button
        type="button"
        class="h-[34px] px-3 rounded-[17px] border border-popover-border bg-transparent text-text0/80 text-[13px] cursor-pointer hover:border-text3 hover:text-text0"
        onclick={() => ask(c)}
      >{c}</button>
    {/each}
  </div>
  <form onsubmit={submit} class="flex gap-2 items-center py-1.5 pr-1.5 pl-3.5 rounded-2xl bg-bg2 border border-border">
    <label for="today-coach-q" class="sr-only">Ask your coach</label>
    <input
      id="today-coach-q"
      bind:value={question}
      autocomplete="off"
      placeholder="Ask your coach…"
      class="flex-1 min-w-0 h-9 border-0 bg-transparent text-text0 text-[14px] outline-none placeholder:text-text3"
    />
    <button
      type="submit"
      aria-label="Send"
      class="w-10 h-10 rounded-xl border-0 bg-blue text-on-accent flex items-center justify-center cursor-pointer disabled:opacity-50"
      disabled={!question.trim()}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"></path></svg>
    </button>
  </form>
</section>
