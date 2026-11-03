/**
 * Onboarding is "done" when the profile has the fields onboarding asks for.
 * Used by the layout (redirects) and the dashboard's get-set-up checklist.
 */
export function isProfileComplete(p: Record<string, any> | null | undefined): boolean {
  const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');
  const sport0 = str(p?.sport_focus?.[0]);
  const w = Number(p?.weight_kg);
  const h = Number(p?.height_cm);
  return (
    !!sport0 &&
    !!str(p?.measurement_units) &&
    !!str(p?.time_format) &&
    !!str(p?.date_of_birth) &&
    !!str(p?.gender) &&
    Number.isFinite(w) &&
    w > 0 &&
    Number.isFinite(h) &&
    h > 0
  );
}

/** First name for greetings, from the profile or auth metadata. */
export function firstName(...candidates: unknown[]): string {
  for (const c of candidates) {
    if (typeof c === 'string' && c.trim()) return c.trim().split(/\s+/)[0];
  }
  return '';
}
