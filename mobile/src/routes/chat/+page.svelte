<script lang="ts">
  import { api } from '$lib/api';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { confirm } from '$lib/confirm';
  import DOMPurify from 'dompurify';
  import { marked } from 'marked';
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
  let convoMenuOpen = $state(false);
  let convoMenuEl = $state<HTMLElement | null>(null);
  let historyLoaded = $state(false);
  let historyLoading = $state(false);

  const mdRenderer = new marked.Renderer();
  mdRenderer.link = (...args: any[]) => {
    // Marked's renderer signatures vary by version; support both positional and token-object forms.
    const token = args[0] && typeof args[0] === 'object' ? args[0] : null;
    const href = token?.href ?? args[0];
    const title = token?.title ?? args[1];
    const text = token?.text ?? args[2];

    const safeHref = typeof href === 'string' ? href : '';
    const safeTitle = typeof title === 'string' ? title : undefined;
    const safeText = typeof text === 'string' ? escapeHtmlText(text) : escapeHtmlText(safeHref);
    const titleAttr = safeTitle ? ` title="${escapeHtmlAttr(safeTitle)}"` : '';
    return `<a href="${escapeHtmlAttr(safeHref)}"${titleAttr} target="_blank" rel="noreferrer noopener">${safeText}</a>`;
  };

  marked.setOptions({
    gfm: true,
    breaks: true,
    renderer: mdRenderer
  });

  function escapeHtmlAttr(value: string) {
    return value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  }

  function escapeHtmlText(value: string) {
    return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  }

  function renderAiMarkdown(text: string) {
    // Render markdown → sanitize → render via {@html}.
    const html = marked.parse(text ?? '', { async: false }) as string;
    return DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|\/)/i
    });
  }

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
      const stream = api.streamCoachChat({
        message: text || '(image)',
        recent_tss: athleteStore.recent_tss,
        conversation_id: cid,
        image_urls
      });

      for await (const evt of stream) {
        if (evt.type === 'conversation_id') {
          conversationId = evt.conversation_id;
          continue;
        }
        const msgIndex = messages.findIndex(m => m.id === aiMsgId);
        if (msgIndex !== -1) {
          messages[msgIndex].text += evt.text;
        }
        scrollToBottom();
      }
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

  const suggestions = ['Plan this week', 'Am I overtrained?', 'Race day strategy', 'Improve VO2max'];
</script>

<div class="flex flex-col h-full p-4 box-border">
  <div class="pb-3 shrink-0">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-[#4621FF] to-[#00C8A8] flex items-center justify-center shrink-0">
        <img src="/astrape-logo.svg" alt="Astrape" class="w-6 h-6 object-contain" />
      </div>
      <div class="flex-1 min-w-0">
        <p class="font-semibold text-[15px] truncate">ASTRAPE Coach</p>
        <p class="text-[11px] text-teal">● Online · analyzing your data</p>
      </div>

      <div class="flex items-center gap-2">
        {#if conversations.length > 0}
          <div class="relative" bind:this={convoMenuEl}>
            <button
              type="button"
              class="bg-glass2 border border-border rounded-xl text-[11px] text-text0 pl-3 pr-8 py-2 outline-none max-w-[190px] truncate shadow-[0_0_0_1px_rgba(255,255,255,0.04)] cursor-pointer text-left"
              onclick={() => { convoMenuOpen = !convoMenuOpen; }}
              aria-label="Select chat"
            >
              {currentConversationTitle()}
            </button>
            <div class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-text2 text-[10px]">
              ▼
            </div>

            {#if convoMenuOpen}
              <div class="absolute right-0 mt-2 w-[260px] max-w-[75vw] bg-bg1/90 backdrop-blur border border-border rounded-2xl shadow-2xl overflow-hidden z-20">
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
                        class="w-8 h-8 rounded-xl bg-glass border border-border text-text1 hover:text-red-400 transition-colors flex items-center justify-center shrink-0"
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
          class="px-3 py-1 rounded-lg text-[11px] bg-glass border border-border text-text1 cursor-pointer"
          onclick={newChat}
        >
          New
        </button>
      </div>
    </div>
  </div>

  <div class="flex-1 overflow-y-auto flex flex-col gap-3 pb-2" bind:this={chatContainer}>
    {#each messages as msg (msg.id)}
      <div class="flex flex-col items-start {msg.role === 'user' ? 'items-end' : ''}">
        {#if msg.role === 'ai'}
          <div class="w-6 h-6 rounded-lg bg-gradient-to-br from-[#4621FF] to-[#00C8A8] flex items-center justify-center mb-1">
            <img src="/astrape-logo.svg" alt="Astrape" class="w-3.5 h-3.5 object-contain" />
          </div>
        {/if}
        <div class="max-w-[82%] px-[14px] py-[10px] text-[13px] leading-[1.55] text-text0 border {msg.role === 'user' ? 'bg-blue rounded-[18px_18px_4px_18px] border-[rgba(70,33,255,0.5)]' : 'bg-glass2 rounded-[4px_18px_18px_18px] border-border'}">
          {#if msg.image_urls && msg.image_urls.length > 0}
            <div class="flex gap-2 flex-wrap mb-2">
              {#each msg.image_urls as u (u)}
                <a href={u} target="_blank" rel="noreferrer noopener" class="block">
                  <img src={u} alt="upload" class="w-24 h-24 object-cover rounded-lg border border-[rgba(255,255,255,0.12)]" />
                </a>
              {/each}
            </div>
          {/if}
          {#if msg.role === 'ai'}
            {#if msg.streaming && !msg.text.trim()}
              <div class="flex items-center gap-2 text-text1">
                <div class="flex gap-1">
                  <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce"></div>
                  <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce delay-150"></div>
                  <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce delay-300"></div>
                </div>
                <span class="text-[12px]">Thinking…</span>
              </div>
            {:else}
              <div class="chat-md">{@html renderAiMarkdown(msg.text)}</div>
            {/if}
            {#if msg.streaming && msg.text.trim()}
              <span class="animate-[blink_1s_step-end_infinite]">▋</span>
            {/if}
          {:else}
            {msg.text}
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <div class="flex gap-1.5 overflow-x-auto pb-2 shrink-0">
    {#each suggestions as s (s)}
      <button class="whitespace-nowrap px-3 py-1 rounded-full text-[11px] bg-glass border border-border text-text1 cursor-pointer font-sans" onclick={() => { input = s; }}>{s}</button>
    {/each}
  </div>

  <div class="flex gap-2 shrink-0 items-end">
    <input
      bind:this={fileInput}
      type="file"
      accept="image/*"
      multiple
      class="hidden"
      onchange={onFilesSelected}
    />
    <button
      class="w-11 h-11 rounded-xl shrink-0 text-white text-[16px] flex items-center justify-center transition-all duration-200 border border-border bg-glass"
      disabled={loading}
      onclick={pickImage}
      aria-label="Attach image"
      type="button"
    >
      ＋
    </button>
    <input 
      bind:value={input} 
      onkeydown={(e) => e.key === 'Enter' && !loading && send()} 
      placeholder="Ask your coach..." 
      class="flex-1 px-4 py-[11px] rounded-xl text-[13px] bg-glass2 border border-border text-text0 font-sans outline-none"
    />
    <button class="w-11 h-11 rounded-xl shrink-0 text-white text-[18px] flex items-center justify-center transition-all duration-200 border border-border {(input.trim() || pendingImageUrls.length > 0) ? 'bg-blue border-blue' : 'bg-glass'}" disabled={loading || (!input.trim() && pendingImageUrls.length === 0)} onclick={send}>↑</button>
  </div>

  {#if pendingImageUrls.length > 0}
    <div class="mt-2 flex gap-2 flex-wrap">
      {#each pendingImageUrls as u (u)}
        <div class="relative">
          <img src={u} alt="pending upload" class="w-16 h-16 object-cover rounded-lg border border-[rgba(255,255,255,0.12)]" />
          <button
            class="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-bg1 border border-border text-text1 text-[12px] flex items-center justify-center"
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

  @keyframes blink {
    50% {
      opacity: 0;
    }
  }
</style>
