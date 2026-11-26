import assert from "node:assert/strict";
import { createHash } from "node:crypto";

const publicKey = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a";
const config = {
  config_version: 1,
  network_id: "11".repeat(32),
  sequence: 1,
  previous_config_digest: null,
  keys: [{
    key_id: "21fe31dfa154a261626bf854046fd2271b7bed4b6abe45aa58877ef47f9721b9",
    public_key: publicKey,
    scopes: ["genesis-founder-allocation"],
    status: "active",
  }],
};

function canonicalize(value) {
  if (Array.isArray(value)) return "[" + value.map(canonicalize).join(",") + "]";
  if (value !== null && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(
      key => JSON.stringify(key) + ":" + canonicalize(value[key])
    ).join(",") + "}";
  }
  return JSON.stringify(value);
}

const digest = createHash("sha256")
  .update(Buffer.from("BLACKROOT-TRUST-CONFIG-V1\0", "utf8"))
  .update(Buffer.from(canonicalize(config), "utf8"))
  .digest("hex");

assert.equal(
  digest,
  "157f3c321befaaaf8f9180c90fdb0ed3164ff9e71c070a664e14a7fbad1456ab",
);
console.log("Independent trust configuration digest vector: OK");
