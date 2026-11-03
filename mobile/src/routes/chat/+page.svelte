<script lang="ts">
  import { api } from '$lib/api';
  import { renderCoachMarkdownToSafeHtml, normalizeTypographyForWrap } from '$lib/coachMarkdown';
  import { buildMergedCoachPromptSuggestions } from '$lib/coachPromptSuggestions';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { confirm } from '$lib/confirm';
  import { format } from 'date-fns';
  import { tick, onDestroy } from 'svelte';
  import { isStandaloneDisplayMode } from '$lib/utils/pwa';
  import { normalizeLeadingTimeOfDayGreeting } from '$lib/utils/greeting';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { buildCoachSteps, coachStatusText, type CoachStep } from '$lib/coachProgress';

  type Conversation = { id: string; title?: string | null; created_at?: string; updated_at?: string };
  type Message = {
    id: string;
    role: 'user' | 'ai';
    text: string;
    image_urls?: string[];
    created_at?: string;
    streaming?: boolean;
    statusText?: string;
    /** What the coach checked while writing this reply (live, not persisted). */
    steps?: CoachStep[];
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


  function coachStatusLabel(status: string, detail?: Record<string, unknown>): string {
    if (status === 'started' || status === 'context_ready') return 'Reviewing your data…';
    if (status === 'thinking') return 'Thinking…';
    if (status === 'tool') {
      const tool = typeof detail?.tool === 'string' ? detail.tool : '';
      if (tool === 'schedule_workout') return 'Scheduling workouts…';
      if (tool === 'get_athlete_zones') return 'Looking up your zones…';
      if (tool === 'internal_scratchpad') return 'Planning…';
      if (tool === 'simulate_training_impact') return 'Simulating training impact…';
      if (tool === 'calculate_nutrition') return 'Calculating nutrition targets…';
      if (tool === 'list_workouts' || tool === 'get_workout_summary') return 'Analyzing your workouts…';
      if (tool === 'clear_training_plans') return 'Clearing calendar…';
      if (tool) return 'Working on it…';
    }
    return 'Thinking…';
  }

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
      // A conversation loaded (or reloaded, e.g. re-opening the app) whose
      // last turn is still the athlete's own message means an async reply
      // (see send()) is still being generated server-side — resume waiting
      // for it instead of leaving the screen looking like nothing happened.
      if (messages[messages.length - 1].role === 'user') {
        const aiMsgId = `local-ai-${Date.now()}`;
        messages.push({ id: aiMsgId, role: 'ai', text: '', streaming: true });
        loading = true; // keep send/attach disabled until the resumed poll resolves
        pollForCoachReply(cid, aiMsgId, rows.length);
      }
    }
    await scrollToBottom();
  }

  // At most one outstanding poll loop at a time — switching conversations or
  // leaving the page should stop waiting on a reply that's no longer shown.
  let activePollToken = 0;

  /**
   * Poll for the reply to whatever the last message in this conversation
   * was, submitted via submitCoachMessageAsync(). knownMessageCount is the
   * message count *before* that reply can possibly have landed, so a longer
   * row count is our signal it arrived (the row list is append-only and
   * ordered by created_at, so a new last row is always the new reply).
   *
   * Callers must set `loading = true` before calling this — send() and
   * loadConversationMessages()'s resume-on-reopen path both do — so the
   * input stays disabled (see the template's `disabled={loading}`) for the
   * whole wait, not just the initial submit call. Sending a second message
   * before the first reply lands would bump activePollToken and orphan the
   * first placeholder mid-flight (see PR #18 review). This function is the
   * only thing that resets `loading` back to false once it's set true for a
   * pending reply — every terminal path below (resolved / poll error /
   * timeout) clears it, gated the same way as the UI update right above it
   * so a stale/superseded poll never touches the wrong conversation's state.
   */
  function pollForCoachReply(cid: string, aiMsgId: string, knownMessageCount: number) {
    const token = ++activePollToken;
    const POLL_INTERVAL_MS = 1200;
    const MAX_ATTEMPTS = 150; // ~3 minutes
    let attempt = 0;

    const tickPoll = async () => {
      if (token !== activePollToken) return; // superseded by a newer poll/navigation
      attempt += 1;
      try {
        const [res, events] = await Promise.all([api.getCoachMessages(cid), api.getCoachProgress(cid)]);
        const rows = res?.messages || [];
        if (rows.length > knownMessageCount) {
          const last = rows[rows.length - 1];
          if (token === activePollToken && conversationId === cid) {
            const msgIndex = messages.findIndex((m) => m.id === aiMsgId);
            if (msgIndex !== -1) {
              const finalSteps = events.length ? buildCoachSteps(events, false) : messages[msgIndex].steps;
              messages[msgIndex] = {
                id: String(last.id),
                role: 'ai',
                text: String(last.content ?? ''),
                image_urls: Array.isArray(last.image_urls) ? last.image_urls : [],
                created_at: last.created_at,
                streaming: false,
                steps: finalSteps?.length ? finalSteps.map((st) => ({ ...st, done: true })) : undefined
              };
            }
            loading = false;
            scrollToBottom();
          }
          return; // done
        }
        if (token === activePollToken && conversationId === cid && events.length) {
          const msgIndex = messages.findIndex((m) => m.id === aiMsgId);
          if (msgIndex !== -1) {
            messages[msgIndex].steps = buildCoachSteps(events, true);
            messages[msgIndex].statusText = coachStatusText(events);
          }
        }
      } catch (e) {
        console.warn('[Chat] Poll for coach reply failed:', e);
        // Transient network hiccup — keep polling rather than giving up.
      }
      if (token !== activePollToken || attempt >= MAX_ATTEMPTS) {
        if (attempt >= MAX_ATTEMPTS && token === activePollToken && conversationId === cid) {
          const msgIndex = messages.findIndex((m) => m.id === aiMsgId);
          if (msgIndex !== -1 && !messages[msgIndex].text.trim()) {
            messages[msgIndex].streaming = false;
            messages[msgIndex].text =
              "That's taking longer than usual. Your coach may still be working on it — check back in a bit, or pull to refresh this chat.";
          }
          loading = false;
        }
        return;
      }
      setTimeout(tickPoll, POLL_INTERVAL_MS);
    };
    setTimeout(tickPoll, POLL_INTERVAL_MS);
  }

  onDestroy(() => {
    activePollToken++; // invalidate any in-flight poll loop
  });

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
    activePollToken++; // stop waiting on a reply for the conversation we're leaving
    loading = false;
    input = '';
    pendingImageUrls = [];
    conversationId = null;
    messages = [{ id: 'local-greeting', role: 'ai', text: initialText }];
    convoMenuOpen = false;
    await scrollToBottom();
  }

  async function selectConversation(cid: string) {
    activePollToken++; // stop waiting on a reply for the conversation we're leaving
    loading = false; // that poll invalidation means nothing will clear it otherwise
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
      if (t instanceof Element && t.closest('[data-header-action="history"]')) return;
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
    // Serialize sends: a reply still in flight (loading stays true from the
    // moment it's submitted until pollForCoachReply resolves it — see that
    // function's docstring) must finish before the next one starts, or a
    // second submit's poll would supersede and orphan the first's
    // placeholder. The send/attach buttons are already disabled via this
    // same flag; this guards direct calls to send() too (e.g. Enter key).
    if (loading) return;

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
      // Fire-and-forget: the backend inserts the user message, generates the
      // reply in a background task, and returns immediately. No connection
      // is held open for however long the (possibly multi-hop) Gemini call
      // takes — pollForCoachReply picks up the result, and a push
      // notification covers the case where the athlete has already left.
      const data = await api.submitCoachMessageAsync({
        message: text || '(image)',
        recent_tss: athleteStore.recent_tss,
        conversation_id: cid,
        image_urls
      });
      if (data.conversation_id) conversationId = data.conversation_id;
      // loading stays true — pollForCoachReply() (below) is responsible for
      // clearing it once the reply actually resolves, not this submit call.
      // Baseline off the server's own row count right after the submit call
      // returns (which already includes the just-inserted user message) —
      // the local `messages` array isn't a reliable proxy for it (it may
      // hold a synthetic, never-persisted greeting row for a new chat).
      const baselineRes = await api.getCoachMessages(data.conversation_id);
      const baselineCount = (baselineRes?.messages || []).length;
      pollForCoachReply(data.conversation_id, aiMsgId, baselineCount);
    } catch (e) {
      console.error('[Chat] Failed to send coach message:', e);
      const msgIndex = messages.findIndex((m) => m.id === aiMsgId);
      if (msgIndex !== -1) {
        messages[msgIndex].streaming = false;
        messages[msgIndex].text = 'Sorry, I had trouble connecting to the coaching engine.';
      }
      loading = false;
    } finally {
      // Refresh conversation titles (auto-named on backend after first message)
      try {
        const res = await api.getCoachConversations();
        conversations = res?.conversations || conversations;
      } catch {}
    }
  }


  function formatConvoDate(iso?: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return format(d, d.getFullYear() === new Date().getFullYear() ? 'EEE d MMM · HH:mm' : 'd MMM yyyy');
  }

  $effect(() => {
    pageHeader.eyebrow = 'Knows your last 90 days';
    pageHeader.actions = [
      { key: 'history', label: 'Past conversations', icon: 'history', onclick: () => (convoMenuOpen = !convoMenuOpen) },
      { key: 'new', label: 'New conversation', icon: 'plus', onclick: () => { convoMenuOpen = false; newChat(); } }
    ];
    return resetPageHeader;
  });
</script>

<div class="relative flex flex-col h-full min-h-0 w-full box-border">
  {#if convoMenuOpen}
    <!-- Past conversations -->
    <div bind:this={convoMenuEl} class="absolute left-4 right-4 top-1 z-30 rounded-[20px] border border-border bg-bg2 shadow-[0_16px_40px_rgba(0,0,0,0.5)] overflow-hidden">
      <div class="flex items-center justify-between px-4 pt-3 pb-2">
        <span class="font-mono text-[10px] tracking-[0.12em] text-text2">PAST CONVERSATIONS</span>
        <button type="button" class="h-8 border-0 bg-transparent p-0 text-[13px] font-medium text-blue cursor-pointer" onclick={() => { convoMenuOpen = false; newChat(); }}>New chat</button>
      </div>
      <div class="max-h-[50dvh] overflow-y-auto">
        {#if conversations.length === 0}
          <p class="m-0 px-4 pb-4 text-[13px] text-text2">No past conversations yet.</p>
        {/if}
        {#each conversations as c (c.id)}
          <div class="flex items-center gap-2 border-t border-border px-2 {c.id === conversationId ? 'bg-bg3' : ''}">
            <button type="button" class="flex-1 min-w-0 flex flex-col gap-0.5 px-2 py-2.5 border-0 bg-transparent text-left cursor-pointer" onclick={() => { convoMenuOpen = false; selectConversation(c.id); }}>
              <span class="text-sm text-text0 truncate">{c.title || 'New chat'}</span>
              <span class="font-mono text-[10px] text-text2 truncate">{formatConvoDate(c.updated_at || c.created_at)}</span>
            </button>
            <button
              type="button"
              class="w-10 h-10 shrink-0 rounded-xl border-0 bg-transparent text-text2 flex items-center justify-center cursor-pointer"
              onclick={(e) => { e.stopPropagation(); deleteConversation(c.id); }}
              aria-label="Delete chat"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg>
            </button>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <div class="flex-1 overflow-y-auto flex flex-col gap-3.5 px-5 pt-2 pb-4 min-h-0" bind:this={chatContainer}>
    {#each messages as msg (msg.id)}
      {#if msg.role === 'ai'}
        {#if msg.steps && msg.steps.length > 0}
          <ol aria-label="What the coach checked" class="list-none m-0 p-0 flex flex-col gap-1.5">
            {#each msg.steps as step (step.key)}
              <li class="flex items-center gap-2 font-mono text-[11px] text-text2">
                {#if step.done}
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5L19 7"></path></svg>
                {:else}
                  <span aria-hidden="true" class="w-3 h-3 flex items-center justify-center"><span class="w-1.5 h-1.5 rounded-full bg-blue animate-pulse"></span></span>
                {/if}
                <span class:text-text1={!step.done}>{step.label}{step.count > 1 ? ` ×${step.count}` : ''}</span>
              </li>
            {/each}
          </ol>
        {/if}
        <div class="flex flex-col gap-2.5 p-4 rounded-[20px] bg-bg2 border border-border text-sm leading-[1.55] text-text1 break-words min-w-0">
          {#if msg.image_urls && msg.image_urls.length > 0}
            <div class="flex gap-2 flex-wrap">
              {#each msg.image_urls as u (u)}
                <a href={u} target={isStandaloneDisplayMode() ? undefined : '_blank'} rel="noopener noreferrer" class="block">
                  <img src={u} alt="upload" class="w-24 h-24 object-cover rounded-xl border border-border" />
                </a>
              {/each}
            </div>
          {/if}
          {#if msg.streaming && !msg.text.trim()}
            <div class="flex items-center gap-2.5 text-text2">
              <span class="flex gap-1" aria-hidden="true">
                <span class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce"></span>
                <span class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce [animation-delay:150ms]"></span>
                <span class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce [animation-delay:300ms]"></span>
              </span>
              <span class="font-mono text-[11px]">{msg.statusText || 'Reviewing your data…'}</span>
            </div>
          {:else}
            <div class="chat-md">{@html renderCoachMarkdownToSafeHtml(msg.text)}</div>
          {/if}
        </div>
      {:else}
        <div class="self-end max-w-[78%] min-w-0 px-3.5 py-3 rounded-[18px_18px_6px_18px] bg-border text-sm leading-[1.45] text-text0 break-words whitespace-pre-wrap">
          {#if msg.image_urls && msg.image_urls.length > 0}
            <div class="flex gap-2 flex-wrap mb-2 justify-end">
              {#each msg.image_urls as u (u)}
                <a href={u} target={isStandaloneDisplayMode() ? undefined : '_blank'} rel="noopener noreferrer" class="block">
                  <img src={u} alt="upload" class="w-24 h-24 object-cover rounded-xl border border-border" />
                </a>
              {/each}
            </div>
          {/if}
          {normalizeTypographyForWrap(msg.text)}
        </div>
      {/if}
    {/each}

    {#if !loading && promptSuggestions.length > 0}
      <div aria-label="Suggested questions" class="flex flex-wrap gap-2">
        {#each promptSuggestions as s, i (s + String(i))}
          <button
            type="button"
            class="h-9 px-3 rounded-[18px] border border-border bg-bg1 text-[13px] text-text1 cursor-pointer text-left max-w-full truncate"
            onclick={() => { input = s; tick().then(() => { resizeChatInput(); chatInputEl?.focus(); }); }}
          >{s}</button>
        {/each}
      </div>
    {/if}
  </div>

  <div class="shrink-0 px-4 pt-1" style="padding-bottom: 12px;">
    {#if pendingImageUrls.length > 0}
      <div class="flex gap-2 flex-wrap pb-2">
        {#each pendingImageUrls as u (u)}
          <div class="relative">
            <img src={u} alt="pending upload" class="w-16 h-16 object-cover rounded-xl border border-border" />
            <button
              class="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-bg2 border border-border text-text1 text-[12px] flex items-center justify-center cursor-pointer"
              onclick={() => { pendingImageUrls = pendingImageUrls.filter((x) => x !== u); }}
              aria-label="Remove image"
              type="button"
            >✕</button>
          </div>
        {/each}
      </div>
    {/if}

    <form class="flex gap-2 items-end p-1.5 rounded-[20px] bg-bg2 border border-border" onsubmit={(e) => { e.preventDefault(); if (!loading) void send(); }}>
      <input bind:this={fileInput} type="file" accept="image/*" multiple class="hidden" onchange={onFilesSelected} />
      <button
        type="button"
        class="w-11 h-11 shrink-0 rounded-[14px] border-0 bg-transparent text-text2 flex items-center justify-center cursor-pointer disabled:opacity-40"
        disabled={loading}
        onclick={pickImage}
        aria-label="Attach image"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"></rect><circle cx="9" cy="10" r="1.6"></circle><path d="m21 16-5-5-9 9"></path></svg>
      </button>
      <label for="coach-input" class="sr-only">Ask your coach</label>
      <textarea
        id="coach-input"
        bind:this={chatInputEl}
        bind:value={input}
        rows="1"
        maxlength="8000"
        oninput={resizeChatInput}
        onkeydown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!loading) void send();
          }
        }}
        placeholder="Ask about your training…"
        class="flex-1 min-w-0 min-h-11 max-h-[200px] py-3 bg-transparent border-0 text-sm leading-snug text-text0 placeholder:text-text2 outline-none resize-none overflow-hidden"
      ></textarea>
      <button
        type="submit"
        class="w-11 h-11 shrink-0 rounded-[14px] border-0 bg-blue text-[#0B1420] flex items-center justify-center cursor-pointer disabled:opacity-35 disabled:pointer-events-none"
        disabled={loading || (!input.trim() && pendingImageUrls.length === 0)}
        aria-label="Send"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"></path></svg>
      </button>
    </form>
  </div>
</div>

<style>
  /* Markdown styles scoped to AI message bubbles */
  :global(.chat-md) {
    word-break: break-word;
    overflow-wrap: break-word;
    font-family: 'Inter', system-ui, sans-serif;
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
  :global(.chat-md :where(ul)) {
    list-style-type: disc;
    list-style-position: outside;
  }
  :global(.chat-md :where(ol)) {
    list-style-type: decimal;
    list-style-position: outside;
  }
  :global(.chat-md :where(ul ul)) {
    list-style-type: circle;
  }
  :global(.chat-md :where(li)) {
    margin: 0.15rem 0;
  }
  :global(.chat-md :where(a)) {
    color: var(--teal);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  :global(.chat-md :where(code)) {
    font-size: 0.92em;
    padding: 0.12rem 0.3rem;
    border-radius: 0.45rem;
    background: var(--glass2);
    border: 1px solid var(--border);
  }
  :global(.chat-md :where(pre)) {
    overflow-x: auto;
    padding: 0.6rem 0.7rem;
    border-radius: 0.75rem;
    background: var(--bg0);
    border: 1px solid var(--border);
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
    background: var(--glass2);
  }
  :global(.chat-md :where(th)) {
    padding: 0.35rem 0.65rem;
    border: 1px solid var(--border);
    white-space: nowrap; /* header labels stay on one line */
    vertical-align: top;
    text-align: left;
    color: var(--teal);
    font-size: 0.9em;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  :global(.chat-md :where(td)) {
    padding: 0.35rem 0.65rem;
    border: 1px solid var(--border);
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
    background: var(--glass);
  }

  :global(.chat-md .chat-table-note) {
    margin-top: 0.6rem;
    font-size: 0.82em;
    color: var(--text2);
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
