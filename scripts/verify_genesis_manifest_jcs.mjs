import { createHash } from "node:crypto";
import assert from "node:assert/strict";

const DOMAIN = Buffer.from("BLACKROOT-GENESIS-MANIFEST-V1\0", "utf8");
const FOUNDER = 20_000_000n * 100_000_000n;
const CAP = 40_000_000n * 100_000_000n;

function compactSize(value) {
  if (value < 253) return Buffer.from([value]);
  if (value <= 0xffff) {
    const out = Buffer.alloc(3);
    out[0] = 0xfd;
    out.writeUInt16LE(value, 1);
    return out;
  }
  throw new Error("fixture CompactSize value out of range");
}
function varBytes(bytes) {
  return Buffer.concat([compactSize(bytes.length), bytes]);
}
function u32(value) {
  const out = Buffer.alloc(4);
  out.writeUInt32LE(value >>> 0);
  return out;
}
function u64(value) {
  const out = Buffer.alloc(8);
  out.writeBigUInt64LE(value);
  return out;
}
function sha256d(bytes) {
  const first = createHash("sha256").update(bytes).digest();
  return createHash("sha256").update(first).digest();
}
function canonicalize(value) {
  if (value === null || typeof value !== "object") {
    if (typeof value === "number") assert(Number.isSafeInteger(value));
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return "[" + value.map(canonicalize).join(",") + "]";
  const keys = Object.keys(value).sort();
  return "{" + keys.map((key) => JSON.stringify(key) + ":" + canonicalize(value[key])).join(",") + "}";
}

const founderScript = Buffer.from("76a914" + "55".repeat(20) + "88ac", "hex");
const coinbase = Buffer.concat([
  u32(1),
  compactSize(1),
  Buffer.alloc(32),
  u32(0xffffffff),
  varBytes(Buffer.from([0x01, 0x01])),
  u32(0xffffffff),
  compactSize(2),
  u64(0n),
  varBytes(Buffer.from([0x6a])),
  u64(FOUNDER),
  varBytes(founderScript),
  u32(0),
]);

const manifest = {
  manifest_version: 1,
  manifest_digest: "00".repeat(32),
  network_id: "11".repeat(32),
  genesis_block_hash: "22".repeat(32),
  genesis_coinbase_tx: coinbase.toString("hex"),
  founder_output_index: 1,
  founder_amount_sats: Number(FOUNDER),
  founder_script_pub_key: founderScript.toString("hex"),
  total_supply_cap_sats: Number(CAP),
  mining_schedule_id: "33".repeat(32),
  approval_record: "test-only-fixture; not owner approval",
};
const payload = { ...manifest };
delete payload.manifest_digest;
const digest = createHash("sha256")
  .update(DOMAIN)
  .update(Buffer.from(canonicalize(payload), "utf8"))
  .digest("hex");

assert.equal(digest, "9bb6346eff59ffa041f2d81ad640e0af04bde0feade6da4eef223c7744c86370");
assert.equal(sha256d(coinbase).reverse().toString("hex"),
  "114782ba397fdd4cb92497fdff2e71198ea5d3b6bd9632466ca38df91c3e1a12");
console.log("Independent genesis manifest JCS vector: OK");
