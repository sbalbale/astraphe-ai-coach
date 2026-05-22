/**
 * Builds prompt suggestions from athlete signals and recent chat turns.
 */

export type CoachChatTurn = { role: 'user' | 'ai'; text: string };

export type CoachSuggestionInputs = {
  ctl: number;
  tsb: number;
  sleepScore: number | null;
  hrvZScore: number | null;
  /** Recent messages (newest last). Empty/streaming bubbles should be omitted by caller. */
  recentMessages?: CoachChatTurn[];
  /** AI-extracted facts from long-term memory. */
  memories?: string[];
};

function stripMarkdownLite(s: string): string {
  return s
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*?|__|\*|_|#+\s?/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

function dedupeSuggestions(candidates: string[], limit: number): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of candidates) {
    const t = c.trim();
    if (!t) continue;
    const key = t.toLowerCase().slice(0, 140);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(t);
    if (out.length >= limit) break;
  }
  return out;
}

const MONTH_RE =
  /\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(20\d{2}))?\b/i;

function titleCaseMonth(m: string): string {
  return m.charAt(0).toUpperCase() + m.slice(1).toLowerCase();
}

interface DetectedEvent {
  kind: 'race' | 'trip';
  label: string;
  datePhrase: string | null;
}

/** 
 * Smarter event detection that pairs dates with specific events 
 * mentioned in the same vicinity, and distinguishes between goals.
 */
function detectEvents(turns: CoachChatTurn[]): DetectedEvent[] {
  const events: DetectedEvent[] = [];
  const fullText = turns.map(t => t.text).join('\n').toLowerCase();

  // 1. Detect Race (Primary Target)
  let raceKind: string | null = null;
  if (/\bsprint\b/.test(fullText) && /\btriathlon\b/.test(fullText)) raceKind = 'sprint triathlon';
  else if (/\bolympic\b/.test(fullText) && /\btriathlon\b/.test(fullText)) raceKind = 'Olympic triathlon';
  else if (/\b70\.3\b|half[-\s]?iron/.test(fullText)) raceKind = '70.3 / half-Iron';
  else if (/\b140\.6\b|\bfull\s+iron\b|\bironman\b/.test(fullText) && /\btriathlon\b/.test(fullText)) raceKind = 'full-distance triathlon';
  else if (/\bmarathon\b/.test(fullText)) raceKind = 'marathon';
  else if (/\brace\b|\btarget\b/.test(fullText)) raceKind = 'target event';

  if (raceKind) {
    // Look for a date specifically associated with the race/target in the text
    const raceMatch = turns.find(t => {
      const low = t.text.toLowerCase();
      return (low.includes(raceKind!) || low.includes('race') || low.includes('target')) && MONTH_RE.test(low);
    });
    let raceDate: string | null = null;
    if (raceMatch) {
      const m = raceMatch.text.match(MONTH_RE);
      if (m) raceDate = `${titleCaseMonth(m[1]!)} ${m[2]}`;
    }
    events.push({ kind: 'race', label: raceKind, datePhrase: raceDate });
  }

  // 2. Detect Trip (Secondary Event)
  let tripKind: string | null = null;
  if (/\bbackpacking\b|\bhiking\b/.test(fullText)) tripKind = 'backpacking trip';
  else if (/\btrip\b|\badventure\b/.test(fullText)) tripKind = 'upcoming trip';
  if (/\bpemi\s?loop\b/.test(fullText)) tripKind = 'Pemi Loop trip';

  if (tripKind) {
    const tripMatch = turns.find(t => {
      const low = t.text.toLowerCase();
      return (low.includes(tripKind!) || low.includes('backpacking') || low.includes('hiking') || low.includes('loop')) && 
             (MONTH_RE.test(low) || /\bthis\s+weekend\b/.test(low) || /\btomorrow\b/.test(low));
    });
    let tripDate: string | null = null;
    if (tripMatch) {
      const low = tripMatch.text.toLowerCase();
      if (low.includes('this weekend')) {
        tripDate = 'this weekend';
      } else if (low.includes('tomorrow')) {
        tripDate = 'tomorrow';
      } else {
        const m = tripMatch.text.match(MONTH_RE);
        if (m) tripDate = `${titleCaseMonth(m[1]!)} ${m[2]}`;
      }
    }
    events.push({ kind: 'trip', label: tripKind, datePhrase: tripDate });
  }

  return events;
}

/** Pull "June 22" / "June 22nd" from user-visible text (any turn). */
function extractRaceDatePhrase(fullBlob: string): string | null {
  const m = fullBlob.match(MONTH_RE);
  if (!m) return null;
  const mon = titleCaseMonth(m[1]!);
  const day = String(Number.parseInt(m[2]!, 10));
  return `${mon} ${day}`;
}

function extractDaysRemaining(fullBlob: string): number | null {
  const m = fullBlob.match(/\b(\d{1,3})\s+days\s+remaining\b/i);
  if (m) return Number.parseInt(m[1]!, 10);
  const m2 = fullBlob.match(/\bwith\s+(\d{1,3})\s+days\s+remaining\b/i);
  if (m2) return Number.parseInt(m2[1]!, 10);
  return null;
}

function extractRaceKind(lowerBlob: string): string | null {
  if (/\bsprint\b/.test(lowerBlob) && /\btriathlon\b/.test(lowerBlob)) return 'sprint triathlon';
  if (/\bolympic\b/.test(lowerBlob) && /\btriathlon\b/.test(lowerBlob)) return 'Olympic triathlon';
  if (/\b70\.3\b|half[-\s]?iron/.test(lowerBlob)) return '70.3 / half-Iron';
  if (/\b140\.6\b|\bfull\s+iron\b|\bironman\b/.test(lowerBlob) && /\btriathlon\b/.test(lowerBlob))
    return 'full-distance triathlon';
  if (/\bmarathon\b/.test(lowerBlob)) return 'marathon';
  return null;
}

function conversationDepth(turns: CoachChatTurn[]): number {
  return turns.filter((t) => t.text.trim()).length;
}

function threadDiscussedCtl(blob: string, ctlRounded: number): boolean {
  if (!Number.isFinite(ctlRounded) || ctlRounded <= 0) return false;
  if (!/\bctl\b/i.test(blob)) return false;
  for (const d of [-2, -1, 0, 1, 2]) {
    const n = ctlRounded + d;
    if (new RegExp(`\\b${n}\\b`).test(blob)) return true;
  }
  // Coach/user often cite decimals, e.g. "CTL of 54.52"
  if (new RegExp(`\\b${ctlRounded}[\\.,]\\d+\\b`).test(blob)) return true;
  if (new RegExp(`\\b${ctlRounded - 1}[\\.,]\\d+\\b`).test(blob)) return true;
  return /\bctl\b[^.]{0,48}\d{2}[\.,]\d+/i.test(blob);
}

function threadDiscussedTsb(blob: string): boolean {
  return /\btsb\b/i.test(blob) && /\b\d{1,2}(\.\d+)?\b/.test(blob);
}

/** Signals-only prompts (2–3). */
export function buildCoachPromptSuggestions(input: Omit<CoachSuggestionInputs, 'recentMessages'>): string[] {
  const { ctl, tsb, sleepScore, hrvZScore } = input;
  const out: string[] = [];

  const tsbRounded = Number.isFinite(tsb) ? Math.round(tsb) : null;
  const ctlRounded = Number.isFinite(ctl) ? Math.round(ctl) : 0;

  // 1. High Fatigue / Recovery (TSB)
  if (tsbRounded !== null && tsbRounded < -20) {
    out.push(`My Form is down to ${tsbRounded}. Should I pivot tomorrow's session to active recovery?`);
  } else if (tsbRounded !== null && tsbRounded > 15) {
    out.push(`My TSB is +${tsbRounded}. Is this a good window to push a breakthrough workout?`);
  }

  // 2. Autonomic Strain (HRV)
  if (hrvZScore !== null && Number.isFinite(hrvZScore)) {
    if (hrvZScore < -1.5) {
      out.push(`My HRV is deeply suppressed (${hrvZScore.toFixed(1)} SD). Am I at risk of overtraining?`);
    } else if (hrvZScore > 1.0) {
      out.push(`My HRV is up today! Should I take advantage of this recovery window for extra intensity?`);
    }
  }

  // 3. Fitness Level (CTL) - Contextualized
  if (ctlRounded > 0) {
    if (ctlRounded < 40) {
      out.push(`With my CTL at ${ctlRounded}, how should I safely ramp up volume for my upcoming goals?`);
    } else if (ctlRounded > 80) {
      out.push(`My fitness is high (CTL: ${ctlRounded}). How do I maintain this without accumulating too much fatigue?`);
    } else {
      out.push(`Given my current fitness and recovery, what's the best focus for my training this week?`);
    }
  }

  // 4. Sleep
  if (sleepScore !== null && Number.isFinite(sleepScore) && sleepScore < 60) {
    out.push(`I had a rough night (Sleep Score: ${Math.round(sleepScore)}). How does this change today's plan?`);
  }

  // Fallbacks if we still have space or nothing matched
  if (out.length < 3) {
    out.push(`Look at my last 7 days of data—what's one specific adjustment you'd recommend?`);
  }
  if (out.length < 3 && ctlRounded <= 0) {
    out.push(`I'm just starting out. How do I build a sustainable aerobic foundation?`);
  }

  return out.slice(0, 3);
}

function filterAthleteAgainstThread(
  athlete: string[],
  conversationBlobLower: string,
  ctlRounded: number
): string[] {
  return athlete.filter((s) => {
    const sl = s.toLowerCase();
    if (sl.startsWith('my ctl is') && threadDiscussedCtl(conversationBlobLower, ctlRounded)) {
      return false;
    }
    if (sl.startsWith('my tsb is') && threadDiscussedTsb(conversationBlobLower)) {
      return false;
    }
    return true;
  });
}

/**
 * Rich follow-ups from last coach reply + user-stated goals (race, date, phase language).
 */
export function buildChatContextSuggestions(turns: CoachChatTurn[]): string[] {
  const cleaned = turns
    .filter((m) => m.text.trim())
    .map((m) => ({
      role: m.role,
      plain: stripMarkdownLite(m.text)
    }));

  if (cleaned.length < 2) return [];

  const blobLower = cleaned.map((m) => m.plain.toLowerCase()).join(' ');
  const last = cleaned[cleaned.length - 1]!;

  const detectedEvents = detectEvents(turns);
  const primaryRace = detectedEvents.find(e => e.kind === 'race');
  const secondaryTrip = detectedEvents.find(e => e.kind === 'trip');

  // Logic prefers the primary race if it has a date, otherwise any detected event
  const primaryEvent = primaryRace?.datePhrase ? primaryRace : (secondaryTrip || primaryRace);
  const eventLabel = primaryEvent ? (primaryEvent.datePhrase ? `${primaryEvent.label} on ${primaryEvent.datePhrase}` : primaryEvent.label) : null;

  const out: string[] = [];

  const lastAi = last.role === 'ai' ? last.plain : '';
  const lastAiLower = lastAi.toLowerCase();
  const lastUser = cleaned.filter((c) => c.role === 'user').slice(-1)[0]?.plain.toLowerCase() ?? '';

  // --- Rich follow-ups when coach just gave a substantive plan (last = AI) ---
  if (last.role === 'ai' && last.plain.length >= 32) {
    const buildMention = /\b(build|progressive|phase|volume|aerobic|foundation|baseline)\b/i.test(lastAiLower);
    const intensityLater = /\b(intensity|interval|race-specific|threshold|ftp|vo2)\b/i.test(lastAiLower);

    if (eventLabel) {
      const timeHint = primaryEvent?.datePhrase === 'this weekend' ? 'this weekend' : primaryEvent?.datePhrase ? `leading into ${primaryEvent.datePhrase}` : '';
      
      if (primaryRace) {
        out.push(`For my ${primaryRace.label}${primaryRace.datePhrase ? ` on ${primaryRace.datePhrase}` : ''}, what should swim vs bike vs run hours look like this month?`);
      }
      
      if (secondaryTrip) {
        out.push(`How should I adjust my intensity next week to recover from my ${secondaryTrip.label}${secondaryTrip.datePhrase ? ` ${secondaryTrip.datePhrase}` : ''}?`);
      }
    }

    if (buildMention && (intensityLater || /\btransition\b/i.test(lastAiLower))) {
      out.push(`You said to build aerobic volume before adding intensity—what TSS ceiling should I hold until I'm ready for race-specific work?`);
      out.push(`What exact signal (CTL, TSB, sleep, or HRV) would tell you I'm ready to shift into those race-specific intervals?`);
    }

    if (last.plain.length >= 60 && primaryRace) {
      out.push(`If my recovery slips during this ${primaryRace.label} build, what's the first thing you cut: volume, intensity, or frequency?`);
    }
  }

  // --- User just spoke; coach hasn't replied yet (last = user) ---
  if (last.role === 'user' && last.plain.length >= 8) {
    if (primaryRace && primaryRace.datePhrase) {
      out.push(`Given my ${primaryRace.label} is on ${primaryRace.datePhrase}, what mistakes do athletes usually make in the first 3 weeks of this build?`);
    }
    if (secondaryTrip) {
      out.push(`Will my ${secondaryTrip.label}${secondaryTrip.datePhrase ? ` ${secondaryTrip.datePhrase}` : ''} have a significant impact on my long-term fitness (CTL)?`);
    }
    if (/\b(recover|tired|fatigue|sore|burnout)\b/.test(lastUser)) {
      out.push(`What objective signals would tell me I'm actually recovered enough to go hard again?`);
    }
  }

  return dedupeSuggestions(out, 8);
}

/** Converts raw memory strings into proactive conversational chips. */
export function buildMemorySuggestions(memories: string[]): string[] {
  const out: string[] = [];

  for (const memory of memories) {
    const m = memory.toLowerCase();

    // Triathlon context
    if (m.includes('triathlon')) {
      const dist = m.includes('sprint')
        ? 'sprint'
        : m.includes('olympic')
          ? 'Olympic'
          : m.includes('70.3')
            ? '70.3'
            : '';
      out.push(`Based on my ${dist} triathlon target, are my CTL and volume ramp looking realistic?`);
    }

    // Goal/Date context
    if (m.includes('goal') || m.includes('target') || m.includes('on ')) {
      const parts = m.split(' on ');
      const raceName = parts[0]?.replace('goal is ', '').replace('target is ', '') || 'target event';
      out.push(`Given my ${raceName.trim()}, what should I focus on in training this week?`);
    }

    // Injury context
    if (m.includes('injury') || m.includes('hurt') || m.includes('pain') || m.includes('sore')) {
      out.push(`How should I adjust my intensity to manage that injury context you mentioned?`);
    }

    // Trip/Backpacking context
    if (m.includes('backpacking') || m.includes('trip') || m.includes('hiking')) {
      out.push(`How will my upcoming trip impact my fitness and race readiness?`);
    }
  }

  return out;
}

/** True when there has been at least one user turn in the thread (not only the coach greeting). */
function hasUserParticipation(turns: CoachChatTurn[]): boolean {
  return turns.some((t) => t.role === 'user' && t.text.trim().length > 0);
}

function isRichThread(turns: CoachChatTurn[]): boolean {
  if (conversationDepth(turns) >= 5) return true;
  const b = turns.map((t) => stripMarkdownLite(t.text).toLowerCase()).join(' ');
  if (/\btriathlon\b/.test(b) && MONTH_RE.test(turns.map((t) => t.text).join(' '))) return true;
  if (/\b(june|july|may)\s+\d{1,2}/i.test(b) && /\bctl\b/.test(b) && /\btsb\b/.test(b)) return true;
  return false;
}

/**
 * Merges athlete-based and chat-context suggestions; prefers specific chat follow-ups when the thread is substantive.
 */
export function buildMergedCoachPromptSuggestions(input: CoachSuggestionInputs): string[] {
  const ctlRounded = Number.isFinite(input.ctl) ? Math.round(input.ctl) : 0;
  const athlete = buildCoachPromptSuggestions({
    ctl: input.ctl,
    tsb: input.tsb,
    sleepScore: input.sleepScore,
    hrvZScore: input.hrvZScore
  });

  const turns = input.recentMessages ?? [];
  const memories = input.memories ?? [];

  const memorySuggestions = buildMemorySuggestions(memories);

  if (!hasUserParticipation(turns)) {
    // Brand new chat: Prioritize memory-based questions so the coach feels like they "know" the user
    return dedupeSuggestions([...memorySuggestions, ...athlete], 3);
  }

  const blobLower = turns.map((t) => stripMarkdownLite(t.text).toLowerCase()).join(' ');
  const athleteFiltered = filterAthleteAgainstThread(athlete, blobLower, ctlRounded);

  const chat = buildChatContextSuggestions(turns);
  if (!chat.length) {
    return dedupeSuggestions([...memorySuggestions, ...athleteFiltered], 3);
  }

  const rich = isRichThread(turns);

  if (rich) {
    // Prefer three context-heavy prompts; only back-fill from athlete if we have fewer than 3.
    const primary = dedupeSuggestions(chat, 3);
    if (primary.length >= 3) return primary;
    return dedupeSuggestions([...primary, ...memorySuggestions, ...athleteFiltered], 3);
  }

  const merged = [...chat.slice(0, 2), ...memorySuggestions, ...athleteFiltered];
  return dedupeSuggestions(merged, 3);
}
