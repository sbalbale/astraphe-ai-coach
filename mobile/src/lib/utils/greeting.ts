export type TimeOfDayPeriod = 'morning' | 'afternoon' | 'evening';

export function getTimeOfDayPeriod(date = new Date()): TimeOfDayPeriod {
  const hour = date.getHours();
  if (hour >= 5 && hour < 12) return 'morning';
  if (hour >= 12 && hour < 18) return 'afternoon';
  return 'evening';
}

export function getTimeOfDayGreeting(date = new Date()): string {
  const period = getTimeOfDayPeriod(date);
  return `Good ${period}`;
}

export function normalizeLeadingTimeOfDayGreeting(text: string, date = new Date()): string {
  const greeting = getTimeOfDayGreeting(date);
  return text.replace(/^\s*good\s+(morning|afternoon|evening)\b/i, greeting);
}

export function stripLeadingTimeOfDayGreeting(text: string): string {
  const stripped = text
    .trim()
    .replace(/^good\s+(morning|afternoon|evening)\b[\s,!.:-]*/i, '')
    .trimStart();

  if (!stripped) return stripped;
  return stripped.charAt(0).toUpperCase() + stripped.slice(1);
}
