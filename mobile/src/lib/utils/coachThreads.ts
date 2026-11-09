/**
 * Coach-started threads (post-workout debrief, missed session, weekly summary…) and the
 * push notifications that open them. Pure helpers: used by the chat page and by the
 * service worker, so no `$lib` imports here.
 */

export type CoachThreadContext = {
  kind?: string;
  id?: string;
  title?: string;
  meta?: string;
  href?: string;
};

export type CoachConversation = {
  id: string;
  title?: string | null;
  created_at?: string;
  updated_at?: string;
  started_by?: 'athlete' | 'coach' | null;
  trigger?: string | null;
  context?: CoachThreadContext | null;
  unread?: boolean | null;
};

const TRIGGER_LABELS: Record<string, string> = {
  debrief: 'POST-WORKOUT DEBRIEF',
  missed: 'MISSED SESSION',
  weekly: 'WEEKLY SUMMARY',
  readiness: 'MORNING READINESS',
  ready: 'MORNING READINESS',
  plan_changed: 'PLAN CHANGED',
  plan: 'PLAN CHANGED'
};

/** "FROM YOUR COACH · <label>" label for a thread's trigger. */
export function triggerLabel(trigger: string | null | undefined): string {
  const t = (trigger ?? '').trim().toLowerCase();
  if (!t) return 'CHECK-IN';
  return TRIGGER_LABELS[t] ?? t.replace(/[_-]+/g, ' ').toUpperCase();
}

export function isCoachThread(c: CoachConversation | null | undefined): boolean {
  return c?.started_by === 'coach';
}

/** Unread coach-started threads, optionally not counting the open one. */
export function unreadCount(conversations: CoachConversation[], exceptId: string | null = null): number {
  return conversations.filter((c) => c.unread && c.id !== exceptId).length;
}

export function unreadLabel(n: number): string {
  return n > 0 ? `${n} UNREAD` : 'ALL CAUGHT UP';
}

/** Context card kind label: WORKOUT, PLAN, WEEK… */
export function contextKindLabel(kind: string | null | undefined): string {
  const k = (kind ?? '').trim();
  return k ? k.replace(/[_-]+/g, ' ').toUpperCase() : 'CONTEXT';
}

/** Only same-origin app paths ("/training?workout_id=…"); anything else is dropped. */
export function safeAppHref(href: string | null | undefined): string | null {
  if (typeof href !== 'string') return null;
  const h = href.trim();
  if (!h.startsWith('/') || h.startsWith('//') || h.startsWith('/\\')) return null;
  return h;
}

/**
 * Quick replies carried in a push payload: a JSON string (FCM data values are strings)
 * or an array. At most `max`, trimmed, non-empty, deduplicated.
 */
export function parseQuickReplies(raw: unknown, max = 2): string[] {
  let list: unknown = raw;
  if (typeof raw === 'string') {
    try {
      list = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(list)) return [];
  const out: string[] = [];
  for (const v of list) {
    if (typeof v !== 'string') continue;
    const t = v.trim().slice(0, 80);
    if (t && !out.includes(t)) out.push(t);
    if (out.length >= max) break;
  }
  return out;
}

/** `/chat?conversation=<id>` (and `&reply=<text>` to send a quick reply on open). */
export function coachThreadUrl(conversationId: string, reply?: string | null): string {
  const p = new URLSearchParams({ conversation: conversationId });
  if (reply && reply.trim()) p.set('reply', reply.trim().slice(0, 500));
  return `/chat?${p.toString()}`;
}

/** Notification action ids for quick replies ("reply-0", "reply-1") and opening the chat. */
export const OPEN_CHAT_ACTION = 'open';
export function replyActionId(i: number): string {
  return `reply-${i}`;
}
export function replyIndexFromAction(action: string | null | undefined): number | null {
  const m = /^reply-(\d)$/.exec(action ?? '');
  return m ? Number(m[1]) : null;
}

/**
 * What a chat send posts. A quick reply (non-null) is its own message: never the typed
 * draft or the staged photos/documents, which stay in the composer. Null = nothing to send.
 */
export function outgoingMessage<D>(
  quickReply: string | null,
  composer: { input: string; images: string[]; docs: D[] }
): { text: string; images: string[]; docs: D[]; fromComposer: boolean } | null {
  if (quickReply !== null) {
    const text = quickReply.trim();
    return text ? { text, images: [], docs: [], fromComposer: false } : null;
  }
  const text = composer.input.trim();
  if (!text && composer.images.length === 0 && composer.docs.length === 0) return null;
  return { text, images: composer.images, docs: composer.docs, fromComposer: true };
}

type SwWindowClient = {
  url: string;
  visibilityState?: 'visible' | 'hidden' | 'prerender';
  navigate?: (url: string) => Promise<unknown>;
  focus: () => Promise<unknown>;
};
type SwClients = {
  matchAll: (opts: { type: 'window'; includeUncontrolled: boolean }) => Promise<readonly SwWindowClient[]>;
  openWindow: (url: string) => Promise<unknown>;
};

/**
 * Notification click (service worker): reuse an open app window, else open one.
 * `navigate()` rejects for windows this worker doesn't control (matchAll includes them),
 * and resolves null when it can't navigate; then a new window is opened instead, so the
 * click never does nothing.
 */
export async function focusOrOpenClient(clients: SwClients, origin: string, targetUrl: string): Promise<void> {
  const list = await clients.matchAll({ type: 'window', includeUncontrolled: true });
  const client = list.find((c) => c.url.startsWith(origin));
  if (client && typeof client.navigate === 'function') {
    let navigated: SwWindowClient | null = null;
    try {
      navigated = ((await client.navigate(targetUrl)) as SwWindowClient | null) ?? null;
    } catch {
      navigated = null; // uncontrolled client: open a new window below
    }
    if (navigated) {
      try {
        await (navigated.focus ? navigated.focus() : client.focus());
      } catch {
        // focus can be refused; the window already shows the page
      }
      return;
    }
  }
  await clients.openWindow(targetUrl);
}

/**
 * A coach-reply push while the chat is on screen: the athlete is watching the reply arrive,
 * so the notification is pointless. True when a visible app window is on /chat.
 * (The chat page doesn't keep the open conversation in its URL, so it's any chat.)
 */
export async function chatIsOnScreen(clients: Pick<SwClients, 'matchAll'>, origin: string): Promise<boolean> {
  const list = await clients.matchAll({ type: 'window', includeUncontrolled: true });
  return list.some((c) => {
    if (!c.url.startsWith(origin) || c.visibilityState !== 'visible') return false;
    try {
      return new URL(c.url).pathname.replace(/\/+$/, '') === '/chat';
    } catch {
      return false;
    }
  });
}

/** Last message from the coach that still offers quick replies (only when it is the latest message). */
export function latestQuickReplies(messages: { role: string; quick_replies?: string[] | null; streaming?: boolean }[]): string[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== 'ai' || last.streaming) return [];
  return (last.quick_replies ?? []).filter((q) => typeof q === 'string' && q.trim()).slice(0, 4);
}

/**
 * Where tapping a notification goes: its coach thread when it names one, else its url.
 * (Coach replies sent url "/chat", which opened the chat tab instead of the thread.)
 */
export function notificationTarget(
  data: { url?: unknown; conversation_id?: unknown; [key: string]: unknown } | null | undefined
): string | undefined {
  const id = data?.conversation_id;
  if (typeof id === 'string' && id.trim()) return coachThreadUrl(id.trim());
  return typeof data?.url === 'string' ? data.url : undefined;
}
