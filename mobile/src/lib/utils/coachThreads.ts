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

/** Last message from the coach that still offers quick replies (only when it is the latest message). */
export function latestQuickReplies(messages: { role: string; quick_replies?: string[] | null; streaming?: boolean }[]): string[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== 'ai' || last.streaming) return [];
  return (last.quick_replies ?? []).filter((q) => typeof q === 'string' && q.trim()).slice(0, 4);
}
