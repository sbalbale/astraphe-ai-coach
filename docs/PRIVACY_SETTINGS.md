# Privacy Settings

## Overview

ASTRAPE gives users control over two privacy settings accessible from **Profile → Privacy**.

---

## Settings

### Anonymous AI Training

> "Allow ASTRAPE to use your anonymized performance data to improve our global coaching models."

- **Default:** Off (opt-in)
- **Stored as:** `privacy_settings.share_data` (`boolean`) on the athlete's profile

When this is enabled, the user's anonymized workout and biometric data may be used to improve ASTRAPE's global coaching models. Currently this flag is stored but not actively consumed by any pipeline — it will gate future training data exports once that infrastructure is built.

### Product Updates

> "Receive occasional emails about new features and platform updates."

- **Default:** Off (opt-in)
- **Stored as:** `privacy_settings.marketing` (`boolean`) on the athlete's profile

When a user enables this, they are automatically added to the **Astrape Marketing** segment in Resend. When they disable it, they are marked as `unsubscribed` in that segment. The sync happens immediately on each toggle.

---

## How Settings Are Saved

Both settings are saved to `athletes.privacy_settings` (a JSONB column) via `PATCH /v1/athlete/profile`. The toggle saves immediately — there is no explicit "Save" button.

---

## Resend Integration

The `marketing` flag is the only setting that triggers an external side-effect:

1. User toggles the checkbox in the Privacy screen
2. The app calls `PATCH /v1/athlete/profile` with `{ privacy_settings: { marketing: true/false } }`
3. The backend saves the value to Supabase, then calls the Resend API to upsert the contact in the Astrape Marketing audience
4. Resend uses **upsert semantics** — the same API call works whether the user is new or already in the audience

If the Resend call fails (network error, invalid key, etc.), the profile save still succeeds. The failure is logged server-side but not returned to the user.

---

## Required Environment Variables

```
RESEND_API_KEY=re_your_api_key_here
RESEND_AUDIENCE_ID=your_audience_uuid_here
```

Get these from [resend.com](https://resend.com):
- **API Key:** Settings → API Keys
- **Audience ID:** Contacts → Segments → Astrape Marketing → copy the UUID from the URL

If either variable is missing, Resend sync is silently skipped (the profile still saves normally).
