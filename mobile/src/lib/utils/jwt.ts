/**
 * Decode a JWT's payload (no verification; the server verifies). JWTs are base64url
 * with padding stripped and UTF-8 inside, which plain `atob` doesn't handle: it threw
 * on `-`/`_`, which some payloads contain (e.g. accented names in user_metadata), and
 * the callers treated that as an invalid session and signed the user out.
 */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const part = typeof token === 'string' ? token.split('.')[1] : undefined;
  if (!part) return null;
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (part.length % 4)) % 4);
    const binary = atob(b64);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    const json = new TextDecoder().decode(bytes);
    const parsed = JSON.parse(json);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
