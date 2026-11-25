#!/usr/bin/env node
// Independent JavaScript/Node.js reproduction of the BLACKROOT genesis candidate.
// Uses only Node's built-in crypto module; does not import project Python code.
import { createHash } from "node:crypto";
import assert from "node:assert/strict";

const sha256d = (bytes) =>
  createHash("sha256").update(createHash("sha256").update(bytes).digest()).digest();
const u32le = (n) => {
  const b = Buffer.alloc(4);
  b.writeUInt32LE(n);
  return b;
};
const u64le = (n) => {
  const b = Buffer.alloc(8);
  b.writeBigUInt64LE(BigInt(n));
  return b;
};
const compactSize = (n) => {
  if (n < 253) return Buffer.from([n]);
  if (n <= 0xffff) {
    const b = Buffer.alloc(3);
    b[0] = 0xfd;
    b.writeUInt16LE(n, 1);
    return b;
  }
  throw new Error("fixture CompactSize value is outside this verifier's supported range");
};
const displayHash = (raw) => Buffer.from(raw).reverse().toString("hex");
const littleEndianInteger = (raw) => BigInt("0x" + Buffer.from(raw).reverse().toString("hex"));

function decodeCompact(bits) {
  const size = bits >>> 24;
  const word = bits & 0x007fffff;
  const negative = word !== 0 && (bits & 0x00800000) !== 0;
  const overflow = word !== 0 &&
    (size > 34 || (word > 0xff && size > 33) || (word > 0xffff && size > 32));
  let target = size <= 3
    ? BigInt(word >>> (8 * (3 - size)))
    : BigInt(word) << (8n * BigInt(size - 3));
  assert.equal(negative, false, "compact target must not be negative");
  assert.equal(overflow, false, "compact target must not overflow uint256");
  assert.ok(target > 0n && target < (1n << 256n), "compact target must be a positive uint256");
  return target;
}

function makeCoinbase() {
  // Version 1, one null-prevout input, scriptSig 01 01, final sequence,
  // one zero-value OP_RETURN output, locktime zero.
  return Buffer.concat([
    u32le(1),
    compactSize(1),
    Buffer.alloc(32),
    u32le(0xffffffff),
    compactSize(2),
    Buffer.from("0101", "hex"),
    u32le(0xffffffff),
    compactSize(1),
    u64le(0),
    compactSize(1),
    Buffer.from([0x6a]),
    u32le(0),
  ]);
}

const tx = makeCoinbase();
assert.equal(tx.length, 63);
assert.equal(
  tx.toString("hex"),
  "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff020101ffffffff010000000000000000016a00000000",
  "serialized genesis transaction mismatch",
);

const txidRaw = sha256d(tx);
assert.equal(
  displayHash(txidRaw),
  "35993aaf3055dd3e72466a4724bf6a0c4d1ff340130266b3a1c71b100490a42e",
  "genesis txid mismatch",
);

// A one-transaction genesis block has that transaction's raw txid as its merkle root.
const timestamp = 1_795_564_800;
const bits = 0x207fffff;
const nonce = 0;
const header = Buffer.concat([
  u32le(1),
  Buffer.alloc(32),
  txidRaw,
  u32le(timestamp),
  u32le(bits),
  u32le(nonce),
]);
assert.equal(header.length, 80);
assert.equal(
  header.toString("hex"),
  "0100000000000000000000000000000000000000000000000000000000000000000000002ea49004101bc7a1b366021340f31f4d0c6abf24476a46723edd5530af3a99350025066bffff7f2000000000",
  "serialized genesis header mismatch",
);

const blockHashRaw = sha256d(header);
assert.equal(
  displayHash(blockHashRaw),
  "12d0a70715fcc771e2228e8a8e2f85b4ada2b1bf2991c2a564553c0b9c922269",
  "genesis block hash mismatch",
);
const target = decodeCompact(bits);
assert.equal(target, 0x7fffffn << (8n * (0x20n - 3n)));
assert.ok(littleEndianInteger(blockHashRaw) <= target, "candidate genesis does not satisfy proof of work");

console.log("Independent Node.js genesis candidate verification: PASS");
console.log("transaction_bytes=63");
console.log("txid=" + displayHash(txidRaw));
console.log("header_bytes=80");
console.log("block_hash=" + displayHash(blockHashRaw));
console.log("proof_of_work=valid");
