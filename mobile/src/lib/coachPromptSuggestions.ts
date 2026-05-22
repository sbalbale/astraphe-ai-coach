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
  if (/\bbackpacking\b|\bhiking\b|\btrip\b/.test(lowerBlob)) return 'backpacking trip';
  if (/\bpemi\s?loop\b/.test(lowerBlob)) return 'Pemi Loop trip';
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

  const fullOriginal = turns.map((t) => t.text).join('\n');
  const blobLower = cleaned.map((m) => m.plain.toLowerCase()).join(' ');
  const last = cleaned[cleaned.length - 1]!;

  const datePhrase = extractRaceDatePhrase(fullOriginal);
  const daysOut = extractDaysRemaining(blobLower);
  const raceKind = extractRaceKind(blobLower);

  const eventBits = [raceKind, datePhrase].filter(Boolean);
  const eventLabel = eventBits.length ? eventBits.join(' on ') : datePhrase || raceKind;

  const out: string[] = [];

  const lastAi = last.role === 'ai' ? last.plain : '';
  const lastAiLower = lastAi.toLowerCase();
  const lastUser = cleaned.filter((c) => c.role === 'user').slice(-1)[0]?.plain.toLowerCase() ?? '';

  // --- Rich follow-ups when coach just gave a substantive plan (last = AI) ---
  if (last.role === 'ai' && last.plain.length >= 32) {
    const buildMention =
      /\b(build|progressive|phase|volume|aerobic|foundation|baseline)\b/i.test(lastAiLower);
    const intensityLater =
      /\b(intensity|interval|race-specific|threshold|ftp|vo2)\b/i.test(lastAiLower);
    const triContext = /\b(triathlon|swim|bike|run|brick)\b/i.test(blobLower) || raceKind?.includes('tri');

    if (eventLabel && (triContext || raceKind)) {
      const timeHint =
        daysOut != null ? `with about ${daysOut} days to go` : datePhrase ? `leading into ${datePhrase}` : '';
      out.push(
        `For my ${eventLabel}${timeHint ? ` (${timeHint})` : ''}, what should swim vs bike vs run hours look like this month?`
      );
    }

    if (buildMention && (intensityLater || /\btransition\b/i.test(lastAiLower))) {
      out.push(
        `You said to build aerobic volume before adding intensity—what weekly hour or TSS ceiling should I hold until I'm ready for race-specific work?`
      );
      out.push(
        `What exact signal (CTL, TSB, sleep, or HRV) would tell you I'm ready to shift into those race-specific intervals?`
      );
    } else if (buildMention) {
      out.push(
        `Given your aerobic-first plan, sketch two sample weeks: one minimal-time (6–7h) and one normal (10–12h).`
      );
    }

    if (/\b50\b|\b4[5-9]\b|\b3[0-9]\b/.test(lastAiLower) && /\bday/.test(lastAiLower) && raceKind) {
      out.push(
        `Between now and ${datePhrase ?? 'race day'}, split that build into 2–3 mesocycles with a one-line goal each.`
      );
    }

    if (triContext && !out.length) {
      out.push(
        `For this triathlon block, when should I add bricks and at what duration relative to my long bike?`
      );
    }

    // Specific "risk" and "operationalize" instead of generic templates
    if (last.plain.length >= 60) {
      out.push(
        `If my recovery slips during this block, what's the first thing you cut: volume, intensity, or frequency—and for how long?`
      );
    }

    // Only if we still lack variety
    if (out.length < 2) {
      out.push(
        `Turn your last answer into a bullet week plan (Mon–Sun) that matches my numbers and ${eventLabel ?? 'my goal'}.`
      );
    }
  }

  // --- User just spoke; coach hasn't replied yet (last = user) ---
  if (last.role === 'user' && last.plain.length >= 8) {
    const u = lastUser;
    if (/\b(june|july|may|april|march|august|september|october|november|december|january|february)\b/.test(u) && /\btriathlon\b/.test(u)) {
      out.push(
        `Given that race date and sprint distance, what mistakes do athletes make in the first 3 weeks of the build?`
      );
    }
    if (/\b(plan|week|schedule|prioritize)\b/.test(u) && !/\b(race|tri)\b/.test(blobLower)) {
      out.push(`What data from my profile would change your answer if it moved 10% in the wrong direction?`);
    }
    if (/\b(recover|tired|fatigue|sore|burnout)\b/.test(u)) {
      out.push(`What objective signals would tell me I'm actually recovered enough to go hard?`);
    }
    if (/\b(eat|nutrition|carb|fuel)\b/.test(u)) {
      out.push(`Translate that nutrition advice into what I do the evening before a key workout.`);
    }
  }

  return dedupeSuggestions(out, 8);
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
  if (!hasUserParticipation(turns)) {
    return dedupeSuggestions(athlete, 3);
  }

  const blobLower = turns.map((t) => stripMarkdownLite(t.text).toLowerCase()).join(' ');
  const athleteFiltered = filterAthleteAgainstThread(athlete, blobLower, ctlRounded);

  const chat = buildChatContextSuggestions(turns);
  if (!chat.length) {
    return dedupeSuggestions(athleteFiltered, 3);
  }

  const rich = isRichThread(turns);

  if (rich) {
    // Prefer three context-heavy prompts; only back-fill from athlete if we have fewer than 3.
    const primary = dedupeSuggestions(chat, 3);
    if (primary.length >= 3) return primary;
    return dedupeSuggestions([...primary, ...athleteFiltered], 3);
  }

  const merged = [...chat.slice(0, 2), ...athleteFiltered];
  return dedupeSuggestions(merged, 3);
}
