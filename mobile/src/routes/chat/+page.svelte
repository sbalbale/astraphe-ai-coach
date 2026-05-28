<script lang="ts">
  import { api } from '$lib/api';
  import { renderCoachMarkdownToSafeHtml, normalizeTypographyForWrap } from '$lib/coachMarkdown';
  import { buildMergedCoachPromptSuggestions } from '$lib/coachPromptSuggestions';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { confirm } from '$lib/confirm';
  import { format } from 'date-fns';
  import { tick } from 'svelte';
  import { isStandaloneDisplayMode } from '$lib/utils/pwa';
  import { normalizeLeadingTimeOfDayGreeting } from '$lib/utils/greeting';

  type Conversation = { id: string; title?: string | null; created_at?: string; updated_at?: string };
  type Message = {
    id: string;
    role: 'user' | 'ai';
    text: string;
    image_urls?: string[];
    created_at?: string;
    streaming?: boolean;
  };

  let greetingMessage = $state<string>('');
  
  const initialText = $derived(greetingMessage || `Hey ${authStore.user?.user_metadata?.full_name?.split(' ')[0] || 'there'}! I'm your ASTRAPHE Coach. ${athleteStore.ctl > 0 ? `I've analyzed your current fitness (CTL: ${Math.round(athleteStore.ctl)}).` : "Link your data so I can start analyzing your training."} How can I help you today?`);
  
  let conversations = $state<Conversation[]>([]);
  let conversationId = $state<string | null>(null);
  let messages = $state<Message[]>([]);
  let aiMemories = $state<string[]>([]);
  
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
      // 1. Load conversations list FIRST (so menu works immediately)
      const convoRes = await api.getCoachConversations();
      conversations = convoRes?.conversations || [];
      historyLoaded = true;

      // 2. Load initialization data in the background (greeting + memories)
      api.initializeCoach().then((initRes) => {
        if (initRes?.status === 'success' || initRes?.status === 'partial_success') {
          const message = typeof initRes.message === 'string' ? initRes.message : '';
          greetingMessage = message ? normalizeLeadingTimeOfDayGreeting(message) : '';
          aiMemories = initRes.memories || [];
          
          // If we are still in a new chat (no conversationId), update the greeting text
          if (!conversationId && messages.length > 0 && messages[0].id === 'local-greeting') {
            messages[0].text = initialText;
          }
        }
      }).catch(err => {
        console.warn("[coach.initialize] Failed in background:", err);
      });

      // Default to a new chat on first entry
      conversationId = null;
      messages = [{ id: 'local-greeting', role: 'ai', text: initialText }];
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
    conversationId = null;
    messages = [{ id: 'local-greeting', role: 'ai', text: initialText }];
    convoMenuOpen = false;
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
      recentMessages: recentTurnsForSuggestions,
      memories: aiMemories
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
      let accumulated = '';
      let inputUnlocked = false;
      const unlockInput = () => {
        if (inputUnlocked) return;
        inputUnlocked = true;
        loading = false;
      };
      const data = await api.streamCoachMessage({
        message: text || '(image)',
        recent_tss: athleteStore.recent_tss,
        conversation_id: cid,
        image_urls,
        onConversationId: (id) => {
          conversationId = id;
        },
        onStarted: unlockInput,
        onChunk: (chunk) => {
          unlockInput();
          accumulated += chunk;
          const msgIndex = messages.findIndex((m) => m.id === aiMsgId);
          if (msgIndex !== -1) {
            messages[msgIndex].text = accumulated;
          }
          scrollToBottom();
        }
      });
      if (data.conversation_id) conversationId = data.conversation_id;
      const msgIndex = messages.findIndex((m) => m.id === aiMsgId);
      if (msgIndex !== -1 && !messages[msgIndex].text) {
        messages[msgIndex].text = accumulated;
      }
      scrollToBottom();
    } catch (e) {
      console.error('[Chat] Failed to send coach message:', e);
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
    class="w-full h-full flex flex-col flex-1 min-h-0 rounded-none border-0 bg-bg1/35 overflow-hidden"
  >
    <!-- Mockup header -->
    <div class="shrink-0 px-4 pt-4 pb-3 flex items-center justify-between gap-3 border-b border-border">
      <span class="text-[11px] sm:text-xs tracking-wide font-semibold text-text1">Astraphe AI Coach Chat</span>
      <div class="flex items-center gap-1.5 shrink-0">
        <span
          class="inline-flex h-2 w-2 rounded-full bg-teal animate-pulse shadow-[0_0_10px_rgba(0,200,168,0.55)]"
          aria-hidden="true"
        ></span>
        <span class="text-[11px] uppercase tracking-wider font-semibold text-astraphe-teal">Live</span>
      </div>
    </div>

    <!-- History controls -->
    <div class="shrink-0 px-4 py-2 flex items-center justify-end gap-2 border-b border-border bg-bg0/25">
      {#if conversations.length > 0}
        <div class="relative flex-1 min-w-0 max-w-[220px]" bind:this={convoMenuEl}>
          <button
            type="button"
            class="w-full bg-glass2 border border-border rounded-xl text-[11px] text-text0 pl-3 pr-8 py-2 outline-none truncate text-left hover:bg-glass transition-colors"
            onclick={() => { convoMenuOpen = !convoMenuOpen; }}
            aria-label="Select chat"
          >
            {currentConversationTitle()}
          </button>
          <div class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text2 text-[10px]">▼</div>

          {#if convoMenuOpen}
            <div
              class="absolute left-0 right-0 mt-2 max-w-[min(100vw-2rem,320px)] bg-bg1/95 backdrop-blur border border-border rounded-2xl shadow-2xl overflow-hidden z-20"
            >
              <div class="max-h-[320px] overflow-y-auto">
                {#each conversations as c (c.id)}
                  <div
                    class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-glass2 transition-colors cursor-pointer {c.id === conversationId ? 'bg-glass2' : ''}"
                    role="button"
                    tabindex="0"
                    onclick={() => selectConversation(c.id)}
                    onkeydown={(e) => e.key === 'Enter' && selectConversation(c.id)}
                  >
                    <div class="flex-1 min-w-0">
                      <div class="text-[12px] text-text0 truncate">{c.title || 'New chat'}</div>
                      <div class="text-[10px] text-text2 truncate">{c.updated_at || c.created_at || ''}</div>
                    </div>
                    <button
                      type="button"
                      class="w-8 h-8 rounded-lg bg-glass2 border border-border text-text1 hover:text-red transition-colors flex items-center justify-center shrink-0"
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
        class="px-3 py-1.5 rounded-lg text-[11px] bg-glass2 border border-border text-text1 hover:bg-glass transition-colors shrink-0"
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
              class="w-8 h-8 shrink-0 rounded-full bg-bg2 border border-border flex items-center justify-center text-[9px] font-bold tracking-wide text-teal select-none"
              aria-hidden="true"
            >
              AI
            </div>
            <div
              class="max-w-[min(92%,28rem)] min-w-0 overflow-hidden px-[14px] py-[10px] text-[13px] leading-[1.55] text-text0 rounded-2xl rounded-bl-md border border-border bg-glass2 break-words"
            >
              {#if msg.image_urls && msg.image_urls.length > 0}
                <div class="flex gap-2 flex-wrap mb-2">
                  {#each msg.image_urls as u (u)}
                    <a
                      href={u}
                      target={isStandaloneDisplayMode() ? undefined : '_blank'}
                      rel="noopener noreferrer"
                      class="block"
                    >
                      <img
                        src={u}
                        alt="upload"
                        class="w-24 h-24 object-cover rounded-lg border border-border"
                      />
                    </a>
                  {/each}
                </div>
              {/if}
              {#if msg.streaming && !msg.text.trim()}
                <div class="flex items-center gap-2 text-text1">
                  <div class="flex gap-1">
                    <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce"></div>
                    <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce [animation-delay:150ms]"></div>
                    <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce [animation-delay:300ms]"></div>
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
              class="max-w-[min(92%,28rem)] min-w-0 px-[14px] py-[10px] text-[13px] leading-[1.55] text-text0 rounded-2xl rounded-br-md border border-blue/30 bg-blue-dim break-words whitespace-pre-wrap"
            >
              {#if msg.image_urls && msg.image_urls.length > 0}
                <div class="flex gap-2 flex-wrap mb-2 justify-end">
                  {#each msg.image_urls as u (u)}
                    <a
                      href={u}
                      target={isStandaloneDisplayMode() ? undefined : '_blank'}
                      rel="noopener noreferrer"
                      class="block"
                    >
                      <img
                        src={u}
                        alt="upload"
                        class="w-24 h-24 object-cover rounded-lg border border-blue/30"
                      />
                    </a>
                  {/each}
                </div>
              {/if}
              {normalizeTypographyForWrap(msg.text)}
            </div>
            <div
              class="w-8 h-8 shrink-0 rounded-full bg-bg0 border border-border flex items-center justify-center text-[10px] font-semibold text-text1 select-none uppercase"
              aria-hidden="true"
            >
              {userInitials}
            </div>
          </div>
        {/if}
      {/each}
    </div>

    <div class="shrink-0 px-4 pt-2 pb-1 border-t border-border bg-bg0/20">
      <div class="flex gap-2 overflow-x-auto pb-3 mb-2 scrollbar-thin">
        {#each promptSuggestions as s, i (s + String(i))}
          <button
            type="button"
            class="whitespace-nowrap shrink-0 px-3 py-2 rounded-xl text-sm text-text1 bg-glass2 hover:bg-glass border border-border transition-colors text-left cursor-pointer font-sans"
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
                class="w-16 h-16 object-cover rounded-lg border border-border"
              />
              <button
                class="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-bg1 border border-border text-text1 text-[12px] flex items-center justify-center hover:border-text2"
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
          class="w-10 h-10 rounded-xl shrink-0 text-text1 text-[17px] flex items-center justify-center transition-colors border border-border bg-bg1 hover:bg-bg2 disabled:opacity-40"
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
          class="flex-1 min-w-0 min-h-[2.75rem] max-h-[200px] px-4 py-3 rounded-xl text-[13px] leading-snug bg-bg1 border border-border text-text0 placeholder:text-text2 font-sans outline-none focus:border-blue focus:ring-1 focus:ring-blue/30 resize-none overflow-hidden"
        ></textarea>
        <button
          type="button"
          class="w-11 h-11 shrink-0 rounded-xl flex items-center justify-center transition-all bg-blue hover:bg-blue/90 disabled:opacity-35 disabled:pointer-events-none text-text0 shadow-[0_8px_24px_-12px_rgba(70,33,255,0.7)]"
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
    overflow-wrap: break-word;
    font-family: 'ChatSans', 'Space Grotesk', sans-serif;
  }
  :global(.chat-md :where(p, li, blockquote)) {
    overflow-wrap: break-word;
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

  /* Responsive tables in AI messages */
  :global(.chat-md :where(table)) {
    display: block;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    max-width: 100%;
    border-collapse: collapse;
    font-size: 0.8em;
    margin: 0.5rem 0;
    border-radius: 0.5rem;
  }
  :global(.chat-md :where(thead)) {
    background: rgba(70, 33, 255, 0.12);
  }
  :global(.chat-md :where(th)) {
    padding: 0.35rem 0.65rem;
    border: 1px solid rgba(255, 255, 255, 0.08);
    white-space: nowrap; /* header labels stay on one line */
    vertical-align: top;
    text-align: left;
    color: rgb(0 200 168);
    font-size: 0.9em;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  :global(.chat-md :where(td)) {
    padding: 0.35rem 0.65rem;
    border: 1px solid rgba(255, 255, 255, 0.08);
    white-space: normal; /* allow wrapping */
    overflow-wrap: break-word;
    word-break: normal;
    vertical-align: top;
    max-width: 14rem; /* single cell can't blow out the table */
  }
  :global(.chat-md :where(td:first-child, th:first-child)) {
    min-width: 6.5rem;
  }
  :global(.chat-md :where(tbody tr:nth-child(even))) {
    background: rgba(255, 255, 255, 0.03);
  }

  :global(.chat-md .chat-table-note) {
    margin-top: 0.6rem;
    font-size: 0.82em;
    color: rgb(148 163 184);
    line-height: 1.5;
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
