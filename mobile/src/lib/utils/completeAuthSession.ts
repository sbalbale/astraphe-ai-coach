import type { Session } from '@supabase/supabase-js';
import { authStore } from '$lib/stores/authStore.svelte';
import { goto } from '$app/navigation';

/**
 * Shared post-verification flow: called once a Supabase session has been
 * confirmed, whether the user arrived via the email confirmation link
 * (auth/callback) or by entering the emailed verification code directly
 * (auth/signup). Onboards the athlete record, applies the session locally,
 * then redirects into the app.
 */
export async function completeAuthSession(session: Session): Promise<void> {
  try {
    await fetch(`${import.meta.env.VITE_API_URL}/v1/athlete/onboard`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session.access_token}`,
        'Content-Type': 'application/json',
      },
    });
  } catch {
    // Non-fatal
  }
  authStore.applySession(session);
  await goto('/onboarding', { replaceState: true });
}
