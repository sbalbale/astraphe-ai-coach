## What & why

<!-- Describe what changed and why. Link related issues. -->

## Testing

<!-- How did you verify this? Test output, manual steps, screenshots for UI changes. -->

## Checklist

- [ ] Tests pass locally (backend: `python -m pytest` from the repo root; mobile: `pnpm test` and `pnpm check` in `mobile/`)
- [ ] Schema changes are a new file in `supabase/migrations/` with RLS on user tables
- [ ] Docs updated if behavior changed
- [ ] No secrets, API keys, or real user data included in this diff
