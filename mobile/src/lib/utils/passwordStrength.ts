/**
 * Client-side minimum for new passwords (sign-up and reset). Supabase Auth enforces its
 * own minimum server-side; keep this at least as strict.
 */
export const MIN_PASSWORD_LENGTH = 8;

export type PasswordStrength = {
  /** 0 = empty or shorter than the minimum, 1–4 = weak → very strong. */
  score: 0 | 1 | 2 | 3 | 4;
  label: '' | 'Too short' | 'Weak' | 'Fair' | 'Strong' | 'Very strong';
  tone: 'none' | 'red' | 'amber' | 'green';
};

/** How many of lower / upper / digit / symbol the password uses. */
function characterClasses(pw: string): number {
  return [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(pw)).length;
}

/**
 * A rough, local strength estimate for the meter under password fields. It only
 * guides the user; the server's rules (minimum length) are what's enforced.
 */
export function passwordStrength(pw: string, minLength: number): PasswordStrength {
  if (!pw) return { score: 0, label: '', tone: 'none' };
  if (pw.length < minLength) return { score: 0, label: 'Too short', tone: 'red' };

  const classes = characterClasses(pw);
  let score = 1;
  if (pw.length >= 12) score++;
  if (classes >= 3) score++;
  if (pw.length >= 16 || (pw.length >= 12 && classes === 4)) score++;
  // A long run of one character class (e.g. "aaaaaaaaaaaa") isn't strong.
  if (classes === 1 && score > 2) score = 2;

  const s = Math.min(4, score) as 1 | 2 | 3 | 4;
  const labels = { 1: 'Weak', 2: 'Fair', 3: 'Strong', 4: 'Very strong' } as const;
  const tones = { 1: 'red', 2: 'amber', 3: 'green', 4: 'green' } as const;
  return { score: s, label: labels[s], tone: tones[s] };
}
