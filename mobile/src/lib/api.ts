import { getAuthHeaders } from './apiAuth';
import { supabase } from '$lib/supabase';
import type { Workout } from './types/training';
import { getTimeOfDayPeriod, type TimeOfDayPeriod } from './utils/greeting';

const VITE_API_URL = import.meta.env.VITE_API_URL;
const API_URL = VITE_API_URL && VITE_API_URL !== 'undefined' ? VITE_API_URL : 'http://localhost:8000';
/** Strict calendar day for `/v1/training-plans` query params (avoids 422 from bad callers). */
const ISO_DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
console.log(`[API] Initialized with API_URL: ${API_URL}`);

const getUserTimezoneOffsetMin = () => -new Date().getTimezoneOffset();

let _initCache: { result: unknown; expiresAt: number; period: TimeOfDayPeriod; timezoneOffsetMin: number } | null = null;

export const api = {
  async getDashboardSummary(day?: string) {
    try {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams();
      if (day) qs.set('day', day);
      const url = `${API_URL}/v1/analysis/dashboard-summary${qs.toString() ? `?${qs.toString()}` : ''}`;
      const res = await fetch(url, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('Failed to fetch dashboard summary from backend.', e);
    }
    return null;
  },

  async getRecoveryAnalysis(day?: string) {
    try {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams();
      if (day) qs.set('day', day);
      const url = `${API_URL}/v1/analysis/recovery${qs.toString() ? `?${qs.toString()}` : ''}`;
      const res = await fetch(url, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('Failed to fetch recovery analysis from backend.', e);
    }
    return null;
  },

  async getSleepAnalysis(day?: string) {
    try {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams();
      if (day) qs.set('day', day);
      const url = `${API_URL}/v1/analysis/sleep${qs.toString() ? `?${qs.toString()}` : ''}`;
      const res = await fetch(url, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('Failed to fetch sleep analysis from backend.', e);
    }
    return null;
  },

  async getStrainAnalysis(day?: string) {
    try {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams();
      if (day) qs.set('day', day);
      const url = `${API_URL}/v1/analysis/strain${qs.toString() ? `?${qs.toString()}` : ''}`;
      const res = await fetch(url, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('Failed to fetch strain analysis from backend.', e);
    }
    return null;
  },

  async getTrainingLoadAnalysis(end_day?: string) {
    try {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams();
      if (end_day) qs.set('end_day', end_day);
      const url = `${API_URL}/v1/analysis/training-load${qs.toString() ? `?${qs.toString()}` : ''}`;
      const res = await fetch(url, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('Failed to fetch training load analysis from backend.', e);
    }
    return null;
  },

  async getAthleteState() {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/athlete/state`, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to fetch athlete state from backend.", e);
    }
    return null;
  },

  async getAthleteMetrics() {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/athlete/metrics`, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to fetch athlete metrics from backend.", e);
    }
    return null;
  },

  async getBiometricsPage(params?: { limit?: number; before?: string; all?: boolean }) {
    try {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams();
      if (params?.limit != null) qs.set('limit', String(params.limit));
      if (params?.before) qs.set('before', params.before);
      if (params?.all) qs.set('all', 'true');
      const url = `${API_URL}/v1/biometrics${qs.toString() ? `?${qs.toString()}` : ''}`;

      const res = await fetch(url, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to fetch biometrics from backend.", e);
    }
    return null;
  },

  async getPlan() {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/plan`, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to fetch plan from backend.", e);
    }
    return null;
  },

  async getAthleteProfile() {
    try {
      const headers = await getAuthHeaders();
      const url = `${API_URL}/v1/athlete/profile`;
      console.log(`[API] Fetching profile from: ${url}`);
      const res = await fetch(url, { headers });
      if (res.ok) return await res.json();
      console.warn(`[API] Profile fetch failed with status: ${res.status}`);
    } catch (e) {
      console.warn("Failed to fetch profile from backend.", e);
    }
    return null;
  },

  async getCompletedWorkouts(limit = 20) {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/workouts?limit=${limit}`, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to fetch workouts from backend.", e);
    }
    return null;
  },

  async getWorkouts(startDate: string, endDate: string): Promise<Workout[]> {
    if (!ISO_DATE_ONLY.test(startDate) || !ISO_DATE_ONLY.test(endDate)) {
      console.warn('[API] getWorkouts requires YYYY-MM-DD startDate and endDate.', { startDate, endDate });
      return [];
    }
    try {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams();
      qs.set('start_date', startDate);
      qs.set('end_date', endDate);
      const res = await fetch(`${API_URL}/v1/training-plans?${qs.toString()}`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      return Array.isArray(json) ? (json as Workout[]) : [];
    } catch (e) {
      console.warn("Failed to fetch planned workouts from backend.", e);
      return [];
    }
  },

  async saveWorkout(workout: Workout): Promise<Workout | null> {
    try {
      const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
      const isUuid = (v: string) =>
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v);
      const method = isUuid(workout.id) ? 'PUT' : 'POST';
      const url = isUuid(workout.id)
        ? `${API_URL}/v1/training-plans/${workout.id}`
        : `${API_URL}/v1/training-plans`;

      const res = await fetch(url, {
        method,
        headers,
        body: JSON.stringify(workout)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as Workout;
    } catch (e) {
      console.warn("Failed to save planned workout.", e);
      return null;
    }
  },

  async deleteTrainingPlan(planId: string): Promise<boolean> {
    const isUuid = (v: string) =>
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v);
    if (!isUuid(planId)) {
      console.warn('[API] deleteTrainingPlan expects a UUID plan id.', planId);
      return false;
    }
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/training-plans/${planId}`, {
        method: 'DELETE',
        headers
      });
      if (res.status === 404) return false;
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return true;
    } catch (e) {
      console.warn('Failed to delete planned workout from calendar.', e);
      return false;
    }
  },

  async deleteWorkout(workoutId: string) {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/workouts/${workoutId}`, {
        method: 'DELETE',
        headers
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to delete workout.", e);
    }
    return null;
  },

  async updateWorkout(workoutId: string, payload: object) {
    try {
      const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
      const res = await fetch(`${API_URL}/v1/workouts/${workoutId}`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify(payload)
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to update workout.", e);
    }
    return null;
  },

  async patchAthleteProfile(payload: any): Promise<{ ok: true; data: unknown } | { ok: false; error: string }> {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        if (attempt > 0) await new Promise(r => setTimeout(r, attempt * 2000));
        const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
        const res = await fetch(`${API_URL}/v1/athlete/profile`, {
          method: 'PATCH',
          headers,
          body: JSON.stringify(payload)
        });
        if (res.ok) return { ok: true, data: await res.json() };
        if (res.status === 503 || res.status === 504) {
          if (attempt < 2) continue;
          return {
            ok: false,
            error: 'Server is temporarily unavailable. Please try again in a minute.'
          };
        }
        let detail = `Save failed (${res.status})`;
        try {
          const body = await res.json();
          if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : detail;
        } catch {
          /* ignore */
        }
        return { ok: false, error: detail };
      } catch (e) {
        console.warn("Failed to patch athlete profile.", e);
        if (attempt === 2) {
          return { ok: false, error: 'Network error while saving. Check your connection and try again.' };
        }
      }
    }
    return { ok: false, error: 'Failed to save changes. Please try again.' };
  },

  async deleteAthleteAccount() {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/athlete`, {
        method: 'DELETE',
        headers
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to delete athlete account.", e);
    }
    return null;
  },

  async unlinkIntegration(provider: string) {
    try {
      const headers = await getAuthHeaders();
      const url = `${API_URL}/v1/sync/${provider}`;
      console.log(`[API] Unlink integration request: ${url}`);
      const res = await fetch(url, {
        method: 'DELETE',
        headers
      });
      if (res.ok) {
        const json = await res.json();
        console.log(`[API] Unlink integration OK (${provider})`, json);
        return json;
      }
      const text = await res.text().catch(() => '');
      console.warn(`[API] Unlink integration failed (${provider}) status=${res.status} body=${text}`);
    } catch (e) {
      console.warn(`Failed to unlink ${provider}.`, e);
    }
    return null;
  },

  async connectIntervalsIcu(payload: {
    intervals_athlete_id: string;
    api_key: string;
    days?: number;
  }) {
    try {
      const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
      const res = await fetch(`${API_URL}/v1/sync/intervals-icu/connect`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });
      if (res.ok) return await res.json();
      const text = await res.text().catch(() => '');
      console.warn(`[API] Intervals.icu connect failed status=${res.status} body=${text}`);
    } catch (e) {
      console.warn('Failed to connect Intervals.icu.', e);
    }
    return null;
  },

  async connectGarmin(payload: { username: string; password: string; days?: number }) {
    try {
      const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
      const res = await fetch(`${API_URL}/v1/sync/garmin/connect`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) return body;
      console.warn(`[API] Garmin connect failed status=${res.status}`, body);
      return {
        status: 'error',
        detail: typeof body?.detail === 'string' ? body.detail : `Connection failed (${res.status})`
      };
    } catch (e) {
      console.warn('Failed to connect Garmin.', e);
      return { status: 'error', detail: 'Connection failed' };
    }
  },

  async connectGarminMfa(payload: { state_token: string; mfa_code: string; days?: number }) {
    try {
      const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
      const res = await fetch(`${API_URL}/v1/sync/garmin/connect/mfa`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) return body;
      console.warn(`[API] Garmin MFA failed status=${res.status}`, body);
      return {
        status: 'error',
        detail: typeof body?.detail === 'string' ? body.detail : `MFA verification failed (${res.status})`
      };
    } catch (e) {
      console.warn('Failed to verify Garmin MFA.', e);
      return { status: 'error', detail: 'MFA verification failed' };
    }
  },

  async getSyncStatus() {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/sync/status`, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to fetch sync status.", e);
    }
    return null;
  },

  async get<T = any>(path: string): Promise<T | null> {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}${path}`, { headers });
      if (res.ok) return (await res.json()) as T;
      const text = await res.text().catch(() => '');
      console.warn(`[API] GET ${path} failed status=${res.status} body=${text}`);
    } catch (e) {
      console.warn(`Failed to GET ${path} from backend.`, e);
    }
    return null;
  },

  async post(path: string, payload: any) {
    try {
      const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
      const res = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn(`Failed to POST ${path} to backend.`, e);
    }
    return null;
  },

  async getCoachConversations() {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/coach/conversations`, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to fetch coach conversations.", e);
    }
    return null;
  },

  async initializeCoach() {
    const period = getTimeOfDayPeriod();
    const timezoneOffsetMin = getUserTimezoneOffsetMin();
    if (
      _initCache &&
      _initCache.period === period &&
      _initCache.timezoneOffsetMin === timezoneOffsetMin &&
      Date.now() < _initCache.expiresAt
    ) return _initCache.result;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
      const res = await fetch(`${API_URL}/v1/coach/initialize`, {
        method: 'POST',
        headers,
        signal: controller.signal,
        body: JSON.stringify({ timezone_offset_min: timezoneOffsetMin })
      });
      if (res.ok) {
        const data = await res.json();
        _initCache = { result: data, expiresAt: Date.now() + 10 * 60 * 1000, period, timezoneOffsetMin };
        return data;
      }
    } catch (e) {
      if (e instanceof Error && e.name !== 'AbortError') console.warn("Failed to initialize coach.", e);
    } finally {
      clearTimeout(timer);
    }
    return null;
  },

  async createCoachConversation(title?: string) {
    return await this.post('/v1/coach/conversations', { title: title ?? null });
  },

  async deleteCoachConversation(conversationId: string) {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/coach/conversations/${conversationId}`, {
        method: 'DELETE',
        headers
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to delete coach conversation.", e);
    }
    return null;
  },

  async getCoachMessages(conversationId: string) {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/v1/coach/conversations/${conversationId}/messages`, { headers });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Failed to fetch coach messages.", e);
    }
    return null;
  },

  async uploadCoachImage(file: File, conversationId: string) {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user?.id) throw new Error('Not signed in');

    const ext = (file.name.split('.').pop() || 'jpg').toLowerCase();
    const safeExt = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'heic'].includes(ext) ? ext : 'jpg';
    const filename = `${Date.now()}-${Math.random().toString(16).slice(2)}.${safeExt}`;
    const path = `coach/${user.id}/${conversationId}/${filename}`;

    const bucket = supabase.storage.from('coach-uploads');
    const uploadRes = await bucket.upload(path, file, { contentType: file.type, upsert: false });
    if (uploadRes.error) throw uploadRes.error;

    const { data } = bucket.getPublicUrl(path);
    if (!data?.publicUrl) throw new Error('Failed to get public URL');
    return data.publicUrl;
  },

  async streamCoachMessage(params: {
    message: string;
    recent_tss: number;
    conversation_id?: string | null;
    image_urls?: string[] | null;
    onConversationId?: (conversationId: string) => void;
    onStarted?: () => void;
    onStatus?: (status: string, detail?: Record<string, unknown>) => void;
    onChunk: (text: string) => void;
    onSources?: (sources: unknown[]) => void;
  }): Promise<{ conversation_id: string }> {
    const headers = await getAuthHeaders({ 'Content-Type': 'application/json' });
    const response = await fetch(`${API_URL}/v1/coach/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        message: params.message,
        recent_tss: params.recent_tss,
        conversation_id: params.conversation_id ?? null,
        image_urls: params.image_urls ?? null,
        timezone_offset_min: getUserTimezoneOffsetMin()
      })
    });

    if (!response.ok) {
      const text = await response.text();
      let detail = text?.trim() || `HTTP ${response.status}`;
      try {
        const body = JSON.parse(text) as { detail?: unknown };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error('Streaming not supported');

    const decoder = new TextDecoder();
    let buffer = '';
    let conversationId = params.conversation_id ?? '';
    let streamStarted = false;

    const notifyStarted = () => {
      if (streamStarted) return;
      streamStarted = true;
      params.onStarted?.();
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';

      for (const part of parts) {
        for (const line of part.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6).trim();
          if (!payload || payload === '[DONE]') continue;
          let data: Record<string, unknown>;
          try {
            data = JSON.parse(payload) as Record<string, unknown>;
          } catch {
            continue;
          }
          if (typeof data.conversation_id === 'string') {
            conversationId = data.conversation_id;
            notifyStarted();
            params.onConversationId?.(conversationId);
          }
          if (typeof data.status === 'string' && data.status) {
            notifyStarted();
            params.onStatus?.(data.status, data);
          }
          if (typeof data.text === 'string' && data.text) {
            notifyStarted();
            params.onChunk(data.text);
          }
          if (Array.isArray(data.sources)) {
            params.onSources?.(data.sources);
          }
          if (typeof data.error === 'string') {
            throw new Error(data.error);
          }
        }
      }
    }

    if (!conversationId) {
      throw new Error('Invalid coach stream: missing conversation_id');
    }
    return { conversation_id: conversationId };
  },

  /** @deprecated Prefer streamCoachMessage for lower perceived latency */
  async sendCoachMessage(params: {
    message: string;
    recent_tss: number;
    conversation_id?: string | null;
    image_urls?: string[] | null;
  }): Promise<{
    status: string;
    conversation_id: string;
    reply: string;
    sources?: unknown[];
  }> {
    let reply = '';
    let sources: unknown[] | undefined;
    const result = await this.streamCoachMessage({
      ...params,
      onChunk: (chunk) => {
        reply += chunk;
      },
      onSources: (s) => {
        sources = s;
      }
    });
    return {
      status: 'success',
      conversation_id: result.conversation_id,
      reply,
      sources
    };
  }
};
