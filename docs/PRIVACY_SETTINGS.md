# Privacy Settings

## Overview

Privacy settings are managed at **Profile -> Privacy** (`mobile/src/routes/profile/privacy/+page.svelte`) and saved to `athletes.privacy_settings` (JSONB) through `PATCH /v1/athlete/profile`.

## Settings

```json
{ "share_data": false, "marketing": false }
```

Both default to `false` (opt-in). The page's `defaultSettings` supplies the defaults when the profile has no `privacy_settings`.

### Anonymous AI training (`share_data`)

Stored only. No backend code reads it today. It is meant to gate a future anonymized training-data export; such a pipeline should filter on `privacy_settings->>'share_data' = 'true'`.

### Product updates (`marketing`)

When the saved payload contains `marketing`, the backend syncs the user's email to the configured Resend audience: subscribed when `true`, marked `unsubscribed` when `false` (the contact is kept).

## Save Behavior

Each toggle saves immediately; there is no Save button. The page flips the toggle, disables the toggles while saving, sends the full `privacy_settings` object through `athleteStore.updateProfile()`, and reverts the toggle if the save fails. On success the store reloads the profile.

The backend validates `privacy_settings` as a small flat object: at most 30 keys, keys up to 40 characters, values that are booleans, numbers, short strings (200 characters max) or null.

No schema change is needed to add a flag. Add it to `defaultSettings` and the row list on the page, and add any side effect in `update_athlete_profile` (`backend/app/routers/athlete.py`).

The AI coach cannot change privacy or marketing settings (`backend/app/services/athlete_profile.py` keeps them out of what the coach may edit).

## Resend Integration

Resend is the only external side effect.

1. The user toggles any privacy setting. The page always sends the full object, so `marketing` is in every privacy save.
2. `PATCH /v1/athlete/profile` saves the profile.
3. If the request has the user's email (`get_current_user_email`, which looks up the Supabase auth user for the bearer token) and `marketing` is in the payload, `sync_marketing_contact(email, subscribed)` in `backend/app/services/resend_service.py` runs.
4. It calls `POST https://api.resend.com/audiences/{RESEND_AUDIENCE_ID}/contacts` with `{email, unsubscribed: !subscribed}` and `Authorization: Bearer {RESEND_API_KEY}`, with a 5 s timeout. Resend upserts the contact, so it is safe to call on every save.
5. Errors are printed with a `[resend]` prefix and never fail the profile save.

Backend environment (`backend/app/config.py`):

```env
RESEND_API_KEY=
RESEND_AUDIENCE_ID=
```

If either is missing, the sync is skipped.

## Account Deletion

The privacy screen also has a Delete account button. After a confirmation dialog the frontend calls:

```http
DELETE /v1/athlete
```

On success it signs out and goes to `/auth/signin`. The backend owns the deletion flow and is the source of truth for what data is removed.
