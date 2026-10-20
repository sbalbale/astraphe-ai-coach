import test from "node:test";
import assert from "node:assert/strict";
import { chooseSendFormat, extractText, normalizeNumber, phoneFromSpaceId, senderNumber } from "./lib.mjs";

test("normalizeNumber", () => {
  assert.equal(normalizeNumber("+1 (555) 123-4567"), "+15551234567");
  assert.equal(normalizeNumber("5551234567"), null);
  assert.equal(normalizeNumber(null), null);
});

test("phoneFromSpaceId handles DM guids and bare numbers, not groups", () => {
  assert.equal(phoneFromSpaceId("any;-;+15551234567"), "+15551234567");
  assert.equal(phoneFromSpaceId("+15551234567"), "+15551234567");
  assert.equal(phoneFromSpaceId("any;+;chat123"), null);
});

test("extractText: text, reply, group; ignores reactions/media", () => {
  assert.equal(extractText({ type: "text", text: "hi" }), "hi");
  assert.equal(extractText({ type: "reply", content: { type: "text", text: "yo" } }), "yo");
  assert.equal(
    extractText({ type: "group", items: [{ content: { type: "text", text: "a" } }, { content: { type: "attachment" } }] }),
    "a"
  );
  assert.equal(extractText({ type: "reaction", emoji: "👍" }), "");
  assert.equal(extractText(null), "");
});

test("chooseSendFormat routes URLs through plain text", () => {
  assert.equal(chooseSendFormat("nice ride"), "markdown");
  assert.equal(chooseSendFormat("see https://example.com/x"), "text");
});

test("senderNumber falls back from space.phone to space id", () => {
  assert.equal(senderNumber({ phone: "+15551234567" }, {}), "+15551234567");
  assert.equal(senderNumber({ id: "any;-;+15551234567" }, {}), "+15551234567");
  assert.equal(senderNumber({ id: "any;+;group" }, {}), null);
});
