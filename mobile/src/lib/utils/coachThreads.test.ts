import { describe, expect, it, vi } from 'vitest';
import {
  chatIsOnScreen,
  coachThreadUrl,
  contextKindLabel,
  focusOrOpenClient,
  outgoingMessage,
  isCoachThread,
  latestQuickReplies,
  notificationTarget,
  parseQuickReplies,
  replyActionId,
  replyIndexFromAction,
  safeAppHref,
  triggerLabel,
  unreadCount,
  unreadLabel
} from './coachThreads';

describe('coach threads', () => {
  it('labels triggers as in the design', () => {
    expect(triggerLabel('debrief')).toBe('POST-WORKOUT DEBRIEF');
    expect(triggerLabel('missed')).toBe('MISSED SESSION');
    expect(triggerLabel('weekly')).toBe('WEEKLY SUMMARY');
    expect(triggerLabel('plan_changed')).toBe('PLAN CHANGED');
    expect(triggerLabel('something_new')).toBe('SOMETHING NEW');
    expect(triggerLabel(null)).toBe('CHECK-IN');
  });

  it('counts unread coach threads, optionally skipping the open one', () => {
    const cs = [
      { id: 'a', started_by: 'coach' as const, unread: true },
      { id: 'b', started_by: 'coach' as const, unread: false },
      { id: 'c', started_by: 'coach' as const, unread: true }
    ];
    expect(unreadCount(cs)).toBe(2);
    expect(unreadCount(cs, 'a')).toBe(1);
    expect(unreadLabel(2)).toBe('2 UNREAD');
    expect(unreadLabel(0)).toBe('ALL CAUGHT UP');
    expect(isCoachThread(cs[0])).toBe(true);
    expect(isCoachThread({ id: 'x', started_by: 'athlete' })).toBe(false);
  });

  it('only allows in-app context links', () => {
    expect(safeAppHref('/training?workout_id=w1')).toBe('/training?workout_id=w1');
    expect(safeAppHref('https://evil.example')).toBeNull();
    expect(safeAppHref('//evil.example')).toBeNull();
    expect(safeAppHref(undefined)).toBeNull();
    expect(contextKindLabel('workout')).toBe('WORKOUT');
  });

  it('parses quick replies from a push payload', () => {
    expect(parseQuickReplies('["Felt good","Legs were heavy","Cut it short"]')).toEqual(['Felt good', 'Legs were heavy']);
    expect(parseQuickReplies(['Felt good', 'Felt good', ' ', 3], 4)).toEqual(['Felt good']);
    expect(parseQuickReplies('not json')).toEqual([]);
    expect(parseQuickReplies(undefined)).toEqual([]);
  });

  it('builds deep links and action ids', () => {
    expect(coachThreadUrl('c1')).toBe('/chat?conversation=c1');
    expect(coachThreadUrl('c1', 'Felt good')).toBe('/chat?conversation=c1&reply=Felt+good');
    expect(replyIndexFromAction(replyActionId(1))).toBe(1);
    expect(replyIndexFromAction('open')).toBeNull();
  });

  it('offers quick replies only under the latest coach message', () => {
    expect(latestQuickReplies([{ role: 'ai', quick_replies: ['Felt good'] }])).toEqual(['Felt good']);
    expect(latestQuickReplies([{ role: 'ai', quick_replies: ['Felt good'] }, { role: 'user' }])).toEqual([]);
    expect(latestQuickReplies([{ role: 'ai', quick_replies: ['Felt good'], streaming: true }])).toEqual([]);
  });
});

describe('outgoingMessage', () => {
  const composer = { input: '  half-typed question ', images: ['img-1'], docs: [{ name: 'plan.pdf' }] };
  it('a quick reply goes alone, leaving the draft and staged files', () => {
    expect(outgoingMessage('Felt good', composer)).toEqual({ text: 'Felt good', images: [], docs: [], fromComposer: false });
    expect(outgoingMessage('  ', composer)).toBeNull();
  });
  it('the composer sends its text and staged files', () => {
    expect(outgoingMessage(null, composer)).toEqual({ text: 'half-typed question', images: ['img-1'], docs: [{ name: 'plan.pdf' }], fromComposer: true });
    expect(outgoingMessage(null, { input: ' ', images: [], docs: [] })).toBeNull();
  });
});

describe('notification click (focusOrOpenClient)', () => {
  const ORIGIN = 'https://app.example';
  const clientsWith = (client: Record<string, unknown> | null) => ({
    matchAll: vi.fn().mockResolvedValue(client ? [{ url: `${ORIGIN}/dashboard`, focus: vi.fn().mockResolvedValue(undefined), ...client }] : []),
    openWindow: vi.fn().mockResolvedValue(null)
  });

  it('navigates and focuses an open app window', async () => {
    const focus = vi.fn().mockResolvedValue(undefined);
    const clients = clientsWith({ navigate: vi.fn().mockResolvedValue({ url: '', focus }) });
    await focusOrOpenClient(clients, ORIGIN, '/chat?conversation=c1');
    expect(focus).toHaveBeenCalled();
    expect(clients.openWindow).not.toHaveBeenCalled();
  });

  it('opens a window when navigate rejects (uncontrolled client)', async () => {
    const clients = clientsWith({ navigate: vi.fn().mockRejectedValue(new TypeError('not controlled')) });
    await focusOrOpenClient(clients, ORIGIN, '/chat?conversation=c1');
    expect(clients.openWindow).toHaveBeenCalledWith('/chat?conversation=c1');
  });

  it('opens a window when navigate resolves null, or when no app window is open', async () => {
    const clients = clientsWith({ navigate: vi.fn().mockResolvedValue(null) });
    await focusOrOpenClient(clients, ORIGIN, '/readiness');
    expect(clients.openWindow).toHaveBeenCalledWith('/readiness');
    const none = clientsWith(null);
    await focusOrOpenClient(none, ORIGIN, '/readiness');
    expect(none.openWindow).toHaveBeenCalledWith('/readiness');
  });

  it('a refused focus after navigating does not open a second window', async () => {
    const clients = clientsWith({ navigate: vi.fn().mockResolvedValue({ url: '', focus: vi.fn().mockRejectedValue(new Error('no')) }) });
    await focusOrOpenClient(clients, ORIGIN, '/readiness');
    expect(clients.openWindow).not.toHaveBeenCalled();
  });
});

describe('coach reply while the chat is on screen (chatIsOnScreen)', () => {
  const ORIGIN = 'https://app.example';
  const clients = (...list: { url: string; visibilityState?: 'visible' | 'hidden' }[]) => ({
    matchAll: vi.fn().mockResolvedValue(list.map((c) => ({ focus: vi.fn(), ...c })))
  });

  it('is on screen when a visible window shows the chat', async () => {
    expect(await chatIsOnScreen(clients({ url: `${ORIGIN}/chat`, visibilityState: 'visible' }), ORIGIN)).toBe(true);
    expect(await chatIsOnScreen(clients({ url: `${ORIGIN}/chat/?x=1`, visibilityState: 'visible' }), ORIGIN)).toBe(true);
  });

  it('is not when the chat is in the background, another page is open, or no window', async () => {
    expect(await chatIsOnScreen(clients({ url: `${ORIGIN}/chat`, visibilityState: 'hidden' }), ORIGIN)).toBe(false);
    expect(await chatIsOnScreen(clients({ url: `${ORIGIN}/dashboard`, visibilityState: 'visible' }), ORIGIN)).toBe(false);
    expect(await chatIsOnScreen(clients({ url: 'https://other.example/chat', visibilityState: 'visible' }), ORIGIN)).toBe(false);
    expect(await chatIsOnScreen(clients(), ORIGIN)).toBe(false);
  });
});

describe('notificationTarget', () => {
  it('opens the thread a coach notification names, even when its url is just /chat', () => {
    expect(notificationTarget({ url: '/chat', conversation_id: 'c1', type: 'reply' })).toBe('/chat?conversation=c1');
  });
  it('uses the url for other notifications', () => {
    expect(notificationTarget({ url: '/readiness' })).toBe('/readiness');
    expect(notificationTarget(undefined)).toBeUndefined();
  });
});
