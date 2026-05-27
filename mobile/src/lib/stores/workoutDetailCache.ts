import { browser } from '$app/environment';
import { getActivityDetail } from '../services/activityService';

const CACHE_KEY = 'astrape:workout-detail:v1';
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const MAX_ENTRIES = 20;

export interface WorkoutDetailEntry {
  savedAt: number;
  streams: any;
  laps: any[];
  intervals: any;
  zones: any;
}

export type WorkoutDetailCache = Record<string, WorkoutDetailEntry>;

export function loadWorkoutDetailCache(): WorkoutDetailCache {
  if (!browser) return {};
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as WorkoutDetailCache;
    
    // Cleanup expired entries
    const now = Date.now();
    const clean: WorkoutDetailCache = {};
    let hasChanges = false;
    for (const [id, entry] of Object.entries(parsed)) {
      if (now - entry.savedAt < CACHE_TTL_MS) {
        clean[id] = entry;
      } else {
        hasChanges = true;
      }
    }
    
    if (hasChanges) {
      saveRawCache(clean);
    }
    
    return clean;
  } catch {
    return {};
  }
}

function saveRawCache(cache: WorkoutDetailCache): void {
  if (!browser) return;
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
  } catch (e) {
    if (e instanceof Error && e.name === 'QuotaExceededError') {
      // Evict oldest half and retry once
      const sorted = Object.entries(cache).sort((a, b) => a[1].savedAt - b[1].savedAt);
      const half = Math.floor(sorted.length / 2);
      const reduced = Object.fromEntries(sorted.slice(half));
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(reduced));
      } catch {
        // give up
      }
    }
  }
}

export function saveWorkoutDetailToCache(
  workoutId: string,
  data: Omit<WorkoutDetailEntry, 'savedAt'>
): void {
  if (!browser) return;
  const cache = loadWorkoutDetailCache();
  
  cache[workoutId] = {
    ...data,
    savedAt: Date.now()
  };
  
  // LRU Eviction
  const entries = Object.entries(cache);
  if (entries.length > MAX_ENTRIES) {
    const sorted = entries.sort((a, b) => a[1].savedAt - b[1].savedAt);
    const reduced = Object.fromEntries(sorted.slice(entries.length - MAX_ENTRIES));
    saveRawCache(reduced);
  } else {
    saveRawCache(cache);
  }
}

export function clearWorkoutDetailFromCache(workoutId: string): void {
  if (!browser) return;
  const cache = loadWorkoutDetailCache();
  if (cache[workoutId]) {
    delete cache[workoutId];
    saveRawCache(cache);
  }
}

export function clearAllWorkoutDetailCache(): void {
  if (!browser) return;
  localStorage.removeItem(CACHE_KEY);
}

const activePreloads = new Set<string>();

export async function preloadWorkoutDetail(workoutId: string): Promise<void> {
  if (!browser || !workoutId) return;
  if (activePreloads.has(workoutId)) return;

  const cache = loadWorkoutDetailCache();
  if (cache[workoutId]) return; // Already cached

  activePreloads.add(workoutId);
  try {
    const detail = await getActivityDetail(workoutId);
    saveWorkoutDetailToCache(workoutId, {
      streams: detail.streams,
      laps: detail.laps ?? [],
      intervals: detail.intervals,
      zones: detail.zones,
    });
  } catch (e) {
    console.error(`[WorkoutCache] Preload failed for ${workoutId}:`, e);
  } finally {
    activePreloads.delete(workoutId);
  }
}
