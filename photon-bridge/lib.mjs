// Pure helpers for the bridge, kept separate from index.mjs so `node --test` can
// exercise them without a Photon connection.

const DM_CHAT_GUID_RE = /^any;-;(\+\d{6,})$/;
const E164_RE = /^\+\d{6,15}$/;
const URL_RE = /https?:\/\/[^\s)'"<>]+/i;

export function normalizeNumber(raw) {
  if (!raw) return null;
  const cleaned = String(raw).replace(/[\s\-().]/g, "");
  return E164_RE.test(cleaned) ? cleaned : null;
}

// Photon DM spaces are `any;-;+1555...`, or a bare E.164 number.
export function phoneFromSpaceId(spaceId) {
  if (typeof spaceId !== "string") return null;
  if (E164_RE.test(spaceId)) return spaceId;
  const m = spaceId.match(DM_CHAT_GUID_RE);
  return m ? m[1] : null;
}

// Plain text of a message body: a text content, or the text parts of a
// text+attachment group. Anything else (reactions, receipts, media-only) -> "".
export function extractText(content) {
  if (!content || typeof content !== "object") return "";
  if (content.type === "text") return content.text || "";
  if (content.type === "reply") return extractText(content.content);
  if (content.type === "group") {
    return (Array.isArray(content.items) ? content.items : [])
      .map((item) => extractText(item?.content))
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

// spectrum-ts' markdown() builder can 500 on raw URLs, and iMessage auto-links
// plain URLs anyway, so URL-bearing replies go out as plain text.
export function chooseSendFormat(text) {
  return URL_RE.test(String(text)) ? "text" : "markdown";
}

// Sender identity for an inbound event: the DM's phone number, else null (groups
// and unknown spaces are ignored by the bridge).
export function senderNumber(space, message) {
  return (
    normalizeNumber(space?.phone) ||
    normalizeNumber(message?.space?.phone) ||
    phoneFromSpaceId(space?.id) ||
    phoneFromSpaceId(message?.space?.id) ||
    null
  );
}
