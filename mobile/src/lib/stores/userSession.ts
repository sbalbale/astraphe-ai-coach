import { api } from '$lib/api';
import { athleteStore } from '$lib/stores/athleteStore.svelte';
import { trainingStore } from '$lib/stores/trainingStore.svelte';
import { clearAllWorkoutDetailCache } from '$lib/stores/workoutDetailCache';
import { resetBodyDate } from '$lib/stores/bodyDate.svelte';

/** localStorage keys holding one user's data outside the stores above. */
const USER_SCOPED_STORAGE_KEYS = ['astraphe:dashboard-ai-summary:v3'];

/**
 * Forget everything that belongs to the signed-in user: stores, in-memory and
 * localStorage caches. Called whenever the signed-in user changes (sign-out, or a
 * different account on the same device), so nothing from the previous user is shown.
 */
export function clearUserScopedState(): void {
  athleteStore.reset();
  trainingStore.reset();
  api.clearUserCaches();
  clearAllWorkoutDetailCache();
  resetBodyDate();
  if (typeof localStorage !== 'undefined') {
    for (const key of USER_SCOPED_STORAGE_KEYS) {
      try {
        localStorage.removeItem(key);
      } catch {
        // ignore
      }
    }
  }
}
