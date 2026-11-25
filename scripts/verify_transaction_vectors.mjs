#!/usr/bin/env node
// Cross-language regression vector for the prototype's legacy transaction wire format.
// Uses only Node.js built-ins; this is not an external maintained client or audit.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";

const sha256d = (bytes) =>
  createHash("sha256").update(createHash("sha256").update(bytes).digest()).digest();

function compactSize(value) {
  assert(Number.isSafeInteger(value) && value >= 0 && value <= 0xffffffff,
    "fixture CompactSize value out of range");
  if (value < 253) return Buffer.from([value]);
  if (value <= 0xffff) {
    const out = Buffer.alloc(3); out[0] = 0xfd; out.writeUInt16LE(value, 1); return out;
  }
  const out = Buffer.alloc(5); out[0] = 0xfe; out.writeUInt32LE(value, 1); return out;
}

function readCompactSize(raw, offset) {
  assert(offset < raw.length, "truncated CompactSize");
  const prefix = raw[offset++];
  if (prefix < 253) return [prefix, offset];
  const width = prefix === 0xfd ? 2 : prefix === 0xfe ? 4 : 8;
  assert(offset + width <= raw.length, "truncated CompactSize payload");
  let value;
  if (width === 2) value = raw.readUInt16LE(offset);
  else if (width === 4) value = raw.readUInt32LE(offset);
  else {
    const wide = raw.readBigUInt64LE(offset);
    assert(wide <= BigInt(Number.MAX_SAFE_INTEGER), "fixture value exceeds safe integer");
    value = Number(wide);
  }
  const minimum = width === 2 ? 253 : width === 4 ? 0x10000 : 0x100000000;
  assert(value >= minimum, "non-canonical CompactSize encoding");
  return [value, offset + width];
}

function varBytes(value) { return Buffer.concat([compactSize(value.length), value]); }
function serializeFixture() {
  const version = Buffer.alloc(4); version.writeInt32LE(2);
  const index = Buffer.alloc(4); index.writeUInt32LE(0);
  const sequence = Buffer.alloc(4); sequence.writeUInt32LE(0xfffffffe);
  const outputValue = Buffer.alloc(8); outputValue.writeBigUInt64LE(123456n);
  const lockTime = Buffer.alloc(4); lockTime.writeUInt32LE(42);
  return Buffer.concat([
    version, compactSize(1), Buffer.alloc(32, 0x11), index,
    varBytes(Buffer.from("0102", "hex")), sequence,
    compactSize(1), outputValue, varBytes(Buffer.from("5121", "hex")), lockTime,
  ]);
}

function parseAndReserialize(raw) {
  let offset = 0;
  assert(raw.length >= 4, "truncated version");
  const version = raw.readInt32LE(offset); offset += 4;
  let count; [count, offset] = readCompactSize(raw, offset);
  assert(count === 1, "fixture input count mismatch");
  assert(offset + 36 <= raw.length, "truncated outpoint");
  const txid = raw.subarray(offset, offset + 32); offset += 32;
  const index = raw.subarray(offset, offset + 4); offset += 4;
  let scriptLength; [scriptLength, offset] = readCompactSize(raw, offset);
  assert(offset + scriptLength + 4 <= raw.length, "truncated input script/sequence");
  const scriptSig = raw.subarray(offset, offset + scriptLength); offset += scriptLength;
  const sequence = raw.subarray(offset, offset + 4); offset += 4;
  let outputCount; [outputCount, offset] = readCompactSize(raw, offset);
  assert(outputCount === 1, "fixture output count mismatch");
  assert(offset + 8 <= raw.length, "truncated output value");
  const value = raw.subarray(offset, offset + 8); offset += 8;
  let pkLength; [pkLength, offset] = readCompactSize(raw, offset);
  assert(offset + pkLength + 4 <= raw.length, "truncated output script/locktime");
  const scriptPubKey = raw.subarray(offset, offset + pkLength); offset += pkLength;
  const lockTime = raw.subarray(offset, offset + 4); offset += 4;
  assert.equal(offset, raw.length, "trailing transaction bytes");
  return Buffer.concat([
    Buffer.from(raw.subarray(0, 4)), compactSize(1), txid, index,
    varBytes(scriptSig), sequence, compactSize(1), value,
    varBytes(scriptPubKey), lockTime,
  ]);
}

const expectedHex = "0200000001111111111111111111111111111111111111111111111111111111111111111100000000020102feffffff0140e20100000000000251212a000000";
const expectedTxid = "45d2edad504593db9f267c0373055d07fef27d75a7c1d7bfa0e0b86870da7ad8";
const raw = serializeFixture();
assert.equal(raw.length, 64);
assert.equal(raw.toString("hex"), expectedHex);
assert.equal(parseAndReserialize(raw).toString("hex"), expectedHex);
assert.equal(sha256d(raw).reverse().toString("hex"), expectedTxid);

assert.equal(compactSize(252).toString("hex"), "fc");
assert.equal(compactSize(253).toString("hex"), "fdfd00");
assert.equal(compactSize(65535).toString("hex"), "fdffff");
assert.equal(compactSize(65536).toString("hex"), "fe00000100");
assert.throws(() => readCompactSize(Buffer.from("fdfc00", "hex"), 0), /non-canonical/);
assert.throws(() => readCompactSize(Buffer.from("feffff0000", "hex"), 0), /non-canonical/);
assert.throws(() => readCompactSize(Buffer.from("fd", "hex"), 0), /truncated/);
assert.throws(() => parseAndReserialize(Buffer.concat([raw, Buffer.from([0])])), /trailing/);
assert.throws(() => parseAndReserialize(raw.subarray(0, raw.length - 1)), /truncated/);

console.log("Independent Node.js transaction vector verification: PASS");
console.log("transaction_bytes=64");
console.log("txid=" + expectedTxid);
console.log("compact_size_boundaries=PASS");
console.log("canonicality_truncation_trailing=PASS");
