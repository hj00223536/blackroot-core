import assert from "node:assert/strict";
import { createHash } from "node:crypto";

const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const INDEX = new Map([...ALPHABET].map((ch, i) => [ch, i]));

function sha256(data) {
  return createHash("sha256").update(data).digest();
}
function checksum(data) {
  return sha256(sha256(data)).subarray(0, 4);
}
function b58encode(data) {
  let zeros = 0;
  while (zeros < data.length && data[zeros] === 0) zeros++;
  let n = BigInt("0x" + data.toString("hex"));
  let out = "";
  while (n > 0n) {
    const rem = Number(n % 58n);
    n /= 58n;
    out = ALPHABET[rem] + out;
  }
  return "1".repeat(zeros) + out;
}
function b58decode(text) {
  let n = 0n;
  for (const ch of text) {
    assert.ok(INDEX.has(ch), "invalid Base58 character");
    n = n * 58n + BigInt(INDEX.get(ch));
  }
  let hex = n === 0n ? "" : n.toString(16).padStart(Math.ceil(n.toString(16).length / 2) * 2, "0");
  const body = hex ? Buffer.from(hex, "hex") : Buffer.alloc(0);
  const zeros = text.length - text.replace(/^1+/, "").length;
  return Buffer.concat([Buffer.alloc(zeros), body]);
}
function encode(version, payload) {
  const body = Buffer.concat([Buffer.from([version]), payload]);
  return b58encode(Buffer.concat([body, checksum(body)]));
}
function decode(address, expectedVersion, payloadLength) {
  const raw = b58decode(address);
  assert.ok(raw.length >= 6, "Base58Check value too short");
  const body = raw.subarray(0, -4);
  assert.deepEqual(raw.subarray(-4), checksum(body), "checksum mismatch");
  assert.equal(body[0], expectedVersion, "wrong network version");
  assert.equal(body.length - 1, payloadLength, "wrong payload length");
  return body.subarray(1);
}

const hash160 = Buffer.from("592fc3990026334c8c6fb2b9da457179cdb5c688", "hex");
const expected = "GRyVmuRWX2EJ2KXNJs2Zu8KC11YX27ZKb1";
const address = encode(0x26, hash160);
assert.equal(address, expected, "independent Base58Check vector mismatch");
assert.deepEqual(decode(address, 0x26, 20), hash160);
assert.throws(() => decode(address, 0x00, 20), /wrong network version/);
assert.throws(() => decode(address.slice(0, -1) + (address.endsWith("1") ? "2" : "1"), 0x26, 20), /checksum mismatch/);
assert.throws(() => decode(encode(0x26, Buffer.from("short")), 0x26, 20), /wrong payload length/);

console.log("Independent Base58Check/P2PKH address vectors passed (Node.js 22).");
