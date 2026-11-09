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
  import { pageHeader, claimPageHeader } from '$lib/stores/pageHeader.svelte';
  import { page } from '$app/stores';
  import { replaceState } from '$app/navigation';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';
  import { viewport } from '$lib/stores/viewport.svelte';
  import ConversationList from '$lib/components/wide/coach/ConversationList.svelte';
  import CoachContextPane from '$lib/components/wide/coach/CoachContextPane.svelte';
  import { buildCoachSteps, coachStatusText, type CoachStep } from '$lib/coachProgress';
  import { COACH_REPLY_WAIT_MS, remainingReplyWaitMs } from '$lib/utils/coachReply';
  import { CHAT_FILE_ACCEPT, documentBadge, documentProblem, fileExtension, isDocumentFile, isImageFile } from '$lib/utils/chatAttachments';
  import CoachThreadHeader from '$lib/components/coach/CoachThreadHeader.svelte';
  import QuickReplies from '$lib/components/coach/QuickReplies.svelte';
  import {
    isCoachThread,
    latestQuickReplies,
    outgoingMessage,
    triggerLabel,
    unreadCount,
    unreadLabel,
    type CoachConversation
  } from '$lib/utils/coachThreads';

  type Conversation = CoachConversation;
  type Message = {
    id: string;
    role: 'user' | 'ai';
    text: string;
    image_urls?: string[];
    /** Documents attached to a user message (names only; the text stays server-side). */
    attachments?: { name: string; kind: string }[];
    created_at?: string;
    streaming?: boolean;
    statusText?: string;
    /** What the coach checked while writing this reply (live, not persisted). */
    steps?: CoachStep[];
    /** One-tap replies the coach offered with this message ("Felt good"). */
    quick_replies?: string[];
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
  /** Documents picked for the next message: read on the server first, then sent with it. */
  type PendingDoc = { id: string; name: string; status: 'reading' | 'ready' | 'error'; content?: string; error?: string };
  let pendingDocs = $state<PendingDoc[]>([]);
  let attachError = $state<string | null>(null);
  const docsReading = $derived(pendingDocs.some((d) => d.status === 'reading'));
  const readyDocs = $derived(pendingDocs.filter((d) => d.status === 'ready' && d.content));
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

  /** Tablet / desktop: conversations | chat | context (design: Coach 3-pane). */
  const wide = $derived(viewport.wide);

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
        attachments: Array.isArray(m.attachments) ? m.attachments : [],
        quick_replies: Array.isArray(m.quick_replies) ? m.quick_replies : [],
        created_at: m.created_at
      }));
      // A conversation loaded (or reloaded, e.g. re-opening the app) whose
      // last turn is still the athlete's own message means an async reply
      // (see send()) is still being generated server-side — resume waiting
      // for it instead of leaving the screen looking like nothing happened.
      // Only while a reply can still be coming: an old unanswered message (the
      // reply failed) must not lock the input for another 3 minutes.
      const last = messages[messages.length - 1];
      const waitMs = last.role === 'user' ? remainingReplyWaitMs(last.created_at) : 0;
      if (waitMs > 0) {
        const aiMsgId = `local-ai-${Date.now()}`;
        messages.push({ id: aiMsgId, role: 'ai', text: '', streaming: true });
        loading = true; // keep send/attach disabled until the resumed poll resolves
        pollForCoachReply(cid, aiMsgId, rows.length, waitMs);
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
  function pollForCoachReply(
    cid: string,
    aiMsgId: string,
    knownMessageCount: number,
    waitMs: number = COACH_REPLY_WAIT_MS
  ) {
    const token = ++activePollToken;
    const POLL_INTERVAL_MS = 1200;
    const MAX_ATTEMPTS = Math.max(1, Math.ceil(waitMs / POLL_INTERVAL_MS)); // ~3 minutes for a new send
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
                quick_replies: Array.isArray(last.quick_replies) ? last.quick_replies : [],
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

  // One create at a time: several photos picked together each asked for a conversation and
  // each got a new one, leaving empty "New chat"s in the history.
  let creatingConversation: Promise<string | null> | null = null;

  /** The open conversation, created on first need (a send, or a photo upload). It joins the
   * history list once it has a message (the list refreshes after each send; the server
   * leaves empty chats out). */
  async function ensureConversation(): Promise<string | null> {
    if (conversationId) return conversationId;
    if (creatingConversation) return creatingConversation;
    const token = activePollToken;
    creatingConversation = (async () => {
      try {
        const created = await api.createCoachConversation();
        const cid = (created?.conversation?.id as string | undefined) ?? null;
        // Started a new chat (or opened another) meanwhile: don't point the screen at this one.
        if (cid && token === activePollToken) conversationId = cid;
        return cid;
      } finally {
        creatingConversation = null;
      }
    })();
    return creatingConversation;
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
    markRead(cid);
    await loadConversationMessages(cid);
  }

  /** Opening a coach-started thread clears its unread dot (locally right away, then on the server). */
  function markRead(cid: string) {
    if (!conversations.some((c) => c.id === cid && c.unread)) return;
    conversations = conversations.map((c) => (c.id === cid ? { ...c, unread: false } : c));
    void api.markCoachConversationRead(cid);
  }

  const currentConversation = $derived(conversations.find((c) => c.id === conversationId) ?? null);
  const unreadN = $derived(unreadCount(conversations));
  /** Quick replies under the coach's latest message; hidden while a reply is in flight. */
  const quickReplies = $derived(loading ? [] : latestQuickReplies(messages));

  /** A quick reply goes as its own message; a typed draft and staged files stay put. */
  function sendQuickReply(text: string) {
    if (loading) return;
    void send(text);
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

  function pickImage() {
    // The conversation is created once photos are actually picked (onFilesSelected), so
    // cancelling the picker leaves nothing behind.
    fileInput?.click();
  }

  async function onFilesSelected(e: Event) {
    const inputEl = e.currentTarget as HTMLInputElement;
    const files = Array.from(inputEl.files || []);
    inputEl.value = '';
    if (files.length === 0) return;
    attachError = null;

    const images = files.filter((f) => isImageFile(f) && !isDocumentFile(f));
    const docs = files.filter((f) => !images.includes(f));
    for (const f of docs) void addDocument(f);
    if (images.length === 0) return;

    const cid = await ensureConversation();
    if (!cid) return;

    try {
      loading = true;
      for (const f of images) {
        const url = await api.uploadCoachImage(f, cid);
        pendingImageUrls = [...pendingImageUrls, url];
      }
    } catch (err) {
      console.warn('Image upload failed', err);
      attachError = "Couldn't upload that photo. Try again.";
    } finally {
      loading = false;
    }
  }

  /** Reads a document on the server; its chip shows reading → ready (or the reason it failed). */
  async function addDocument(file: File) {
    const problem = documentProblem(file, pendingDocs.filter((d) => d.status !== 'error').length);
    if (problem) {
      attachError = problem;
      return;
    }
    const id = `doc-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    pendingDocs = [...pendingDocs, { id, name: file.name, status: 'reading' }];
    try {
      const res = await api.uploadCoachDocument(file);
      pendingDocs = pendingDocs.map((d) => (d.id === id ? { ...d, status: 'ready', content: res.content } : d));
    } catch (err) {
      const msg = err instanceof Error ? err.message : `Couldn't read ${file.name}.`;
      pendingDocs = pendingDocs.map((d) => (d.id === id ? { ...d, status: 'error', error: msg } : d));
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

  /**
   * Send the composer (text + staged photos/documents), or, with `quickReply`, just that
   * reply as its own message: the typed draft and staged attachments stay untouched.
   */
  async function send(quickReply: string | null = null) {
    const out = outgoingMessage(quickReply, { input, images: pendingImageUrls, docs: readyDocs });
    if (!out) return;
    const { text, fromComposer } = out;
    // Wait for documents still being read rather than sending without them.
    if (fromComposer && docsReading) return;
    // Serialize sends: a reply still in flight (loading stays true from the
    // moment it's submitted until pollForCoachReply resolves it — see that
    // function's docstring) must finish before the next one starts, or a
    // second submit's poll would supersede and orphan the first's
    // placeholder. The send/attach buttons are already disabled via this
    // same flag; this guards direct calls to send() too (e.g. Enter key).
    if (loading) return;

    let image_urls: string[] = [];
    let documents: { name: string; content: string }[] = [];
    if (fromComposer) {
      input = '';
      await tick();
      resizeChatInput();
    }
    const cid = await ensureConversation();
    if (fromComposer) {
      // Staged files as of now (the composer awaited above); a quick reply never takes them.
      image_urls = pendingImageUrls;
      pendingImageUrls = [];
      documents = readyDocs.map((d) => ({ name: d.name, content: d.content as string }));
      pendingDocs = [];
      attachError = null;
    }

    const userMsg: Message = {
      id: `local-user-${Date.now()}`,
      role: 'user',
      text,
      image_urls,
      attachments: documents.map((d) => ({ name: d.name, kind: fileExtension(d.name) }))
    };
    messages.push(userMsg);
    loading = true;
    scrollToBottom();

    const aiMsgId = `local-ai-${Date.now()}`;
    messages.push({ id: aiMsgId, role: 'ai', text: '', streaming: true });
    // newChat()/selectConversation() bump this. If the user switches away while the
    // submit is in flight, this send must not re-point the screen at its conversation
    // (later messages went to the old chat) or poll its reply into another chat.
    const sendToken = activePollToken;

    try {
      // Fire-and-forget: the backend inserts the user message, generates the
      // reply in a background task, and returns immediately. No connection
      // is held open for however long the (possibly multi-hop) Gemini call
      // takes — pollForCoachReply picks up the result, and a push
      // notification covers the case where the athlete has already left.
      const data = await api.submitCoachMessageAsync({
        message: text || (documents.length ? '' : '(image)'),
        recent_tss: athleteStore.recent_tss,
        conversation_id: cid,
        image_urls,
        documents
      });
      if (sendToken !== activePollToken) return; // user moved on; the reply is still saved server-side
      if (data.conversation_id) conversationId = data.conversation_id;
      // loading stays true — pollForCoachReply() (below) is responsible for
      // clearing it once the reply actually resolves, not this submit call.
      // Baseline off the server's own row count right after the submit call
      // returns (which already includes the just-inserted user message) —
      // the local `messages` array isn't a reliable proxy for it (it may
      // hold a synthetic, never-persisted greeting row for a new chat).
      const baselineRes = await api.getCoachMessages(data.conversation_id);
      if (sendToken !== activePollToken) return;
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

  // --- New conversation, nothing sent yet (design: empty states, page 8) ---
  const STARTER_PROMPTS = [
    'Should I train hard today?',
    'Build me a plan to raise my FTP',
    'How was my last week of training?'
  ];
  /** The local greeting is a placeholder; the intro card stands in for it until the first send. */
  const isFreshChat = $derived(messages.every((m) => m.id === 'local-greeting'));
  const visibleMessages = $derived(messages.filter((m) => m.id !== 'local-greeting'));

  function useStarter(text: string) {
    input = text;
    tick().then(() => {
      resizeChatInput();
      chatInputEl?.focus();
    });
  }

  // /chat?prompt=… (from Plan and Today): open a new conversation with the text in
  // the composer, unsent, then drop the param so a reload doesn't repeat it.
  let promptApplied = false;
  $effect(() => {
    const prompt = $page.url.searchParams.get('prompt');
    if (!prompt || promptApplied || !historyLoaded || historyLoading) return;
    promptApplied = true;
    (async () => {
      if (conversationId) await newChat();
      useStarter(prompt.slice(0, 2000));
      const url = new URL($page.url);
      url.searchParams.delete('prompt');
      replaceState(url, $page.state);
    })();
  });

  // /chat?conversation=<id>[&reply=<text>] (from a notification): open that thread and send
  // the quick reply once, then drop the params so a reload doesn't repeat it.
  let lastDeepLink = '';
  let pendingReply = $state<string | null>(null);
  $effect(() => {
    const cid = $page.url.searchParams.get('conversation');
    if (!cid || !historyLoaded || historyLoading) return;
    const reply = $page.url.searchParams.get('reply');
    const key = `${cid}|${reply ?? ''}`;
    if (key === lastDeepLink) return;
    lastDeepLink = key;
    (async () => {
      if (!conversations.some((c) => c.id === cid)) {
        const res = await api.getCoachConversations();
        conversations = res?.conversations || conversations;
      }
      if (conversations.some((c) => c.id === cid)) {
        await selectConversation(cid);
        if (reply && reply.trim()) pendingReply = reply.trim().slice(0, 500);
      }
      const url = new URL($page.url);
      url.searchParams.delete('conversation');
      url.searchParams.delete('reply');
      replaceState(url, $page.state);
    })();
  });
  // Send the notification's quick reply once the thread has loaded (and no reply is pending).
  $effect(() => {
    const text = pendingReply;
    if (!text || loading || !conversationId) return;
    pendingReply = null;
    sendQuickReply(text);
  });

  $effect(() => {
    const releaseHeader = claimPageHeader();
    pageHeader.eyebrow = 'Knows your training history';
    pageHeader.actions = [
      { key: 'history', label: 'Past conversations', icon: 'history', onclick: () => (convoMenuOpen = !convoMenuOpen) },
      { key: 'new', label: 'New conversation', icon: 'plus', onclick: () => { convoMenuOpen = false; newChat(); } }
    ];
    return releaseHeader;
  });
</script>

{#if wide}
  <div class="flex h-full min-h-0 w-full">
    <ConversationList
      {conversations}
      activeId={conversationId}
      onSelect={(id) => selectConversation(id)}
      onNew={() => newChat()}
      onDelete={(id) => deleteConversation(id)}
    />
    <main class="flex-1 min-w-0 h-full flex flex-col">
      {@render chatColumn()}
    </main>
    <!-- 768–1199 px (iPad portrait): no room for a third pane; the conversations stay. -->
    {#if viewport.landscape}<CoachContextPane />{/if}
  </div>
{:else}
  {@render chatColumn()}
{/if}

{#snippet chatColumn()}
<div class="relative flex flex-col h-full min-h-0 w-full box-border">
  {#if convoMenuOpen}
    <!-- Past conversations -->
    <div bind:this={convoMenuEl} class="absolute left-4 right-4 top-1 z-30 rounded-[20px] border border-border bg-bg2 shadow-[0_16px_40px_rgba(0,0,0,0.5)] overflow-hidden">
      <div class="flex items-center justify-between px-4 pt-3 pb-2">
        <span class="font-mono text-[10px] tracking-[0.12em] {unreadN ? 'text-blue' : 'text-text2'}">CONVERSATIONS · {unreadLabel(unreadN)}</span>
        <button type="button" class="h-8 border-0 bg-transparent p-0 text-[13px] font-medium text-blue cursor-pointer" onclick={() => { convoMenuOpen = false; newChat(); }}>New chat</button>
      </div>
      <div class="max-h-[50dvh] overflow-y-auto">
        {#if conversations.length === 0}
          <p class="m-0 px-4 pb-4 text-[13px] text-text2">No past conversations yet.</p>
        {/if}
        {#each conversations as c (c.id)}
          <div class="flex items-center gap-2 border-t border-border px-2 {c.id === conversationId ? 'bg-bg3' : ''}">
            <button type="button" class="flex-1 min-w-0 flex items-center gap-2 px-2 py-2.5 border-0 bg-transparent text-left cursor-pointer" aria-label="{c.title || 'New chat'}{c.unread ? ', unread, from your coach' : ''}" onclick={() => { convoMenuOpen = false; selectConversation(c.id); }}>
              <span class="flex-1 min-w-0 flex flex-col gap-0.5">
                <span class="text-sm text-text0 truncate {c.unread ? 'font-semibold' : ''}">{c.title || 'New chat'}</span>
                {#if isCoachThread(c)}
                  <span class="font-mono text-[9px] tracking-[0.1em] truncate {c.unread ? 'text-blue' : 'text-text3'}">FROM YOUR COACH · {triggerLabel(c.trigger)}</span>
                {/if}
                <span class="font-mono text-[10px] text-text2 truncate">{formatConvoDate(c.updated_at || c.created_at)}</span>
              </span>
              {#if c.unread}<span aria-hidden="true" class="flex-none w-[9px] h-[9px] rounded-full bg-blue"></span>{/if}
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

  <div class="flex-1 overflow-y-auto flex flex-col min-h-0 {wide ? 'px-12 pt-10 pb-5' : 'px-5 pt-2 pb-4'}" bind:this={chatContainer} aria-live={wide ? 'polite' : undefined}>
    <div class="flex flex-col {wide ? 'w-full max-w-[680px] mx-auto gap-[18px]' : 'gap-3.5'}">
    {#if isFreshChat && !historyLoading}
      <section aria-labelledby="coach-intro-title" class="flex flex-col {wide ? 'pt-[60px]' : 'pt-4'}">
        <div class="w-14 h-14 rounded-2xl border border-blue/20 bg-blue-dim text-blue flex items-center justify-center mb-6">
          <UiIcon name="chat" size={24} />
        </div>
        {#if !wide && unreadN > 0}
          <button
            type="button"
            class="self-start -mt-2 mb-5 h-9 px-3 rounded-full border border-accent-surface-border bg-accent-surface text-blue font-mono text-[11px] tracking-[0.08em] cursor-pointer"
            onclick={() => (convoMenuOpen = true)}
          >{unreadN} FROM YOUR COACH · OPEN</button>
        {/if}
        <h2 id="coach-intro-title" class="m-0 font-display font-normal text-[34px] leading-[1.1] text-text0">Ask me anything about your training.</h2>
        <p class="m-0 mt-3 text-[16px] leading-relaxed text-text1">
          I can see your workouts, plan, recovery and sleep, so you don't need to paste numbers in. I'll show you what I checked before I answer.
        </p>
        <div aria-label="Suggested questions" class="flex flex-col gap-2.5 mt-6">
          {#each STARTER_PROMPTS as s (s)}
            <button
              type="button"
              class="w-full text-left px-5 py-4 rounded-[18px] border border-border bg-bg2 text-[16px] text-text0 cursor-pointer hover:border-text2/60 transition-colors"
              onclick={() => useStarter(s)}
            >{s}</button>
          {/each}
        </div>
      </section>
    {/if}
    {#if currentConversation && isCoachThread(currentConversation) && !isFreshChat}
      <CoachThreadHeader conversation={currentConversation} {wide} />
    {/if}
    {#each visibleMessages as msg (msg.id)}
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
        <div class="flex flex-col gap-2.5 bg-bg2 border border-border text-text0 break-words min-w-0 {wide ? 'p-5 rounded-[22px] text-[15px] leading-[1.6]' : 'p-4 rounded-[20px] text-sm leading-[1.55]'}">
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
        <div class="self-end max-w-[78%] min-w-0 rounded-[18px_18px_6px_18px] bg-border text-text0 break-words {wide ? 'px-4 py-3 text-[15px] leading-normal' : 'px-3.5 py-3 text-sm leading-[1.45]'}">
          {#if msg.attachments && msg.attachments.length > 0}
            <div class="flex gap-1.5 flex-wrap justify-end {msg.text.trim() || msg.image_urls?.length ? 'mb-2' : ''}">
              {#each msg.attachments as a, i (a.name + i)}
                <span class="inline-flex items-center gap-2 max-w-full h-9 pl-1.5 pr-3 rounded-xl bg-bg2 border border-popover-border text-[13px]">
                  <span aria-hidden="true" class="shrink-0 h-6 px-1.5 rounded-md bg-bg3 font-mono text-[9px] tracking-[0.06em] text-text1 flex items-center">{documentBadge(a.kind || a.name)}</span>
                  <span class="truncate">{a.name}</span>
                </span>
              {/each}
            </div>
          {/if}
          {#if msg.image_urls && msg.image_urls.length > 0}
            <div class="flex gap-2 flex-wrap mb-2 justify-end">
              {#each msg.image_urls as u (u)}
                <a href={u} target={isStandaloneDisplayMode() ? undefined : '_blank'} rel="noopener noreferrer" class="block">
                  <img src={u} alt="upload" class="w-24 h-24 object-cover rounded-xl border border-border" />
                </a>
              {/each}
            </div>
          {/if}
          <!-- Only the text keeps its line breaks: with pre-wrap on the bubble, the template's own
               whitespace before it showed as a leading space on the first line. -->
          <span class="whitespace-pre-wrap">{normalizeTypographyForWrap(msg.text)}</span>
        </div>
      {/if}
    {/each}

    {#if !wide}{@render suggestions()}{/if}
    </div>
  </div>

  <div class="shrink-0 {wide ? 'w-[calc(100%-96px)] max-w-[680px] self-center flex flex-col gap-2.5 mb-8' : 'px-4 pt-1'}" style={wide ? undefined : 'padding-bottom: 12px;'}>
    {#if wide}{@render suggestions()}{/if}
    {#if quickReplies.length > 0}
      <div class={wide ? '' : 'pb-2'}><QuickReplies replies={quickReplies} disabled={loading} onPick={sendQuickReply} /></div>
    {/if}
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

    {#if pendingDocs.length > 0}
      <div class="flex gap-1.5 flex-wrap" aria-label="Attached documents">
        {#each pendingDocs as d (d.id)}
          <span
            class="relative inline-flex items-center gap-2 max-w-full h-10 pl-1.5 pr-8 rounded-xl border text-[13px] {d.status === 'error' ? 'bg-red-dim border-red/40 text-red' : 'bg-bg2 border-popover-border text-text0'}"
            title={d.error ?? d.name}
          >
            <span aria-hidden="true" class="shrink-0 h-7 px-1.5 rounded-md bg-bg3 font-mono text-[9px] tracking-[0.06em] text-text1 flex items-center">{documentBadge(d.name)}</span>
            <span class="flex flex-col min-w-0 leading-tight">
              <span class="truncate max-w-[220px]">{d.name}</span>
              <span class="text-[11px] {d.status === 'error' ? 'text-red' : 'text-text2'}">{d.status === 'reading' ? 'Reading…' : d.status === 'error' ? "Couldn't read" : 'Ready'}</span>
            </span>
            <button
              type="button"
              class="absolute right-1.5 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full border-0 bg-transparent text-text2 text-[12px] flex items-center justify-center cursor-pointer hover:text-text0"
              aria-label="Remove {d.name}"
              onclick={() => { pendingDocs = pendingDocs.filter((x) => x.id !== d.id); }}
            >✕</button>
          </span>
        {/each}
      </div>
    {/if}
    {#if attachError || pendingDocs.some((d) => d.status === 'error')}
      <p role="alert" class="m-0 text-[12px] text-red">{attachError ?? pendingDocs.find((d) => d.status === 'error')?.error}</p>
    {/if}

    <form class="flex gap-2 items-end rounded-[20px] bg-bg2 border border-border {wide ? 'p-2' : 'p-1.5'}" onsubmit={(e) => { e.preventDefault(); if (!loading) void send(); }}>
      <input bind:this={fileInput} type="file" accept={CHAT_FILE_ACCEPT} multiple class="hidden" onchange={onFilesSelected} />
      <button
        type="button"
        class="w-11 h-11 shrink-0 rounded-[14px] border-0 bg-transparent text-text2 flex items-center justify-center cursor-pointer disabled:opacity-40"
        disabled={loading}
        onclick={pickImage}
        aria-label="Attach a photo or document"
        title="Attach a photo, PDF, Word or Excel file"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21 11.5-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l8-8"></path></svg>
      </button>
      <label for="coach-input" class="sr-only">Ask your coach</label>
      <textarea
        id="coach-input"
        bind:this={chatInputEl}
        bind:value={input}
        rows="1"
        maxlength="8000"
        oninput={() => {
          // The iPhone keyboard finishes its predicted word into the box after a send clears
          // it, leaving a lone space the next message started with. Nothing but whitespace
          // is never a message, so clear it.
          if (input && !input.trim()) input = '';
          resizeChatInput();
        }}
        onkeydown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!loading) void send();
          }
        }}
        placeholder={wide ? 'Ask your coach…  (Enter to send, Shift + Enter for a new line)' : 'Ask about your training…'}
        class="flex-1 min-w-0 min-h-11 max-h-[200px] py-3 bg-transparent border-0 text-sm leading-snug text-text0 placeholder:text-text2 outline-none resize-none overflow-hidden"
      ></textarea>
      <button
        type="submit"
        class="w-11 h-11 shrink-0 rounded-[14px] border-0 bg-blue text-on-accent flex items-center justify-center cursor-pointer disabled:opacity-35 disabled:pointer-events-none"
        disabled={loading || docsReading || (!input.trim() && pendingImageUrls.length === 0 && readyDocs.length === 0)}
        aria-label={docsReading ? 'Reading your document…' : 'Send'}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"></path></svg>
      </button>
    </form>
  </div>
</div>
{/snippet}

{#snippet suggestions()}
  {#if !loading && !isFreshChat && promptSuggestions.length > 0 && quickReplies.length === 0}
    <div aria-label="Suggested questions" class="flex flex-wrap gap-2">
      {#each promptSuggestions as s, i (s + String(i))}
        <button
          type="button"
          class="px-3 border text-[13px] cursor-pointer text-left max-w-full truncate bg-bg1 text-text1 {wide ? 'h-[34px] rounded-[17px] border-popover-border hover:border-text3 hover:text-text0' : 'h-9 rounded-[18px] border-border'}"
          onclick={() => { input = s; tick().then(() => { resizeChatInput(); chatInputEl?.focus(); }); }}
        >{s}</button>
      {/each}
    </div>
  {/if}
{/snippet}

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
