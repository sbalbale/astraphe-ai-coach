// Delete Firebase Hosting preview channels for closed PRs.
//
// Each PR preview deploys to a channel named `pr-<number>` (see
// firebase-hosting-pull-request.yml). Channels only expire on their TTL, so a
// burst of PRs can hit the per-site channel quota ("channel quota reached",
// HTTP 429) and every later PR preview fails. This script removes them.
//
// Modes (env):
//   FIREBASE_CHANNEL_ID=pr-123   delete that one channel (used when a PR closes)
//   KEEP_PR_NUMBERS=12,34        sweep: delete every `pr-N` channel whose N is not
//                                listed (pass the currently open PR numbers)
//   DRY_RUN=true                 log what would be deleted, delete nothing
// Auth: FIREBASE_SERVICE_ACCOUNT_JSON (same secret as the deploy) or FIREBASE_ACCESS_TOKEN.
// Never touches the `live` channel or channels not named `pr-<number>`.

import { createSign } from "node:crypto";
import { pathToFileURL } from "node:url";

const API_BASE = "https://firebasehosting.googleapis.com/v1beta1";
const TOKEN_URL = "https://oauth2.googleapis.com/token";
const FIREBASE_HOSTING_SCOPE = "https://www.googleapis.com/auth/firebase.hosting";
const PR_CHANNEL = /^pr-(\d+)$/;

/** Channel IDs to delete in sweep mode: `pr-N` channels whose PR is not in `keep`. Pure, for testing. */
export function channelsToDelete(channelIds, keepPrNumbers) {
  const keep = new Set(keepPrNumbers.map(String));
  return channelIds.filter((id) => {
    const m = PR_CHANNEL.exec(id);
    return m !== null && !keep.has(m[1]);
  });
}

/** Parse "12, 34,56" into ["12","34","56"]; rejects anything that isn't a PR number. */
export function parsePrNumbers(value) {
  const parts = value.split(",").map((s) => s.trim()).filter(Boolean);
  for (const p of parts) {
    if (!/^\d+$/.test(p)) throw new Error(`KEEP_PR_NUMBERS must be comma-separated PR numbers, got "${p}".`);
  }
  return parts;
}

function base64UrlEncode(value) {
  const buffer = Buffer.isBuffer(value) ? value : Buffer.from(value);
  return buffer.toString("base64").replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function resolveAccessToken() {
  if (process.env.FIREBASE_ACCESS_TOKEN) return process.env.FIREBASE_ACCESS_TOKEN;
  if (!process.env.FIREBASE_SERVICE_ACCOUNT_JSON) {
    throw new Error("FIREBASE_SERVICE_ACCOUNT_JSON or FIREBASE_ACCESS_TOKEN is required.");
  }
  const sa = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT_JSON);
  if (!sa.client_email || !sa.private_key) {
    throw new Error("FIREBASE_SERVICE_ACCOUNT_JSON must include client_email and private_key.");
  }
  const now = Math.floor(Date.now() / 1000);
  const header = base64UrlEncode(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = base64UrlEncode(
    JSON.stringify({ iss: sa.client_email, scope: FIREBASE_HOSTING_SCOPE, aud: TOKEN_URL, iat: now, exp: now + 3600 })
  );
  const unsigned = `${header}.${payload}`;
  const signature = createSign("RSA-SHA256").update(unsigned).sign(sa.private_key);
  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: `${unsigned}.${base64UrlEncode(signature)}`
    })
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.access_token) {
    throw new Error(`HTTP ${response.status} from ${TOKEN_URL}: ${body.error_description ?? body.error ?? "no access token"}`);
  }
  return body.access_token;
}

async function api(token, method, url) {
  const response = await fetch(url, { method, headers: { Authorization: `Bearer ${token}` } });
  const text = await response.text();
  return { status: response.status, ok: response.ok, body: text ? JSON.parse(text) : {} };
}

async function listChannelIds(token, parent) {
  const ids = [];
  let pageToken = "";
  do {
    const url = `${API_BASE}/${parent}/channels?pageSize=100${pageToken ? `&pageToken=${encodeURIComponent(pageToken)}` : ""}`;
    const res = await api(token, "GET", url);
    if (!res.ok) throw new Error(`HTTP ${res.status} listing channels: ${res.body.error?.message ?? JSON.stringify(res.body)}`);
    for (const ch of res.body.channels ?? []) ids.push(ch.name.split("/").pop());
    pageToken = res.body.nextPageToken ?? "";
  } while (pageToken);
  return ids;
}

async function deleteChannel(token, parent, id, dryRun) {
  if (!PR_CHANNEL.test(id)) throw new Error(`Refusing to delete non-PR channel "${id}".`);
  if (dryRun) {
    console.log(`[dry run] would delete ${id}`);
    return;
  }
  const res = await api(token, "DELETE", `${API_BASE}/${parent}/channels/${encodeURIComponent(id)}`);
  if (res.status === 404) console.log(`${id}: already gone`);
  else if (!res.ok) throw new Error(`HTTP ${res.status} deleting ${id}: ${res.body.error?.message ?? JSON.stringify(res.body)}`);
  else console.log(`${id}: deleted`);
}

async function main() {
  const project = process.env.FIREBASE_PROJECT;
  const site = process.env.FIREBASE_SITE ?? project;
  if (!project || !site) throw new Error("FIREBASE_PROJECT (and optionally FIREBASE_SITE) is required.");
  const dryRun = process.env.DRY_RUN === "true";
  const single = process.env.FIREBASE_CHANNEL_ID;
  const keepRaw = process.env.KEEP_PR_NUMBERS;
  if (!single && keepRaw === undefined) throw new Error("Set FIREBASE_CHANNEL_ID (one channel) or KEEP_PR_NUMBERS (sweep).");

  const token = await resolveAccessToken();
  const parent = `projects/${encodeURIComponent(project)}/sites/${encodeURIComponent(site)}`;

  if (single) {
    await deleteChannel(token, parent, single, dryRun);
    return;
  }
  const all = await listChannelIds(token, parent);
  const doomed = channelsToDelete(all, parsePrNumbers(keepRaw));
  console.log(`${all.length} channel(s) on ${site}; deleting ${doomed.length} for closed PRs.`);
  for (const id of doomed) await deleteChannel(token, parent, id, dryRun);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
