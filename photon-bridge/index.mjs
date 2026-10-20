// Astraphe Photon bridge.
//
// Photon (iMessage) is gRPC-only via the TypeScript spectrum-ts SDK, so the Python
// backend can't talk to it directly. This single-replica service holds the stream:
//   inbound : app.messages -> POST {BACKEND_URL}/v1/messaging/photon/inbound
//   outbound: POST /send {to, text} (from the backend) -> space.send()
// Both directions are authenticated with PHOTON_BRIDGE_TOKEN. Run exactly ONE
// replica per Photon project: two consumers would fight over the same stream.
//
// Env (required): PHOTON_PROJECT_ID, PHOTON_PROJECT_SECRET, PHOTON_BRIDGE_TOKEN, BACKEND_URL
// Env (optional): PORT (8790), PHOTON_ALLOWED_NUMBER (drop everyone else before the backend)

import http from "node:http";
import crypto from "node:crypto";
import {
  chooseSendFormat,
  extractText,
  normalizeNumber,
  senderNumber,
} from "./lib.mjs";

const projectId = process.env.PHOTON_PROJECT_ID || process.env.SPECTRUM_PROJECT_ID;
const projectSecret = process.env.PHOTON_PROJECT_SECRET || process.env.SPECTRUM_PROJECT_SECRET;
const token = process.env.PHOTON_BRIDGE_TOKEN;
const backendUrl = (process.env.BACKEND_URL || "").replace(/\/$/, "");
const port = parseInt(process.env.PORT || "8790", 10);
const allowed = normalizeNumber(process.env.PHOTON_ALLOWED_NUMBER);

if (!projectId || !projectSecret || !token || !backendUrl) {
  console.error(
    "photon-bridge: PHOTON_PROJECT_ID, PHOTON_PROJECT_SECRET, PHOTON_BRIDGE_TOKEN " +
      "and BACKEND_URL must all be set."
  );
  process.exit(2);
}

const { Spectrum, text: spectrumText, markdown: spectrumMarkdown, typing: spectrumTyping } =
  await import("spectrum-ts");
const { imessage } = await import("spectrum-ts/providers/imessage");

const app = await Spectrum({
  projectId,
  projectSecret,
  providers: [imessage.config()],
  options: { flattenGroups: true },
  telemetry: false,
});

// --- space cache (phone number -> DM space) ---------------------------------
const spaces = new Map();

async function dmSpace(number) {
  const cached = spaces.get(number);
  if (cached) return cached;
  const space = await imessage(app).space.create(number);
  spaces.set(number, space);
  return space;
}

function tokenOk(provided) {
  if (!provided) return false;
  const a = Buffer.from(provided);
  const b = Buffer.from(token);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// --- inbound: Photon -> backend ---------------------------------------------
async function postToBackend(body) {
  // Retry transient failures; the backend dedupes on message_id so a retry after a
  // lost response is safe.
  let delay = 1000;
  for (let attempt = 1; attempt <= 4; attempt++) {
    try {
      const res = await fetch(`${backendUrl}/v1/messaging/photon/inbound`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-photon-bridge-token": token },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      });
      if (res.ok) return true;
      if (res.status < 500) {
        console.error(`photon-bridge: backend rejected inbound (${res.status})`);
        return false;
      }
    } catch (e) {
      console.error(`photon-bridge: backend post failed (attempt ${attempt}): ${e?.message || e}`);
    }
    await new Promise((r) => setTimeout(r, delay));
    delay *= 2;
  }
  return false;
}

async function handleInbound(space, message) {
  const sender = senderNumber(space, message);
  if (!sender || (allowed && sender !== allowed)) return;
  const text = extractText(message.content).trim();
  if (!text) return; // reactions, read receipts, media-only
  const messageId = message.id || `${sender}:${message.timestamp || Date.now()}`;

  const accepted = await postToBackend({ message_id: String(messageId), sender, text });
  if (!accepted) return;
  try {
    await message.read?.();
  } catch {}
  try {
    await space.send(spectrumTyping("start")); // coach replies can take a while
  } catch {}
}

(async () => {
  let backoff = 1000;
  for (;;) {
    try {
      for await (const [space, message] of app.messages) {
        backoff = 1000;
        if (message?.direction && message.direction !== "inbound") continue;
        handleInbound(space, message).catch((e) =>
          console.error("photon-bridge: inbound handling failed: " + (e?.stack || e))
        );
      }
      console.error("photon-bridge: inbound stream ended; re-subscribing");
    } catch (e) {
      console.error("photon-bridge: inbound stream errored: " + (e?.message || e));
    }
    await new Promise((r) => setTimeout(r, backoff + Math.random() * backoff * 0.2));
    backoff = Math.min(backoff * 2, 30000);
  }
})();

// --- outbound: backend -> Photon --------------------------------------------
function readJson(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (c) => {
      raw += c;
      if (raw.length > 64 * 1024) reject(new Error("body too large"));
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

function reply(res, status, obj) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(obj));
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/healthz") return reply(res, 200, { ok: true });
    if (req.method !== "POST" || req.url !== "/send") return reply(res, 404, { error: "not found" });
    if (!tokenOk(req.headers["x-photon-bridge-token"])) return reply(res, 401, { error: "unauthorized" });

    const { to, text } = await readJson(req);
    const number = normalizeNumber(to);
    if (!number || typeof text !== "string" || !text.trim()) {
      return reply(res, 400, { error: "to (E.164) and text are required" });
    }
    if (allowed && number !== allowed) return reply(res, 403, { error: "recipient not allowed" });

    const space = await dmSpace(number);
    const builder = chooseSendFormat(text) === "markdown" ? spectrumMarkdown(text) : spectrumText(text);
    const result = await space.send(builder);
    try {
      await space.send(spectrumTyping("stop"));
    } catch {}
    return reply(res, 200, { ok: true, messageId: result?.id || null });
  } catch (e) {
    console.error("photon-bridge: /send failed: " + (e?.stack || e));
    return reply(res, 500, { error: String(e?.message || e) });
  }
});

server.listen(port, "0.0.0.0", () => console.error(`photon-bridge: listening on :${port}`));

async function shutdown() {
  server.close();
  try {
    await Promise.race([app.stop(), new Promise((r) => setTimeout(r, 3000))]);
  } catch {}
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
