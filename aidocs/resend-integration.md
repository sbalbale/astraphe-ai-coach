# Resend Marketing Integration — AI Context

## What this system does

When a user enables the "Product Updates" toggle on the Privacy settings page, they are automatically added to the **Astrape Marketing** Resend audience. When they disable it, they are marked as `unsubscribed` in that audience.

## Architecture

```
User toggles marketing checkbox
  → toggleSetting('marketing') in +page.svelte (line 37)
  → athleteStore.updateProfile({ privacy_settings: { ...settings } })
  → PATCH /v1/athlete/profile (backend/app/routers/athlete.py)
  → saves to Supabase athletes.privacy_settings (JSONB)
  → if privacy_settings.marketing is present in payload:
      → calls sync_marketing_contact(email, subscribed)
      → POST https://api.resend.com/audiences/{RESEND_AUDIENCE_ID}/contacts
         body: { email, unsubscribed: !subscribed }
```

## Key files

| File | Role |
|------|------|
| `mobile/src/routes/profile/privacy/+page.svelte` | UI: two toggles, saves on each change |
| `backend/app/routers/athlete.py` | `update_athlete_profile` — calls Resend after save |
| `backend/app/services/resend_service.py` | `sync_marketing_contact(email, subscribed)` — async httpx call |
| `backend/app/dependencies.py` | `get_current_user_email` — extracts email from Supabase JWT |
| `backend/app/config.py` | `RESEND_API_KEY`, `RESEND_AUDIENCE_ID` settings |

## Data model

`athletes.privacy_settings` is a JSONB column. Shape:
```json
{
  "share_data": false,
  "marketing": false
}
```

Both default to `false` (opt-in). The `defaultSettings` object in the Svelte page is the source of truth for new users who have no existing `privacy_settings`.

## Resend API details

- **Endpoint:** `POST /audiences/{audience_id}/contacts`
- **Auth:** `Authorization: Bearer {RESEND_API_KEY}`
- **Upsert semantics:** if the email already exists in the audience, Resend updates the `unsubscribed` field rather than erroring
- **Toggle ON:** `unsubscribed: false`
- **Toggle OFF:** `unsubscribed: true` (keeps the contact record for compliance)
- **Timeout:** 5 seconds
- **Error handling:** failures are logged with `[resend]` prefix but never propagate to the user

## Environment variables

```
RESEND_API_KEY=re_...
RESEND_AUDIENCE_ID=<UUID from Resend dashboard>
```

Both are optional at runtime — if either is missing, `sync_marketing_contact` returns immediately without making an HTTP call.

## share_data flag

The `share_data` flag controls whether the user's data can be used for AI model training. It is **stored but not yet consumed** by any backend pipeline. When a training data export pipeline is built, it should filter to `privacy_settings->>'share_data' = 'true'` in Supabase. The default changed from `true` (opt-out) to `false` (opt-in) in this PR.

## Adding new privacy settings

To add a new flag:
1. Add it to `defaultSettings` in `+page.svelte` with an appropriate default
2. Add a label + checkbox in the UI following the existing pattern
3. If it has a side-effect (like `marketing` → Resend), add a handler in `update_athlete_profile`

No schema change needed — `privacy_settings` is an open JSONB column.
