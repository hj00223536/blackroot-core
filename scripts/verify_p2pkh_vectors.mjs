#!/usr/bin/env node
// Cross-language P2PKH/SIGHASH_ALL verification vector.
// Uses Node built-ins plus a small transparent BigInt secp256k1 verifier.
// Regression evidence only; not constant-time and not a production crypto library.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";

const P = 0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2fn;
const N = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;
const G = [
  0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798n,
  0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8n,
];
const mod = (x, m) => ((x % m) + m) % m;
function powMod(base, exponent, modulus) {
  let result = 1n; base = mod(base, modulus);
  while (exponent > 0n) {
    if (exponent & 1n) result = result * base % modulus;
    base = base * base % modulus; exponent >>= 1n;
  }
  return result;
}
function pointAdd(a, b) {
  if (a === null) return b;
  if (b === null) return a;
  if (a[0] === b[0] && mod(a[1] + b[1], P) === 0n) return null;
  const slope = a[0] === b[0]
    ? mod(3n * a[0] * a[0] * powMod(2n * a[1], P - 2n, P), P)
    : mod((b[1] - a[1]) * powMod(b[0] - a[0], P - 2n, P), P);
  const x = mod(slope * slope - a[0] - b[0], P);
  return [x, mod(slope * (a[0] - x) - a[1], P)];
}
function pointMul(k, point = G) {
  let result = null, addend = point;
  while (k > 0n) {
    if (k & 1n) result = pointAdd(result, addend);
    addend = pointAdd(addend, addend); k >>= 1n;
  }
  return result;
}
const sha256 = b => createHash("sha256").update(b).digest();
const sha256d = b => sha256(sha256(b));
const hash160 = b => createHash("ripemd160").update(sha256(b)).digest();
const compact = n => n < 253 ? Buffer.from([n]) : Buffer.from([0xfd, n & 255, n >> 8]);
const varBytes = b => Buffer.concat([compact(b.length), b]);
const le32 = n => { const b = Buffer.alloc(4); b.writeUInt32LE(n); return b; };
const le64 = n => { const b = Buffer.alloc(8); b.writeBigUInt64LE(n); return b; };

function legacySighashAll(previous, scriptCode, outputValue = 90000n) {
  return Buffer.concat([
    le32(1), compact(1), previous, le32(0), varBytes(scriptCode), le32(0xffffffff),
    compact(1), le64(outputValue), varBytes(Buffer.from([0x51])), le32(0), le32(1),
  ]);
}
function parseStrictDer(der) {
  assert(der.length >= 8 && der.length <= 72 && der[0] === 0x30 && der[1] === der.length - 2, "bad DER sequence");
  let pos = 2;
  const readInt = () => {
    assert(der[pos++] === 0x02, "bad DER integer tag");
    const len = der[pos++];
    assert(len > 0 && pos + len <= der.length, "bad DER integer length");
    const bytes = der.subarray(pos, pos + len); pos += len;
    assert(!(bytes[0] & 0x80), "negative DER integer");
    assert(!(len > 1 && bytes[0] === 0 && !(bytes[1] & 0x80)), "non-minimal DER integer");
    return BigInt("0x" + bytes.toString("hex"));
  };
  const r = readInt(), s = readInt();
  assert.equal(pos, der.length, "trailing DER bytes");
  assert(r > 0n && r < N && s > 0n && s <= N / 2n, "signature scalar out of range or high-S");
  return [r, s];
}
function verifyEcdsa(digest, pubkey, der) {
  try {
    assert.equal(pubkey.length, 33);
    assert(pubkey[0] === 2 || pubkey[0] === 3);
    const x = BigInt("0x" + pubkey.subarray(1).toString("hex"));
    assert(x < P);
    const y2 = mod(x * x * x + 7n, P);
    let y = powMod(y2, (P + 1n) / 4n, P);
    assert.equal(y * y % P, y2, "public key is not on curve");
    if (Number(y & 1n) !== (pubkey[0] & 1)) y = P - y;
    const Q = [x, y];
    const [r, s] = parseStrictDer(der);
    const z = BigInt("0x" + digest.toString("hex"));
    const w = powMod(s, N - 2n, N);
    const candidate = pointAdd(pointMul(mod(z * w, N)), pointMul(mod(r * w, N), Q));
    return candidate !== null && candidate[0] % N === r;
  } catch { return false; }
}

const previous = Buffer.alloc(32, 0x12);
const pubkey = Buffer.from("0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798", "hex");
const expectedHash160 = "751e76e8199196d454941c45d1b3a323f1433bd6";
const lockingScript = Buffer.concat([Buffer.from("76a914", "hex"), Buffer.from(expectedHash160, "hex"), Buffer.from("88ac", "hex")]);
const der = Buffer.from("3045022100c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5022018ebf283fe1bf45f6ad4639649fe7281701730ea3a378f875a75f5cfddc8e48d", "hex");
const digest = sha256d(legacySighashAll(previous, lockingScript));
assert.equal(hash160(pubkey).toString("hex"), expectedHash160);
assert.equal(digest.toString("hex"), "08239b63c1da99d3fa11f864d6429e237e08ecc6adea44855f3a6933b833d942");
assert.equal(verifyEcdsa(digest, pubkey, der), true, "valid deterministic P2PKH signature must verify");
assert.equal(verifyEcdsa(sha256d(legacySighashAll(previous, lockingScript, 89999n)), pubkey, der), false,
  "modified output must invalidate signature");
const highS = Buffer.from("3046022100c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5022100e7140d7c01e40ba0952b9c69b6018d7d4a7ecbf1c5c871b4655ca8bcf26d5cb4", "hex");
assert.equal(verifyEcdsa(digest, pubkey, highS), false, "high-S signature must be rejected");
console.log("Independent Node.js P2PKH signature vector verification: PASS");
console.log("hash160=" + expectedHash160);
console.log("sighash=" + digest.toString("hex"));
console.log("valid_signature=PASS modified_transaction=REJECTED high_s=REJECTED");
