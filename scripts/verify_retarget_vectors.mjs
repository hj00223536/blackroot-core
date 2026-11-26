#!/usr/bin/env node
// Independent Node.js 22 vectors for BLACKROOT's current compact-target retarget arithmetic.
// This records current prototype behavior; it does not approve the unresolved protocol rules.
import assert from "node:assert/strict";

const U256 = 1n << 256n;
function decodeCompact(bits) {
  assert(Number.isInteger(bits) && bits >= 0 && bits <= 0xffffffff);
  const size = bits >>> 24;
  const word = bits & 0x007fffff;
  const negative = word !== 0 && (bits & 0x00800000) !== 0;
  const overflow = word !== 0 &&
    (size > 34 || (word > 0xff && size > 33) || (word > 0xffff && size > 32));
  const target = size <= 3
    ? BigInt(word >>> (8 * (3 - size)))
    : BigInt(word) << (8n * BigInt(size - 3));
  assert.equal(negative, false, "negative compact target");
  assert.equal(overflow, false, "overflow compact target");
  assert.ok(target > 0n && target < U256, "target outside positive uint256");
  return target;
}
function encodeCompact(target) {
  assert.ok(typeof target === "bigint" && target > 0n && target < U256);
  let size = Math.ceil(target.toString(2).length / 8);
  let compact = size <= 3
    ? target << (8n * BigInt(3 - size))
    : target >> (8n * BigInt(size - 3));
  if ((compact & 0x00800000n) !== 0n) {
    compact >>= 8n;
    size += 1;
  }
  return ((size << 24) | Number(compact & 0x007fffffn)) >>> 0;
}
function retarget(previousBits, actualTimespan, powLimit, targetTimespan = 2016 * 600) {
  assert(Number.isSafeInteger(actualTimespan) && actualTimespan > 0);
  const previousTarget = decodeCompact(previousBits);
  assert(previousTarget <= powLimit);
  const bounded = Math.max(Math.floor(targetTimespan / 4),
    Math.min(actualTimespan, targetTimespan * 4));
  const nextTarget = previousTarget * BigInt(bounded) / BigInt(targetTimespan);
  return encodeCompact(nextTarget > powLimit ? powLimit : nextTarget);
}

const span = 2016 * 600;
const powLimit = decodeCompact(0x207fffff);

// Existing repository unit-vector parity: quarter, nominal, double, and four-times clamps.
const previousBits = 0x1f3fffff;
const limit = powLimit;
assert.equal(retarget(previousBits, 1, limit), 0x1f0fffff);
assert.equal(retarget(previousBits, span / 4, limit), 0x1f0fffff);
assert.equal(retarget(previousBits, span, limit), 0x1f3fffff);
assert.equal(retarget(previousBits, span * 2, limit), 0x1f7ffffe);
assert.equal(retarget(previousBits, span * 4, limit), 0x2000ffff);
assert.equal(retarget(previousBits, span * 20, limit), 0x2000ffff);

// Explicitly expose the current first-boundary convention: at candidate height
// 2016, parent height 2015 minus ancestor height 0 spans 2015 * 600 seconds,
// while the target span remains 2016 * 600 seconds.
assert.equal(retarget(0x207fffff, 2015 * 600, powLimit), 0x207fefbd);
assert.equal(retarget(0x207fffff, 2016 * 600, powLimit), 0x207fffff);
assert.equal(retarget(0x207fffff, 2017 * 600, powLimit), 0x207fffff);
// Integer-floor rounding and the zero-target fail-closed edge.
const floorTarget = decodeCompact(previousBits) * 333n / 1_000n;
assert.equal(retarget(previousBits, 333, limit, 1_000), encodeCompact(floorTarget));
assert.throws(
  () => retarget(0x01010000, 1, powLimit, 4),
  /positive uint256/,
);
assert.equal(decodeCompact(encodeCompact(decodeCompact(0x207fffff))), decodeCompact(0x207fffff));

console.log("Independent Node.js retarget arithmetic vectors: PASS");
console.log("clamp_vectors=PASS");
console.log("first_boundary_2015_intervals=0x207fefbd");
console.log("nominal_2016_intervals=0x207fffff");
console.log("NOTE: first-boundary convention remains provisional and requires protocol approval.");
