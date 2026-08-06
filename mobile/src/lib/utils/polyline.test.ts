import { describe, expect, it } from 'vitest';
import { decodePolyline, stravaPolylineFromPayload } from './polyline';

describe('decodePolyline', () => {
  it('decodes a known Google-encoded polyline', () => {
    // Google's canonical example: _p~iF~ps|U_ulLnnqC_mqNvxq`@ -> 3 points
    const coords = decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@');
    expect(coords).toEqual([
      [38.5, -120.2],
      [40.7, -120.95],
      [43.252, -126.453]
    ]);
  });

  it('empty string yields empty array', () => {
    expect(decodePolyline('')).toEqual([]);
  });
});

describe('stravaPolylineFromPayload', () => {
  it('returns null for falsy input', () => {
    expect(stravaPolylineFromPayload(null)).toBeNull();
    expect(stravaPolylineFromPayload(undefined)).toBeNull();
    expect(stravaPolylineFromPayload('')).toBeNull();
  });

  it('parses a JSON string payload with summary_polyline', () => {
    const raw = JSON.stringify({ map: { summary_polyline: 'abc123' } });
    expect(stravaPolylineFromPayload(raw)).toBe('abc123');
  });

  it('falls back to polyline field when summary_polyline missing', () => {
    const raw = { map: { polyline: 'xyz789' } };
    expect(stravaPolylineFromPayload(raw)).toBe('xyz789');
  });

  it('invalid JSON string returns null', () => {
    expect(stravaPolylineFromPayload('not json')).toBeNull();
  });

  it('missing map returns null', () => {
    expect(stravaPolylineFromPayload({})).toBeNull();
  });

  it('empty polyline string returns null', () => {
    expect(stravaPolylineFromPayload({ map: { summary_polyline: '' } })).toBeNull();
  });

  it('non-string, non-object raw returns null', () => {
    expect(stravaPolylineFromPayload(42)).toBeNull();
  });
});
