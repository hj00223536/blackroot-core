import assert from "node:assert/strict";
import { createHash } from "node:crypto";

const manifest = {
  manifest_version: 2,
  network_id: "11".repeat(32),
  genesis_block_hash: "22".repeat(32),
  genesis_coinbase_tx: "00",
  founder_output_index: 1,
  founder_amount_sats: 2000000000000000,
  founder_script_pub_key: "51",
  total_supply_cap_sats: 4000000000000000,
  mining_schedule_id: "33".repeat(32),
};

const canonical = JSON.stringify(manifest, Object.keys(manifest).sort());
const digest = createHash("sha256")
  .update(Buffer.from("BLACKROOT-GENESIS-MANIFEST-V2\0", "utf8"))
  .update(Buffer.from(canonical, "utf8"))
  .digest("hex");

assert.equal(
  digest,
  "d5d7ee8495437bc233533966de69a8cb59583dc15f311fea8819a6bff6f604dd",
);
console.log("Independent v2 manifest digest vector: OK");
