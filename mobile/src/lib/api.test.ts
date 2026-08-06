import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getAuthHeadersMock = vi.fn(async (extra: Record<string, string> = {}) => ({ ...extra }));
vi.mock('./apiAuth', () => ({
  getAuthHeaders: (...args: unknown[]) => getAuthHeadersMock(...(args as [Record<string, string>?]))
}));

const getUserMock = vi.fn();
const uploadMock = vi.fn();
const getPublicUrlMock = vi.fn();
vi.mock('$lib/supabase', () => ({
  supabase: {
    auth: { getUser: (...args: unknown[]) => getUserMock(...args) },
    storage: {
      from: () => ({
        upload: (...args: unknown[]) => uploadMock(...args),
        getPublicUrl: (...args: unknown[]) => getPublicUrlMock(...args)
      })
    }
  }
}));

import { api } from './api';

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body)
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  getAuthHeadersMock.mockClear();
  getUserMock.mockReset();
  uploadMock.mockReset();
  getPublicUrlMock.mockReset();
  vi.restoreAllMocks();
});

describe('simple GET-style analysis endpoints', () => {
  it('getDashboardSummary returns parsed JSON on success, with day query param', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ a: 1 }));
    const result = await api.getDashboardSummary('2026-05-20');
    expect(result).toEqual({ a: 1 });
    expect(fetchMock.mock.calls[0][0]).toContain('day=2026-05-20');
  });

  it('getDashboardSummary omits query string without a day', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ a: 1 }));
    await api.getDashboardSummary();
    expect(fetchMock.mock.calls[0][0]).not.toContain('?');
  });

  it('getDashboardSummary returns null on non-ok response', async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, false, 500));
    expect(await api.getDashboardSummary()).toBeNull();
  });

  it('getDashboardSummary returns null and swallows fetch throwing', async () => {
    fetchMock.mockRejectedValue(new Error('network down'));
    expect(await api.getDashboardSummary()).toBeNull();
  });

  it('getRecoveryAnalysis success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.getRecoveryAnalysis('2026-05-20')).toEqual({ ok: true });
  });

  it('getSleepAnalysis success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.getSleepAnalysis()).toEqual({ ok: true });
  });

  it('getStrainAnalysis success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.getStrainAnalysis('2026-05-20')).toEqual({ ok: true });
  });

  it('getTrainingLoadAnalysis success with end_day', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.getTrainingLoadAnalysis('2026-05-20')).toEqual({ ok: true });
    expect(fetchMock.mock.calls[0][0]).toContain('end_day=2026-05-20');
  });

  it('getAthleteState success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'a1' }));
    expect(await api.getAthleteState()).toEqual({ id: 'a1' });
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await api.getAthleteState()).toBeNull();
  });

  it('getAthleteMetrics success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ctl: 50 }));
    expect(await api.getAthleteMetrics()).toEqual({ ctl: 50 });
    fetchMock.mockResolvedValue(jsonResponse(null, false));
    expect(await api.getAthleteMetrics()).toBeNull();
  });

  it('getBiometricsPage builds query params and returns data', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ rows: [] }));
    await api.getBiometricsPage({ limit: 10, before: '2026-05-20', all: true });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('limit=10');
    expect(url).toContain('before=2026-05-20');
    expect(url).toContain('all=true');
  });

  it('getBiometricsPage with no params omits query string', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ rows: [] }));
    await api.getBiometricsPage();
    expect(fetchMock.mock.calls[0][0]).not.toContain('?');
  });

  it('getPlan success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ plan: [] }));
    expect(await api.getPlan()).toEqual({ plan: [] });
  });

  it('getAthleteProfile success/non-ok/catch', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'a1' }));
    expect(await api.getAthleteProfile()).toEqual({ id: 'a1' });
    fetchMock.mockResolvedValue(jsonResponse(null, false, 404));
    expect(await api.getAthleteProfile()).toBeNull();
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await api.getAthleteProfile()).toBeNull();
  });

  it('getCompletedWorkouts default and custom limit', async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.getCompletedWorkouts();
    expect(fetchMock.mock.calls[0][0]).toContain('limit=20');
    await api.getCompletedWorkouts(5);
    expect(fetchMock.mock.calls[1][0]).toContain('limit=5');
  });
});

describe('getWorkouts', () => {
  it('rejects malformed dates without calling fetch', async () => {
    const result = await api.getWorkouts('not-a-date', '2026-05-20');
    expect(result).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns the array on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ id: '1' }]));
    const result = await api.getWorkouts('2026-05-01', '2026-05-20');
    expect(result).toEqual([{ id: '1' }]);
  });

  it('returns [] when the response body is not an array', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ not: 'an array' }));
    expect(await api.getWorkouts('2026-05-01', '2026-05-20')).toEqual([]);
  });

  it('returns [] when the response is not ok', async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, false, 500));
    expect(await api.getWorkouts('2026-05-01', '2026-05-20')).toEqual([]);
  });
});

describe('saveWorkout', () => {
  const uuidWorkout = { id: '11111111-1111-4111-8111-111111111111' } as any;
  const newWorkout = { id: 'temp-id' } as any;

  it('PUTs when the id is a UUID', async () => {
    fetchMock.mockResolvedValue(jsonResponse(uuidWorkout));
    await api.saveWorkout(uuidWorkout);
    expect(fetchMock.mock.calls[0][1].method).toBe('PUT');
    expect(fetchMock.mock.calls[0][0]).toContain(uuidWorkout.id);
  });

  it('POSTs when the id is not a UUID', async () => {
    fetchMock.mockResolvedValue(jsonResponse(newWorkout));
    await api.saveWorkout(newWorkout);
    expect(fetchMock.mock.calls[0][1].method).toBe('POST');
  });

  it('returns null and swallows a non-ok response', async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, false, 500));
    expect(await api.saveWorkout(newWorkout)).toBeNull();
  });
});

describe('deleteTrainingPlan', () => {
  it('non-UUID id returns false without calling fetch', async () => {
    expect(await api.deleteTrainingPlan('not-a-uuid')).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('404 returns false', async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, false, 404));
    expect(await api.deleteTrainingPlan('11111111-1111-4111-8111-111111111111')).toBe(false);
  });

  it('ok returns true', async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, true));
    expect(await api.deleteTrainingPlan('11111111-1111-4111-8111-111111111111')).toBe(true);
  });

  it('other error status returns false via catch', async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, false, 500));
    expect(await api.deleteTrainingPlan('11111111-1111-4111-8111-111111111111')).toBe(false);
  });
});

describe('deleteWorkout / updateWorkout', () => {
  it('deleteWorkout success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.deleteWorkout('w1')).toEqual({ ok: true });
    fetchMock.mockResolvedValue(jsonResponse(null, false));
    expect(await api.deleteWorkout('w1')).toBeNull();
  });

  it('updateWorkout success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.updateWorkout('w1', { title: 'x' })).toEqual({ ok: true });
    fetchMock.mockResolvedValue(jsonResponse(null, false));
    expect(await api.updateWorkout('w1', { title: 'x' })).toBeNull();
  });
});

describe('patchAthleteProfile', () => {
  it('succeeds on first attempt', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'a1' }));
    const result = await api.patchAthleteProfile({ display_name: 'Sean' });
    expect(result).toEqual({ ok: true, data: { id: 'a1' } });
  });

  it('retries on 503 then succeeds', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(null, false, 503))
      .mockResolvedValueOnce(jsonResponse({ id: 'a1' }));
    const result = await api.patchAthleteProfile({ display_name: 'Sean' });
    expect(result).toEqual({ ok: true, data: { id: 'a1' } });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  }, 10000);

  it('gives up after repeated 503s', async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, false, 503));
    const result = await api.patchAthleteProfile({});
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain('temporarily unavailable');
  }, 15000); // real retry backoff (2s + 4s) -- not worth faking timers for one test

  it('returns detail from error body for non-retryable failures', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Invalid FTP value' }, false, 422));
    const result = await api.patchAthleteProfile({});
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe('Invalid FTP value');
  });

  it('falls back to a generic message when error body has no detail', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => {
        throw new Error('not json');
      }
    });
    const result = await api.patchAthleteProfile({});
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe('Save failed (400)');
  });

  it('returns a network-error message after repeated fetch failures', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));
    const result = await api.patchAthleteProfile({});
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain('Network error');
  }, 15000);
});

describe('deleteAthleteAccount', () => {
  it('success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.deleteAthleteAccount()).toEqual({ ok: true });
    fetchMock.mockResolvedValue(jsonResponse(null, false));
    expect(await api.deleteAthleteAccount()).toBeNull();
  });
});

describe('unlinkIntegration', () => {
  it('success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'success' }));
    expect(await api.unlinkIntegration('strava')).toEqual({ status: 'success' });
  });

  it('non-ok logs a warning with body text and returns null', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, text: async () => 'server error' });
    expect(await api.unlinkIntegration('strava')).toBeNull();
  });

  it('catches fetch throwing', async () => {
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await api.unlinkIntegration('strava')).toBeNull();
  });
});

describe('connectIntervalsIcu', () => {
  it('success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ connected: true }));
    const result = await api.connectIntervalsIcu({ intervals_athlete_id: '1', api_key: 'k' });
    expect(result).toEqual({ connected: true });
  });

  it('non-ok returns null', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 400, text: async () => 'bad key' });
    const result = await api.connectIntervalsIcu({ intervals_athlete_id: '1', api_key: 'k' });
    expect(result).toBeNull();
  });
});

describe('getSyncStatus', () => {
  it('success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ integrations: {} }));
    expect(await api.getSyncStatus()).toEqual({ integrations: {} });
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await api.getSyncStatus()).toBeNull();
  });
});

describe('get<T> / post', () => {
  it('get returns JSON on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ a: 1 }));
    expect(await api.get('/v1/whatever')).toEqual({ a: 1 });
  });

  it('get returns null and logs on non-ok', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, text: async () => 'not found' });
    expect(await api.get('/v1/whatever')).toBeNull();
  });

  it('get returns null and swallows a thrown error', async () => {
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await api.get('/v1/whatever')).toBeNull();
  });

  it('post returns JSON on success and null otherwise', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.post('/v1/x', { a: 1 })).toEqual({ ok: true });
    fetchMock.mockResolvedValue(jsonResponse(null, false));
    expect(await api.post('/v1/x', { a: 1 })).toBeNull();
  });
});

describe('coach conversations', () => {
  it('getCoachConversations success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ id: 'c1' }]));
    expect(await api.getCoachConversations()).toEqual([{ id: 'c1' }]);
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await api.getCoachConversations()).toBeNull();
  });

  it('deleteCoachConversation success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await api.deleteCoachConversation('c1')).toEqual({ ok: true });
    fetchMock.mockResolvedValue(jsonResponse(null, false));
    expect(await api.deleteCoachConversation('c1')).toBeNull();
  });

  it('getCoachMessages success/failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ id: 'm1' }]));
    expect(await api.getCoachMessages('c1')).toEqual([{ id: 'm1' }]);
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await api.getCoachMessages('c1')).toBeNull();
  });

  it('createCoachConversation delegates to post', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'c1' }));
    const result = await api.createCoachConversation('My chat');
    expect(result).toEqual({ id: 'c1' });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ title: 'My chat' });
  });
});

describe('initializeCoach', () => {
  // `_initCache` is module-level state shared across calls, so each test needs a fresh
  // module instance (vi.resetModules + dynamic re-import) to avoid the previous test's
  // cached result leaking into this one.
  async function freshApi() {
    vi.resetModules();
    return (await import('./api')).api;
  }

  it('fetches and caches on success', async () => {
    const freshedApi = await freshApi();
    fetchMock.mockResolvedValue(jsonResponse({ greeting: 'hi' }));
    const first = await freshedApi.initializeCoach();
    expect(first).toEqual({ greeting: 'hi' });
    const second = await freshedApi.initializeCoach();
    expect(second).toEqual({ greeting: 'hi' });
    expect(fetchMock).toHaveBeenCalledTimes(1); // second call served from cache
  });

  it('returns null and swallows a non-abort error', async () => {
    const freshedApi = await freshApi();
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await freshedApi.initializeCoach()).toBeNull();
  });
});

describe('uploadCoachImage', () => {
  it('throws when not signed in', async () => {
    getUserMock.mockResolvedValue({ data: { user: null } });
    const file = new File(['x'], 'photo.jpg', { type: 'image/jpeg' });
    await expect(api.uploadCoachImage(file, 'conv-1')).rejects.toThrow('Not signed in');
  });

  it('throws when upload fails', async () => {
    getUserMock.mockResolvedValue({ data: { user: { id: 'u1' } } });
    uploadMock.mockResolvedValue({ error: new Error('upload failed') });
    const file = new File(['x'], 'photo.jpg', { type: 'image/jpeg' });
    await expect(api.uploadCoachImage(file, 'conv-1')).rejects.toThrow('upload failed');
  });

  it('throws when no public URL is returned', async () => {
    getUserMock.mockResolvedValue({ data: { user: { id: 'u1' } } });
    uploadMock.mockResolvedValue({ error: null });
    getPublicUrlMock.mockReturnValue({ data: { publicUrl: null } });
    const file = new File(['x'], 'photo.jpg', { type: 'image/jpeg' });
    await expect(api.uploadCoachImage(file, 'conv-1')).rejects.toThrow('Failed to get public URL');
  });

  it('returns the public URL on success, defaulting unknown extensions to jpg', async () => {
    getUserMock.mockResolvedValue({ data: { user: { id: 'u1' } } });
    uploadMock.mockResolvedValue({ error: null });
    getPublicUrlMock.mockReturnValue({ data: { publicUrl: 'https://cdn.example.com/x.jpg' } });
    const file = new File(['x'], 'photo.unknownext', { type: 'image/jpeg' });
    const result = await api.uploadCoachImage(file, 'conv-1');
    expect(result).toBe('https://cdn.example.com/x.jpg');
  });
});

function makeSseResponse(chunks: string[], ok = true) {
  let i = 0;
  const encoder = new TextEncoder();
  return {
    ok,
    status: ok ? 200 : 500,
    text: async () => chunks.join(''),
    body: {
      getReader: () => ({
        read: async () => {
          if (i < chunks.length) {
            return { done: false, value: encoder.encode(chunks[i++]) };
          }
          return { done: true, value: undefined };
        }
      })
    }
  };
}

describe('streamCoachMessage', () => {
  it('throws with detail from an error JSON body on non-ok response', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, text: async () => JSON.stringify({ detail: 'quota exceeded' }) });
    await expect(
      api.streamCoachMessage({ message: 'hi', recent_tss: 0, onChunk: vi.fn() })
    ).rejects.toThrow('quota exceeded');
  });

  it('throws with raw text when the error body is not JSON', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, text: async () => 'plain error text' });
    await expect(
      api.streamCoachMessage({ message: 'hi', recent_tss: 0, onChunk: vi.fn() })
    ).rejects.toThrow('plain error text');
  });

  it('throws when the response has no readable body', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, body: null });
    await expect(
      api.streamCoachMessage({ message: 'hi', recent_tss: 0, onChunk: vi.fn() })
    ).rejects.toThrow('Streaming not supported');
  });

  it('parses SSE chunks and invokes callbacks, resolving with conversation_id', async () => {
    const onChunk = vi.fn();
    const onStatus = vi.fn();
    const onConversationId = vi.fn();
    const onStarted = vi.fn();
    const onSources = vi.fn();
    const events = [
      `data: ${JSON.stringify({ conversation_id: 'c1' })}\n\n`,
      `data: ${JSON.stringify({ status: 'thinking' })}\n\n`,
      `data: ${JSON.stringify({ text: 'Hello ' })}\n\n`,
      `data: ${JSON.stringify({ text: 'world' })}\n\n`,
      `data: ${JSON.stringify({ sources: [{ url: 'https://x.com' }] })}\n\n`,
      `data: [DONE]\n\n`
    ];
    fetchMock.mockResolvedValue(makeSseResponse(events));
    const result = await api.streamCoachMessage({
      message: 'hi',
      recent_tss: 10,
      onChunk,
      onStatus,
      onConversationId,
      onStarted,
      onSources
    });
    expect(result).toEqual({ conversation_id: 'c1' });
    expect(onChunk).toHaveBeenCalledWith('Hello ');
    expect(onChunk).toHaveBeenCalledWith('world');
    expect(onStatus).toHaveBeenCalledWith('thinking', expect.any(Object));
    expect(onConversationId).toHaveBeenCalledWith('c1');
    expect(onStarted).toHaveBeenCalled();
    expect(onSources).toHaveBeenCalledWith([{ url: 'https://x.com' }]);
  });

  it('throws when an error event arrives mid-stream', async () => {
    const events = [`data: ${JSON.stringify({ conversation_id: 'c1', error: 'model overloaded' })}\n\n`];
    fetchMock.mockResolvedValue(makeSseResponse(events));
    await expect(
      api.streamCoachMessage({ message: 'hi', recent_tss: 0, onChunk: vi.fn() })
    ).rejects.toThrow('model overloaded');
  });

  it('throws when the stream ends without ever receiving a conversation_id', async () => {
    const events = [`data: ${JSON.stringify({ text: 'no id here' })}\n\n`];
    fetchMock.mockResolvedValue(makeSseResponse(events));
    await expect(
      api.streamCoachMessage({ message: 'hi', recent_tss: 0, onChunk: vi.fn() })
    ).rejects.toThrow('missing conversation_id');
  });

  it('skips malformed JSON lines and non-data lines without throwing', async () => {
    const events = [
      'not-a-data-line\n\n',
      'data: not json at all\n\n',
      `data: ${JSON.stringify({ conversation_id: 'c1' })}\n\n`
    ];
    fetchMock.mockResolvedValue(makeSseResponse(events));
    const result = await api.streamCoachMessage({ message: 'hi', recent_tss: 0, onChunk: vi.fn() });
    expect(result).toEqual({ conversation_id: 'c1' });
  });
});

describe('sendCoachMessage', () => {
  it('accumulates streamed chunks into a single reply', async () => {
    const events = [
      `data: ${JSON.stringify({ conversation_id: 'c1' })}\n\n`,
      `data: ${JSON.stringify({ text: 'Hello ' })}\n\n`,
      `data: ${JSON.stringify({ text: 'there' })}\n\n`,
      `data: ${JSON.stringify({ sources: [{ url: 'https://x.com' }] })}\n\n`
    ];
    fetchMock.mockResolvedValue(makeSseResponse(events));
    const result = await api.sendCoachMessage({ message: 'hi', recent_tss: 0 });
    expect(result).toEqual({
      status: 'success',
      conversation_id: 'c1',
      reply: 'Hello there',
      sources: [{ url: 'https://x.com' }]
    });
  });
});
