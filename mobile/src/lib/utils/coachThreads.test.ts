import { describe, expect, it } from 'vitest';
import {
  coachThreadUrl,
  contextKindLabel,
  isCoachThread,
  latestQuickReplies,
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
