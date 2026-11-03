export type AccountTier = 'free' | 'trial' | 'premium';

/** Matches backend app/services/tiers.py. */
export const TRIAL_DAYS = 14;

export function normalizeTier(value: unknown): AccountTier {
  const v = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (v === 'premium' || v === 'trial' || v === 'free') return v;
  return 'free';
}

function parseMs(value: unknown): number | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

/** When a trial ends: app_metadata.trial_ends_at, else TRIAL_DAYS after signup. */
export function trialEndsAtMs(meta: Record<string, unknown> | undefined, createdAt: unknown): number | null {
  const explicit = parseMs(meta?.trial_ends_at);
  if (explicit != null) return explicit;
  const created = parseMs(createdAt);
  return created == null ? null : created + TRIAL_DAYS * 86_400_000;
}

/**
 * The tier the backend enforces: a trial past its end is free (the backend also
 * writes that back, but the session's app_metadata only updates on token refresh).
 */
export function effectiveTier(
  meta: Record<string, unknown> | undefined,
  createdAt: unknown,
  nowMs: number = Date.now()
): AccountTier {
  const tier = normalizeTier(meta?.tier);
  if (tier !== 'trial') return tier;
  const ends = trialEndsAtMs(meta, createdAt);
  return ends != null && nowMs >= ends ? 'free' : 'trial';
}

/** Premium features (coach, plan, AI analysis) are open to premium and to an active trial. */
export function hasPremiumAccess(tier: AccountTier): boolean {
  return tier === 'premium' || tier === 'trial';
}
