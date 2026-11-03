<script lang="ts">
  /** Wide Coach, left pane: title, new chat, filter, past conversations (design: WCoach). */
  import { conversationWhen, filterConversations } from './coachContext';

  type Conversation = { id: string; title?: string | null; created_at?: string; updated_at?: string };

  let {
    conversations,
    activeId,
    disabled = false,
    onSelect,
    onNew,
    onDelete
  }: {
    conversations: Conversation[];
    activeId: string | null;
    disabled?: boolean;
    onSelect: (id: string) => void;
    onNew: () => void;
    onDelete: (id: string) => void;
  } = $props();

  let query = $state('');
  const shown = $derived(filterConversations(conversations, query));
</script>

<aside aria-label="Conversations" class="flex-none w-[260px] h-full box-border px-3.5 py-8 border-r border-rail-border flex flex-col gap-3 min-h-0">
  <div class="flex justify-between items-center px-1.5">
    <h1 class="m-0 font-display font-normal text-[32px] leading-none text-text0">Coach</h1>
    <button
      type="button"
      aria-label="New conversation"
      title="New conversation"
      class="w-9 h-9 rounded-[11px] border border-popover-border bg-transparent text-text0 flex items-center justify-center cursor-pointer hover:border-text3"
      onclick={onNew}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
    </button>
  </div>

  <label for="coach-convo-filter" class="sr-only">Filter conversations</label>
  <input
    id="coach-convo-filter"
    bind:value={query}
    placeholder="Filter conversations"
    autocomplete="off"
    class="h-9 px-3 rounded-[11px] border border-border bg-bg1 text-text0 text-[13px] outline-none focus:border-blue placeholder:text-text3"
  />

  <ul class="list-none m-0 p-0 flex flex-col gap-0.5 overflow-y-auto min-h-0">
    {#each shown as c (c.id)}
      {@const on = c.id === activeId}
      <li class="group relative">
        <button
          type="button"
          aria-pressed={on}
          {disabled}
          class="w-full min-h-[52px] pl-3 pr-10 py-2 rounded-xl border-0 flex flex-col items-start justify-center gap-0.5 text-left text-text0 cursor-pointer disabled:cursor-default {on ? 'bg-bg3' : 'bg-transparent hover:bg-bg2'}"
          onclick={() => onSelect(c.id)}
        >
          <span class="w-full text-[13px] font-medium truncate">{c.title || 'New chat'}</span>
          <span class="text-[11px] text-text2">{conversationWhen(c.updated_at || c.created_at)}</span>
        </button>
        <button
          type="button"
          aria-label="Delete “{c.title || 'New chat'}”"
          class="absolute right-1.5 top-1/2 -translate-y-1/2 w-8 h-8 rounded-lg border-0 bg-transparent text-text3 flex items-center justify-center cursor-pointer opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-red"
          onclick={() => onDelete(c.id)}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg>
        </button>
      </li>
    {:else}
      <li class="px-1.5 py-2 text-[13px] text-text2">{query.trim() ? 'No conversations match.' : 'No past conversations yet.'}</li>
    {/each}
  </ul>

  <span class="mt-auto px-1.5 text-[11px] leading-normal text-text3">The coach reads your workouts, plan, recovery and sleep from your connected apps.</span>
</aside>
