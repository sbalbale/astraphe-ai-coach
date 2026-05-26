# Privacy Settings

## Overview

Privacy settings are managed at **Profile -> Privacy** in the mobile/web app and saved to `athletes.privacy_settings` through `PATCH /v1/athlete/profile`.

## Settings

### Anonymous AI Training

Stored as:

```json
{ "share_data": false }
```

Default is opt-out. The flag is saved today and is intended to gate future anonymized training-data export/model-improvement pipelines.

### Product Updates

Stored as:

```json
{ "marketing": false }
```

Default is opt-out. When enabled, the backend attempts to upsert the user into the configured Resend audience. When disabled, the backend marks the contact unsubscribed in that audience.

## Save Behavior

The frontend saves immediately on toggle through `athleteStore.updateProfile()` and `PATCH /v1/athlete/profile`; there is no separate Save button. The store updates optimistically with the full `privacy_settings` object.

If a profile save fails, current UI behavior is limited; do not assume a full rollback/error-display flow exists for every toggle failure.

## Resend Integration

Resend sync is the only current external side effect.

Flow:

1. User toggles **Product Updates**.
2. Frontend calls `PATCH /v1/athlete/profile` with the updated `privacy_settings`.
3. Backend saves Supabase profile data.
4. Backend calls Resend if `RESEND_API_KEY` and `RESEND_AUDIENCE_ID` are configured.
5. Resend errors are logged, but profile saving still succeeds.

Required backend environment:

```env
RESEND_API_KEY=
RESEND_AUDIENCE_ID=
```

If either value is missing, Resend sync is skipped.

## Account Deletion

The privacy screen also exposes account deletion. The frontend calls:

```http
DELETE /v1/athlete
```

The backend owns the deletion flow and should remain the source of truth for what data is removed.
