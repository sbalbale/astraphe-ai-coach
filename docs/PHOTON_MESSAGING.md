# Photon (iMessage) coach channel

Text the Astraphe coach from your phone, and get a text after each workout. Texts share the
app's coach chat: the same `coach_conversations` / `coach_messages` rows, so a thread started on
the phone shows up in the app and vice versa. Single-user: one allow-listed number.

## How it fits together

```
iPhone <-> Photon (iMessage line) <-gRPC-> photon-bridge (Node, 1 replica)
                                              |  POST /v1/messaging/photon/inbound
                                              v
                                       backend (FastAPI)  -- get_coach_response() --> reply
                                              |  POST {bridge}/send
                                              v
                                        photon-bridge -> iMessage
```

Photon has no webhooks or HTTP send API (only the TypeScript `spectrum-ts` gRPC SDK), so the
bridge holds the stream. Run **exactly one** bridge replica per Photon project.

- Inbound: `routers/messaging.py` -> `services/messaging.handle_inbound_text`. Checks the
  `X-Photon-Bridge-Token` header and the allow-listed sender, then reuses
  `routers/coach._run_coach_response_and_notify` (on `GEMINI_ANALYSIS_MODEL`) with a `reply_sink`
  that texts instead of pushing, in the athlete's latest conversation. Inbound ids are deduped in
  `messaging_events`; more than `PHOTON_MAX_INBOUND_PER_MINUTE` (default 10, per process) gets a
  "slow down" text instead of a reply.
- `/new` (or `/new chat`) by text starts a fresh conversation and opens it with the app's own chat-open message (`ai_coach.build_initialization_message`: proactive anomaly warning, else a context-aware greeting), stored as the first coach message so the app shows it too.
- Post-workout: the text is the coach's post-workout debrief (`services/coach_notifications.post_workout_debrief`),
  spawned from `processing.process_and_save_workout` (unless `skip_tss_recalc`). Garmin triggers it
  from `garmin._save_one_activity` after the FIT download has filled in zones, TSS and laps (its
  ingest always sets `skip_tss_recalc`). The same reply opens a coach thread with a push when the
  athlete's debrief notification is on, and is texted while their `texts` notification setting is
  `active` (default). Skips workouts that ended more than `PHOTON_WORKOUT_MAX_AGE_HOURS` ago, are
  shorter than `PHOTON_MIN_WORKOUT_MINUTES`, or were already notified (`workouts.notified_at`; each
  debrief is also claimed once in `notification_log`).

## Setup

1. Create a **separate** Photon project (https://app.photon.codes) for the coach, register your
   phone number as a user, and note its project id, project secret, and assigned iMessage line.
2. Apply `supabase/migrations/20261020120000_photon_messaging.sql`.
3. Backend env:

   | Var | Value |
   |---|---|
   | `PHOTON_ATHLETE_ID` | your `athletes.id` |
   | `PHOTON_ALLOWED_NUMBER` | your number, E.164 |
   | `PHOTON_BRIDGE_TOKEN` | long random string, shared with the bridge |
   | `PHOTON_BRIDGE_URL` | bridge URL reachable from the backend (default `http://photon-bridge:8790`) |
   | `PHOTON_MIN_WORKOUT_MINUTES` / `PHOTON_WORKOUT_MAX_AGE_HOURS` | optional, default 10 / 12 |
   | `PHOTON_MAX_INBOUND_PER_MINUTE` | optional, default 10 |

4. Bridge env: `PHOTON_PROJECT_ID`, `PHOTON_PROJECT_SECRET`, `PHOTON_BRIDGE_TOKEN` (same as backend),
   `BACKEND_URL` (the backend's in-cluster URL), `PHOTON_ALLOWED_NUMBER`, optional `PORT`
   (default 8790).
5. Build/deploy `photon-bridge/` (`docker build -t astraphe-photon-bridge photon-bridge`) with
   `replicas: 1`. Keep the bridge's `/send` port private to the cluster. `GET /healthz` is the
   health check.

The channel is inert until `PHOTON_ATHLETE_ID`, `PHOTON_ALLOWED_NUMBER` and `PHOTON_BRIDGE_TOKEN`
are all set.

## Notes

- Shared/free Photon lines can't start a conversation with a number that never texted the line.
  Text the coach number once first.
- A Strava/WHOOP workout can arrive as several events; the first eligible one triggers the text, so
  it may be written from the earliest (sparsest) data.
- Tests: `backend/tests/test_photon_messaging.py`, `photon-bridge/lib.test.mjs` (`npm test`).

## Cluster bootstrap (one-time, k3s `astraphe` namespace)

CI (`deploy.yml`) builds `ghcr.io/sbalbale/astraphe-photon-bridge` and rolls it out with
`kubectl set image`, exactly like `astraphe-api` / `astraphe-mcp`. It can only patch an
**existing** Deployment, and `ci-deployer` is scoped narrowly, so do this once **before merging**
(otherwise `deploy-photon-bridge` fails on `main`):

1. Secret for the bridge (values from the Photon dashboard; generate the token with `openssl rand -hex 32`):
   ```bash
   kubectl -n astraphe create secret generic photon-bridge-secrets \
     --from-literal=project-id=<PHOTON_PROJECT_ID> \
     --from-literal=project-secret=<PHOTON_PROJECT_SECRET> \
     --from-literal=bridge-token=<TOKEN>
   ```
2. `kubectl apply -f photon-bridge/k8s.yaml` (Deployment pinned to 1 replica with `Recreate`, plus a
   ClusterIP Service). `BACKEND_URL` points at the `astraphe-api-lb` Service (port 8000); images pull via `ghcr-pull-secret`.
   The first pod will `ImagePullBackOff` until CI has pushed the image once.
3. Allow `ci-deployer` to patch the new Deployment: add `photon-bridge` to the `resourceNames` of the first rule in `Role/ci-deployer-astraphe`, i.e. its
   Role rule for `deployments` (`get`, `patch`) and `deployments/status`/rollout reads.
4. Backend env on the `astraphe-api` Deployment/Secret (CI never touches env):
   `PHOTON_ATHLETE_ID=<your athletes.id>`, `PHOTON_ALLOWED_NUMBER=<your E.164 number>`,
   `PHOTON_BRIDGE_TOKEN=<same token>`, `PHOTON_BRIDGE_URL=http://photon-bridge.astraphe.svc.cluster.local:8790` (backend env comes from the `astraphe-env` Secret via `envFrom`).
   Then `kubectl -n astraphe rollout restart deployment/astraphe-api`.

The migration (`20261020120000_photon_messaging.sql`) also marks workouts that started before 2026-10-20 (EDT) as already notified, so the first deploy does not text about history. It is additive and applied automatically by the
`migrate` job on merge, before the new backend rolls out.
