import type { Session } from '@supabase/supabase-js';
import { authStore } from '$lib/stores/authStore.svelte';
import { goto } from '$app/navigation';

/**
 * Shared post-verification flow: called once a Supabase session has been
 * confirmed, whether the user arrived via the email confirmation link
 * (auth/callback) or by entering the emailed verification code directly
 * (auth/signup). Applies the session locally, then redirects into onboarding.
 *
 * (It used to POST /v1/athlete/onboard, which seeded sample data into the new
 * account; that endpoint is now a no-op kept only for older app versions.)
 */
export async function completeAuthSession(session: Session): Promise<void> {
  authStore.applySession(session);
  await goto('/onboarding', { replaceState: true });
}
