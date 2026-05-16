import { getAuthHeaders } from '$lib/apiAuth';

const VITE_API_URL = import.meta.env.VITE_API_URL;
const API_URL = VITE_API_URL && VITE_API_URL !== 'undefined' ? VITE_API_URL : 'http://localhost:8000';

export interface ActivityStreams {
  time_series: {
    time?: number[];
    heartrate?: number[];
    watts?: number[];
    cadence?: number[];
    velocity_smooth?: number[];
    distance?: number[];
    latlng?: [number, number][];
    altitude?: number[];
    grade_smooth?: number[];
    moving?: boolean[];
  };
  resolution_seconds: number;
}

export interface ActivityLap {
  lap_index: number;
  elapsed_time: number;
  moving_time: number;
  distance: number;
  average_heartrate: number | null;
  max_heartrate: number | null;
  average_watts: number | null;
  average_cadence: number | null;
  average_speed: number | null;
  start_index?: number;
  end_index?: number;
}

export interface RowingInterval {
  split_number: number;
  distance: number;
  elapsed_time: number;
  pace_per_500m: number | null;
  average_heartrate: number | null;
  average_watts: number | null;
  average_cadence: number | null;
  source: string;
}

export interface ActivityIntervals {
  intervals: RowingInterval[];
  source: 'laps' | 'stream_derived';
  splits_metric: object[];
  sport: string;
}

export interface ZoneDef {
  zone: number;
  name: string;
  min_bpm: number;
  max_bpm: number;
}

export interface ActivityZones {
  distribution: Record<string, number>;
  zones: ZoneDef[];
  method: string;
  data_points: number;
  source?: 'stream' | 'summary';
}

/** True when Strava stored a usable velocity stream (pace/speed line charts). */
export function streamsHaveVelocity(streams: ActivityStreams | null): boolean {
  const vel = streams?.time_series?.velocity_smooth;
  if (!Array.isArray(vel)) return false;
  return vel.some((v) => typeof v === 'number' && Number.isFinite(v) && v > 0);
}

async function parseApiError(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    if (body.detail) return body.detail;
  } catch {
    /* ignore */
  }
  return `${fallback} (${res.status})`;
}

/** Loads stored streams from the API (not a live Strava fetch). */
export async function getActivityStreams(workoutId: string): Promise<ActivityStreams | null> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/v1/activities/${workoutId}/streams`, { headers });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load activity streams'));
  return (await res.json()) as ActivityStreams;
}

export async function getActivityLaps(workoutId: string): Promise<ActivityLap[]> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/v1/activities/${workoutId}/laps`, { headers });
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load laps'));
  const data = await res.json();
  return Array.isArray(data) ? (data as ActivityLap[]) : [];
}

export async function getActivityIntervals(workoutId: string): Promise<ActivityIntervals | null> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/v1/activities/${workoutId}/intervals`, { headers });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load intervals'));
  return (await res.json()) as ActivityIntervals;
}

export async function getActivityZones(workoutId: string): Promise<ActivityZones | null> {
  try {
    const headers = await getAuthHeaders();
    const res = await fetch(`${API_URL}/v1/activities/${workoutId}/zones`, { headers });
    if (!res.ok) return null;
    return (await res.json()) as ActivityZones;
  } catch {
    return null;
  }
}

export interface RefetchStravaResult {
  status: string;
  workout_id: string;
  strava_activity_id: number;
  stream_types: string[];
  has_latlng_stream: boolean;
  workout?: Record<string, unknown>;
}

export async function refetchWorkoutFromStrava(
  workoutId: string
): Promise<RefetchStravaResult> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/v1/activities/${workoutId}/refetch-strava`, {
    method: 'POST',
    headers,
  });
  if (!res.ok) {
    let detail = `Repull failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as RefetchStravaResult;
}

export async function hydrateActivityStreams(
  workoutId: string
): Promise<{ status: string; stream_types?: string[] }> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/v1/activities/${workoutId}/hydrate-streams`, {
    method: 'POST',
    headers,
  });
  if (!res.ok) throw new Error(await parseApiError(res, 'Failed to fetch streams from Strava'));
  return (await res.json()) as { status: string; stream_types?: string[] };
}
