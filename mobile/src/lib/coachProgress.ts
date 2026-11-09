/**
 * Turns the coach's live progress events (GET /v1/coach/conversations/{id}/progress)
 * into the "what the coach checked" checklist shown while a reply is being written.
 */

export type CoachProgressEvent = { status: string; tool?: string; hop?: number; at?: number };
export type CoachStep = { key: string; label: string; done: boolean; count: number };

/** Past-tense label per tool, as it reads once the step is finished. */
const TOOL_LABELS: Record<string, string> = {
  list_workouts: 'Looked through your workouts',
  get_workout_summary: 'Read a workout in detail',
  get_workout_streams_window: 'Checked a stretch of a workout',
  summarize_workouts: 'Summarised your recent workouts',
  compare_workouts: 'Compared workouts',
  get_training_load_series: 'Checked your training load',
  get_biometrics_for_dates: 'Checked your recovery and sleep',
  get_athlete_zones: 'Looked up your zones',
  update_profile: 'Updated your settings',
  list_planned_workouts: 'Checked your plan',
  schedule_workout: 'Scheduled a workout',
  update_planned_workout: 'Updated a planned workout',
  delete_planned_workout: 'Removed a planned workout',
  clear_training_plans: 'Cleared your calendar',
  log_workout: 'Logged a workout',
  update_workout: 'Updated a workout',
  log_biometrics: 'Logged biometrics',
  simulate_training_impact: 'Simulated the training impact',
  calculate_nutrition: 'Worked out nutrition targets',
  web_search: 'Searched the web',
  save_memory: 'Saved a note for next time',
  list_memories: 'Checked what it remembers about you',
  update_memory: 'Updated a saved note',
  internal_scratchpad: 'Planned the answer'
};

export function coachToolLabel(tool?: string): string {
  if (!tool) return 'Used a tool';
  return TOOL_LABELS[tool] ?? `Used ${tool.replace(/_/g, ' ')}`;
}

/**
 * Checklist of what the coach did, oldest first. Repeated tools collapse into one row
 * with a count. While `pending`, the most recent step is still running (not done).
 */
export function buildCoachSteps(events: CoachProgressEvent[], pending: boolean): CoachStep[] {
  const steps: CoachStep[] = [];
  for (const e of events) {
    let key: string | null = null;
    let label = '';
    if (e.status === 'context_ready') {
      key = 'context';
      label = 'Loaded your recent training and recovery';
    } else if (e.status === 'tool') {
      key = `tool:${e.tool ?? ''}`;
      label = coachToolLabel(e.tool);
    }
    if (!key) continue;
    const existing = steps.find((s) => s.key === key);
    if (existing) {
      existing.count += 1;
      // Move it to the end: it's the step running now.
      steps.splice(steps.indexOf(existing), 1);
      steps.push(existing);
    } else {
      steps.push({ key, label, done: true, count: 1 });
    }
  }
  const last = events[events.length - 1];
  const lastIsStep = last && (last.status === 'tool' || last.status === 'context_ready');
  if (pending && lastIsStep && steps.length > 0) steps[steps.length - 1].done = false;
  return steps;
}

/** One-line status for the pending reply, from the latest event. */
export function coachStatusText(events: CoachProgressEvent[]): string {
  const last = events[events.length - 1];
  if (!last || last.status === 'started') return 'Reviewing your data…';
  if (last.status === 'context_ready') return 'Reading your data…';
  if (last.status === 'thinking') return (last.hop ?? 0) > 0 ? 'Putting it together…' : 'Thinking…';
  if (last.status === 'tool') return `${coachToolLabel(last.tool)}…`;
  if (last.status === 'done') return 'Writing the reply…';
  return 'Thinking…';
}
