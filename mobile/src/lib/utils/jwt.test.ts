import { describe, expect, it } from 'vitest';
import { decodeJwtPayload } from './jwt';

function b64url(obj: unknown): string {
  const bytes = new TextEncoder().encode(JSON.stringify(obj));
  let bin = '';
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

describe('decodeJwtPayload', () => {
  it('decodes base64url payloads with non-ASCII text', () => {
    // Accented names produce `-`/`_` in base64url, which plain atob rejects.
    for (const name of ['Zoë Ñúñez', 'Søren Ærø', 'Łukasz Żółć', '日本語', 'José María']) {
      const claims = { sub: 'u1', exp: 2000000000, user_metadata: { full_name: name } };
      const token = `${b64url({ alg: 'HS256' })}.${b64url(claims)}.sig`;
      expect(decodeJwtPayload(token)).toEqual(claims);
    }
  });

  it('returns null for garbage', () => {
    expect(decodeJwtPayload('')).toBeNull();
    expect(decodeJwtPayload('a.b')).toBeNull();
    expect(decodeJwtPayload('not-a-jwt')).toBeNull();
  });
});
