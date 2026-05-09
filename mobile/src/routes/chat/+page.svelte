<script lang="ts">
  import { api } from '$lib/api';
  import { renderCoachMarkdownToSafeHtml } from '$lib/coachMarkdown';
  import { buildMergedCoachPromptSuggestions } from '$lib/coachPromptSuggestions';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { confirm } from '$lib/confirm';
  import { format } from 'date-fns';
  import { tick } from 'svelte';

  type Conversation = { id: string; title?: string | null; created_at?: string; updated_at?: string };
  type Message = {
    id: string;
    role: 'user' | 'ai';
    text: string;
    image_urls?: string[];
    created_at?: string;
    streaming?: boolean;
  };
  
  const initialText = $derived(`Hey ${authStore.user?.user_metadata?.full_name?.split(' ')[0] || 'there'}! I'm your ASTRAPE Coach. ${athleteStore.ctl > 0 ? `I've analyzed your current fitness (CTL: ${Math.round(athleteStore.ctl)}).` : "Link your data so I can start analyzing your training."} How can I help you today?`);
  
  let conversations = $state<Conversation[]>([]);
  let conversationId = $state<string | null>(null);
  let messages = $state<Message[]>([]);
  
  let input = $state('');
  let loading = $state(false);
  let pendingImageUrls = $state<string[]>([]);
  let chatContainer: HTMLElement;
  let fileInput: HTMLInputElement | null = null;
  let chatInputEl = $state<HTMLTextAreaElement | null>(null);

  const CHAT_INPUT_MAX_PX = 200;

  function resizeChatInput() {
    const el = chatInputEl;
    if (!el) return;
    el.style.height = '0px';
    const next = Math.min(el.scrollHeight, CHAT_INPUT_MAX_PX);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > CHAT_INPUT_MAX_PX ? 'auto' : 'hidden';
  }

  $effect(() => {
    void input;
    tick().then(() => resizeChatInput());
  });
  let convoMenuOpen = $state(false);
  let convoMenuEl = $state<HTMLElement | null>(null);
  let historyLoaded = $state(false);
  let historyLoading = $state(false);

  async function loadConversationMessages(cid: string) {
    const res = await api.getCoachMessages(cid);
    const rows = res?.messages || [];
    if (!rows.length) {
      // Conversation exists but has no messages yet (new chat)
      messages = [{ id: 'local-greeting', role: 'ai', text: initialText }];
    } else {
      messages = rows.map((m: any) => ({
        id: String(m.id),
        role: m.role === 'user' ? 'user' : 'ai',
        text: String(m.content ?? ''),
        image_urls: Array.isArray(m.image_urls) ? m.image_urls : [],
        created_at: m.created_at
      }));
    }
    await scrollToBottom();
  }

  function currentConversationTitle() {
    const c = conversations.find((x) => x.id === conversationId);
    return c?.title || 'New chat';
  }

  async function loadInitialHistory() {
    if (historyLoading || historyLoaded) return;
    historyLoading = true;
    try {
      const res = await api.getCoachConversations();
      conversations = res?.conversations || [];
      const latest = conversations[0]?.id;
      if (latest) {
        conversationId = latest;
        await loadConversationMessages(latest);
        historyLoaded = true;
        return;
      }
      messages = [{ id: 'local-greeting', role: 'ai', text: initialText }];
      historyLoaded = true;
    } finally {
      historyLoading = false;
    }
  }

  async function ensureConversation() {
    if (conversationId) return conversationId;
    const created = await api.createCoachConversation();
    const cid = created?.conversation?.id;
    if (cid) {
      conversationId = cid;
      conversations = [{ id: cid, title: created?.conversation?.title }, ...conversations];
      return cid as string;
    }
    conversationId = null;
    return null;
  }

  async function newChat() {
    loading = false;
    input = '';
    pendingImageUrls = [];
    const created = await api.createCoachConversation();
    const cid = created?.conversation?.id;
    if (!cid) return;
    conversationId = cid;
    conversations = [{ id: cid, title: created?.conversation?.title }, ...conversations];
    messages = [{ id: 'local-greeting', role: 'ai', text: initialText }];
    await scrollToBottom();
  }

  async function selectConversation(cid: string) {
    conversationId = cid;
    convoMenuOpen = false;
    await loadConversationMessages(cid);
  }

  async function deleteConversation(cid: string) {
    const c = conversations.find((x) => x.id === cid);
    const label = c?.title || 'this chat';
    const ok = await confirm({
      title: 'Delete chat?',
      message: `Delete “${label}”? This cannot be undone.`,
      confirmText: 'Delete',
      cancelText: 'Cancel',
      confirmTone: 'danger'
    });
    if (!ok) return;

    try {
      loading = true;
      await api.deleteCoachConversation(cid);
    } finally {
      loading = false;
    }

    conversations = conversations.filter((x) => x.id !== cid);

    if (conversationId === cid) {
      const next = conversations[0]?.id ?? null;
      conversationId = next;
      if (next) {
        await loadConversationMessages(next);
      } else {
        // no chats left; reset UI
        messages = [{ id: 'local-greeting', role: 'ai', text: initialText }];
      }
    }
  }

  async function pickImage() {
    const cid = await ensureConversation();
    if (!cid) return;
    fileInput?.click();
  }

  async function onFilesSelected(e: Event) {
    const inputEl = e.currentTarget as HTMLInputElement;
    const files = Array.from(inputEl.files || []);
    inputEl.value = '';
    if (files.length === 0) return;

    const cid = await ensureConversation();
    if (!cid) return;

    try {
      loading = true;
      for (const f of files) {
        const url = await api.uploadCoachImage(f, cid);
        pendingImageUrls = [...pendingImageUrls, url];
      }
    } catch (err) {
      console.warn('Image upload failed', err);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    // Keep the greeting in sync if it's still the first message.
    if (messages.length === 0) return;
    const first = messages[0];
    if (first?.id !== 'local-greeting' || first.role !== 'ai') return;
    if (first.text !== initialText) first.text = initialText;
  });

  $effect(() => {
    if (!authStore.user) return;
    if (!historyLoaded && !historyLoading) loadInitialHistory();
  });

  async function scrollToBottom() {
    await tick();
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }

  const todayStr = $derived(format(new Date(), 'yyyy-MM-dd'));
  const biometricSeries = $derived(athleteStore.biometrics?.series ?? []);
  const todayBio = $derived(biometricSeries.find((s: { date?: string }) => s.date === todayStr));
  const latestBio = $derived(
    biometricSeries.length ? biometricSeries[biometricSeries.length - 1] : undefined
  );
  const contextSleepScore = $derived<number | null>(
    typeof todayBio?.sleep_score === 'number' && Number.isFinite(todayBio.sleep_score)
      ? Number(todayBio.sleep_score)
      : typeof latestBio?.sleep_score === 'number' && Number.isFinite(latestBio.sleep_score)
        ? Number(latestBio.sleep_score)
        : null
  );
  const todayHrvZ = $derived(
    typeof todayBio?.hrv_z === 'number' && Number.isFinite(todayBio.hrv_z) ? Number(todayBio.hrv_z) : null
  );
  const contextHrvZ = $derived(
    todayHrvZ ??
      (typeof latestBio?.hrv_z === 'number' && Number.isFinite(latestBio.hrv_z)
        ? Number(latestBio.hrv_z)
        : null)
  );

  const recentTurnsForSuggestions = $derived(
    messages
      .filter((m) => !(m.streaming && !m.text.trim()))
      .filter((m) => m.text.trim())
      .map((m) => ({ role: m.role, text: m.text }))
  );

  const promptSuggestions = $derived(
    buildMergedCoachPromptSuggestions({
      ctl: athleteStore.ctl,
      tsb: athleteStore.tsb,
      sleepScore: contextSleepScore,
      hrvZScore: contextHrvZ,
      recentMessages: recentTurnsForSuggestions
    })
  );

  const userInitials = $derived.by(() => {
    const meta = authStore.user?.user_metadata as Record<string, unknown> | undefined;
    const name = typeof meta?.full_name === 'string' ? meta.full_name.trim() : '';
    if (name) {
      const parts = name.split(/\s+/).filter(Boolean);
      if (parts.length >= 2) {
        return `${parts[0]![0]!}${parts[parts.length - 1]![0]!}`.toUpperCase();
      }
      return parts[0]!.slice(0, 2).toUpperCase();
    }
    const email = authStore.user?.email?.trim();
    if (email) return email.slice(0, 2).toUpperCase();
    return 'Me';
  });

  $effect(() => {
    const onDocDown = (e: MouseEvent) => {
      if (!convoMenuOpen) return;
      const t = e.target as Node | null;
      if (convoMenuEl && t && convoMenuEl.contains(t)) return;
      convoMenuOpen = false;
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') convoMenuOpen = false;
    };

    document.addEventListener('mousedown', onDocDown);
    window.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDocDown);
      window.removeEventListener('keydown', onEsc);
    };
  });

  async function send() {
    const text = input.trim();
    if (!text && pendingImageUrls.length === 0) return;
    
    input = '';
    await tick();
    resizeChatInput();
    const cid = await ensureConversation();
    const image_urls = pendingImageUrls;
    pendingImageUrls = [];

    const userMsg: Message = { id: `local-user-${Date.now()}`, role: 'user', text, image_urls };
    messages.push(userMsg);
    loading = true;
    scrollToBottom();

    const aiMsgId = `local-ai-${Date.now()}`;
    messages.push({ id: aiMsgId, role: 'ai', text: '', streaming: true });
    
    try {
      const data = await api.sendCoachMessage({
        message: text || '(image)',
        recent_tss: athleteStore.recent_tss,
        conversation_id: cid,
        image_urls
      });
      if (data.conversation_id) conversationId = data.conversation_id;
      const msgIndex = messages.findIndex((m) => m.id === aiMsgId);
      if (msgIndex !== -1) {
        messages[msgIndex].text = data.reply ?? '';
      }
      scrollToBottom();
    } catch (e) {
      const msgIndex = messages.findIndex(m => m.id === aiMsgId);
      if (msgIndex !== -1) {
        messages[msgIndex].text = "Sorry, I had trouble connecting to the coaching engine.";
      }
    } finally {
      const msgIndex = messages.findIndex(m => m.id === aiMsgId);
      if (msgIndex !== -1) {
        messages[msgIndex].streaming = false;
      }
      loading = false;
      // Refresh conversation titles (auto-named on backend after first message)
      try {
        const res = await api.getCoachConversations();
        conversations = res?.conversations || conversations;
      } catch {}
    }
  }

</script>

<div class="flex flex-col h-full min-h-0 w-full box-border">
  <div
    class="w-full h-full flex flex-col flex-1 min-h-0 rounded-none border-0 bg-slate-900/35 overflow-hidden"
  >
    <!-- Mockup header -->
    <div class="shrink-0 px-4 pt-4 pb-3 flex items-center justify-between gap-3 border-b border-slate-800/80">
      <span class="text-[11px] sm:text-xs tracking-wide font-semibold text-slate-400">Astrape AI Coach Chat</span>
      <div class="flex items-center gap-1.5 shrink-0">
        <span
          class="inline-flex h-2 w-2 rounded-full bg-teal animate-pulse shadow-[0_0_10px_rgba(0,200,168,0.55)]"
          aria-hidden="true"
        ></span>
        <span class="text-[11px] uppercase tracking-wider font-semibold text-astrape-teal">Live</span>
      </div>
    </div>

    <!-- History controls -->
    <div class="shrink-0 px-4 py-2 flex items-center justify-end gap-2 border-b border-slate-800/60 bg-slate-950/25">
      {#if conversations.length > 0}
        <div class="relative flex-1 min-w-0 max-w-[220px]" bind:this={convoMenuEl}>
          <button
            type="button"
            class="w-full bg-slate-800/40 border border-slate-700 rounded-xl text-[11px] text-slate-200 pl-3 pr-8 py-2 outline-none truncate text-left hover:bg-slate-800/60 transition-colors"
            onclick={() => { convoMenuOpen = !convoMenuOpen; }}
            aria-label="Select chat"
          >
            {currentConversationTitle()}
          </button>
          <div class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 text-[10px]">▼</div>

          {#if convoMenuOpen}
            <div
              class="absolute left-0 right-0 mt-2 max-w-[min(100vw-2rem,320px)] bg-slate-900/95 backdrop-blur border border-slate-700 rounded-2xl shadow-2xl overflow-hidden z-20"
            >
              <div class="max-h-[320px] overflow-y-auto">
                {#each conversations as c (c.id)}
                  <div
                    class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-slate-800/50 transition-colors cursor-pointer {c.id === conversationId ? 'bg-slate-800/35' : ''}"
                    role="button"
                    tabindex="0"
                    onclick={() => selectConversation(c.id)}
                    onkeydown={(e) => e.key === 'Enter' && selectConversation(c.id)}
                  >
                    <div class="flex-1 min-w-0">
                      <div class="text-[12px] text-slate-200 truncate">{c.title || 'New chat'}</div>
                      <div class="text-[10px] text-slate-500 truncate">{c.updated_at || c.created_at || ''}</div>
                    </div>
                    <button
                      type="button"
                      class="w-8 h-8 rounded-lg bg-slate-800/70 border border-slate-600 text-slate-300 hover:text-red-400 transition-colors flex items-center justify-center shrink-0"
                      onclick={(e) => { e.stopPropagation(); deleteConversation(c.id); }}
                      aria-label="Delete chat"
                      title="Delete"
                    >
                      🗑
                    </button>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {/if}
      <button
        type="button"
        class="px-3 py-1.5 rounded-lg text-[11px] bg-slate-800/40 border border-slate-700 text-slate-300 hover:bg-slate-800/65 transition-colors shrink-0"
        onclick={newChat}
      >
        New
      </button>
    </div>

    <div
      class="flex-1 overflow-y-auto flex flex-col gap-3 px-4 py-3 min-h-0"
      bind:this={chatContainer}
    >
      {#each messages as msg (msg.id)}
        {#if msg.role === 'ai'}
          <div class="flex gap-2.5 items-end justify-start">
            <div
              class="w-8 h-8 shrink-0 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-[9px] font-bold tracking-wide text-teal select-none"
              aria-hidden="true"
            >
              AI
            </div>
            <div
              class="max-w-[min(92%,28rem)] px-[14px] py-[10px] text-[13px] leading-[1.55] text-slate-100 rounded-2xl rounded-bl-md border border-slate-700/80 bg-slate-800/60"
            >
              {#if msg.image_urls && msg.image_urls.length > 0}
                <div class="flex gap-2 flex-wrap mb-2">
                  {#each msg.image_urls as u (u)}
                    <a href={u} target="_blank" rel="noreferrer noopener" class="block">
                      <img
                        src={u}
                        alt="upload"
                        class="w-24 h-24 object-cover rounded-lg border border-slate-600/80"
                      />
                    </a>
                  {/each}
                </div>
              {/if}
              {#if msg.streaming && !msg.text.trim()}
                <div class="flex items-center gap-2 text-slate-400">
                  <div class="flex gap-1">
                    <div class="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce"></div>
                    <div class="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:150ms]"></div>
                    <div class="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:300ms]"></div>
                  </div>
                  <span class="text-[12px]">Thinking…</span>
                </div>
              {:else}
                <div class="chat-md">{@html renderCoachMarkdownToSafeHtml(msg.text)}</div>
              {/if}
            </div>
          </div>
        {:else}
          <div class="flex gap-2.5 items-end justify-end">
            <div
              class="max-w-[min(92%,28rem)] px-[14px] py-[10px] text-[13px] leading-[1.55] text-slate-100 rounded-2xl rounded-br-md border border-indigo-500/30 bg-indigo-900/40"
            >
              {#if msg.image_urls && msg.image_urls.length > 0}
                <div class="flex gap-2 flex-wrap mb-2 justify-end">
                  {#each msg.image_urls as u (u)}
                    <a href={u} target="_blank" rel="noreferrer noopener" class="block">
                      <img
                        src={u}
                        alt="upload"
                        class="w-24 h-24 object-cover rounded-lg border border-indigo-500/25"
                      />
                    </a>
                  {/each}
                </div>
              {/if}
              {msg.text}
            </div>
            <div
              class="w-8 h-8 shrink-0 rounded-full bg-slate-950 border border-slate-700 flex items-center justify-center text-[10px] font-semibold text-slate-400 select-none uppercase"
              aria-hidden="true"
            >
              {userInitials}
            </div>
          </div>
        {/if}
      {/each}
    </div>

    <div class="shrink-0 px-4 pt-2 pb-1 border-t border-slate-800/60 bg-slate-950/20">
      <div class="flex gap-2 overflow-x-auto pb-2 scrollbar-thin">
        {#each promptSuggestions as s, i (s + String(i))}
          <button
            type="button"
            class="whitespace-nowrap shrink-0 px-3 py-2 rounded-xl text-sm text-slate-300 bg-slate-800/50 hover:bg-slate-700/80 border border-slate-700 transition-colors text-left cursor-pointer font-sans"
            onclick={() => { input = s; }}
          >
            {s}
          </button>
        {/each}
      </div>

      {#if pendingImageUrls.length > 0}
        <div class="flex gap-2 flex-wrap pb-2">
          {#each pendingImageUrls as u (u)}
            <div class="relative">
              <img
                src={u}
                alt="pending upload"
                class="w-16 h-16 object-cover rounded-lg border border-slate-700"
              />
              <button
                class="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-slate-900 border border-slate-600 text-slate-300 text-[12px] flex items-center justify-center hover:border-slate-500"
                onclick={() => { pendingImageUrls = pendingImageUrls.filter(x => x !== u); }}
                aria-label="Remove image"
                type="button"
              >
                ✕
              </button>
            </div>
          {/each}
        </div>
      {/if}

      <div class="flex gap-2 items-end pb-4">
        <input
          bind:this={fileInput}
          type="file"
          accept="image/*"
          multiple
          class="hidden"
          onchange={onFilesSelected}
        />
        <button
          type="button"
          class="w-10 h-10 rounded-xl shrink-0 text-slate-300 text-[17px] flex items-center justify-center transition-colors border border-slate-700 bg-slate-900 hover:bg-slate-800 disabled:opacity-40"
          disabled={loading}
          onclick={pickImage}
          aria-label="Attach image"
        >
          ＋
        </button>
        <textarea
          bind:this={chatInputEl}
          bind:value={input}
          rows="1"
          maxlength="8000"
          aria-label="Message"
          oninput={resizeChatInput}
          onkeydown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (!loading) void send();
            }
          }}
          placeholder="Ask your coach... (Shift+Enter for new line)"
          class="flex-1 min-w-0 min-h-[2.75rem] max-h-[200px] px-4 py-3 rounded-xl text-[13px] leading-snug bg-slate-900 border border-slate-700 text-slate-100 placeholder:text-slate-500 font-sans outline-none focus:border-slate-500 focus:ring-1 focus:ring-slate-600/80 resize-none overflow-hidden"
        ></textarea>
        <button
          type="button"
          class="w-11 h-11 shrink-0 rounded-xl flex items-center justify-center transition-all bg-indigo-600 hover:bg-indigo-500 disabled:opacity-35 disabled:pointer-events-none text-white shadow-[0_8px_24px_-12px_rgba(79,70,229,0.9)]"
          disabled={loading || (!input.trim() && pendingImageUrls.length === 0)}
          onclick={send}
          aria-label="Send message"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M5 12h14m0 0l-6-6m6 6l-6 6"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </div>
    </div>
  </div>
</div>

<style>
  /* Markdown styles scoped to AI message bubbles */
  :global(.chat-md) {
    word-break: break-word;
  }
  :global(.chat-md :where(p, ul, ol, pre, blockquote)) {
    margin: 0.4rem 0;
  }
  :global(.chat-md :where(ul, ol)) {
    padding-left: 1.1rem;
  }
  :global(.chat-md :where(li)) {
    margin: 0.15rem 0;
  }
  :global(.chat-md :where(a)) {
    color: rgb(0 200 168);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  :global(.chat-md :where(code)) {
    font-size: 0.92em;
    padding: 0.12rem 0.3rem;
    border-radius: 0.45rem;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  :global(.chat-md :where(pre)) {
    overflow-x: auto;
    padding: 0.6rem 0.7rem;
    border-radius: 0.75rem;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  :global(.chat-md :where(pre code)) {
    padding: 0;
    border: 0;
    background: transparent;
  }

  /* KaTeX (inline + display) inherits bubble text color */
  :global(.chat-md .katex) {
    color: inherit;
    font-size: 1em;
  }
  :global(.chat-md .katex-display) {
    margin: 0.5rem 0;
    overflow-x: auto;
    overflow-y: hidden;
  }
</style>
