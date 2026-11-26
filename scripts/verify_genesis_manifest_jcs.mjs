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
function assertUnicodeScalarString(value) {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      assert(next >= 0xdc00 && next <= 0xdfff, "unpaired high surrogate");
      index += 1;
    } else {
      assert(!(unit >= 0xdc00 && unit <= 0xdfff), "unpaired low surrogate");
    }
  }
}
function canonicalize(value) {
  if (typeof value === "string") assertUnicodeScalarString(value);
  if (value === null || typeof value !== "object") {
    if (typeof value === "number") assert(Number.isSafeInteger(value));
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return "[" + value.map(canonicalize).join(",") + "]";
  const keys = Object.keys(value).sort();
  for (const key of keys) assertUnicodeScalarString(key);
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
assert.equal(canonicalize({ text: "café 雪 😀" }), '{"text":"café 雪 😀"}');
assert.equal(canonicalize({ control: "\\u0000\\b\\t\\n\\f\\r" }),
  '{"control":"\\\\u0000\\\\b\\\\t\\\\n\\\\f\\\\r"}');
assert.equal(canonicalize({ "\\ue000": 1, "😀": 2 }), '{"😀":2,"\\ue000":1}');
assert.throws(() => canonicalize("unpaired-\\ud800"), /unpaired high surrogate/);
assert.throws(() => canonicalize({ "bad-\\udfff": 1 }), /unpaired low surrogate/);
assert.equal(sha256d(coinbase).reverse().toString("hex"),
  "b8119fc7d37dd8983eacfc85e3a312d9e1ec8bfeca53c30e844003a23070a5cd");
console.log("Independent genesis manifest JCS vector: OK");
