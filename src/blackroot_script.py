"""Strict P2PKH authorization checks for the BLACKROOT prototype.

Supports only legacy P2PKH, SIGHASH_ALL and secp256k1 ECDSA. Unsupported
scripts or sighash modes are rejected. This is not a complete Script engine.
"""
from __future__ import annotations

import hashlib
import struct

from .blackroot_transactions import OutPoint, Transaction, TxOutput
from .blackroot_consensus import sha256d

# secp256k1 domain parameters
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)
SIGHASH_ALL = 1
OP_DUP = 0x76
OP_HASH160 = 0xA9
OP_EQUALVERIFY = 0x88
OP_CHECKSIG = 0xAC


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    if a == b:
        slope = (3 * a[0] * a[0]) * pow(2 * a[1], P - 2, P) % P
    else:
        slope = (b[1] - a[1]) * pow((b[0] - a[0]) % P, P - 2, P) % P
    x = (slope * slope - a[0] - b[0]) % P
    return x, (slope * (a[0] - x) - a[1]) % P


def _mul(k, point=G):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def _hash160(data: bytes) -> bytes:
    sha = hashlib.sha256(data).digest()
    try:
        return hashlib.new("ripemd160", sha).digest()
    except ValueError as exc:
        raise RuntimeError("RIPEMD160 is unavailable in this runtime") from exc


def _parse_pubkey(raw: bytes):
    if len(raw) == 33 and raw[0] in (2, 3):
        x = int.from_bytes(raw[1:], "big")
        if x >= P:
            return None
        y2 = (pow(x, 3, P) + 7) % P
        y = pow(y2, (P + 1) // 4, P)
        if y * y % P != y2:
            return None
        if y & 1 != raw[0] & 1:
            y = P - y
        return x, y
    if len(raw) == 65 and raw[0] == 4:
        x, y = int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big")
        if x >= P or y >= P or (y * y - x * x * x - 7) % P:
            return None
        return x, y
    return None


def _der_signature(raw: bytes):
    if len(raw) < 8 or len(raw) > 72 or raw[0] != 0x30 or raw[1] != len(raw) - 2:
        return None
    if raw[2] != 0x02:
        return None
    rlen = raw[3]
    if rlen == 0 or 4 + rlen + 2 > len(raw):
        return None
    rraw = raw[4:4 + rlen]
    pos = 4 + rlen
    if raw[pos] != 0x02:
        return None
    slen = raw[pos + 1]
    sraw = raw[pos + 2:]
    if slen == 0 or len(sraw) != slen:
        return None
    for item in (rraw, sraw):
        if item[0] & 0x80:
            return None
        if len(item) > 1 and item[0] == 0 and not item[1] & 0x80:
            return None
    r, s = int.from_bytes(rraw, "big"), int.from_bytes(sraw, "big")
    if not (1 <= r < N and 1 <= s <= N // 2):
        return None
    return r, s


def _push(data: bytes) -> bytes:
    if len(data) > 75:
        raise ValueError("P2PKH push exceeds supported direct-push size")
    return bytes([len(data)]) + data


def p2pkh_script(hash160: bytes) -> bytes:
    if not isinstance(hash160, bytes) or len(hash160) != 20:
        raise ValueError("P2PKH hash must be 20 bytes")
    return bytes([OP_DUP, OP_HASH160, 20]) + hash160 + bytes([OP_EQUALVERIFY, OP_CHECKSIG])


def legacy_sighash_all(tx: Transaction, input_index: int, script_code: bytes) -> bytes:
    if not 0 <= input_index < len(tx.inputs):
        raise ValueError("input index out of range")
    result = struct.pack("<i", tx.version) + _compact(len(tx.inputs))
    for index, txin in enumerate(tx.inputs):
        script = script_code if index == input_index else b""
        result += txin.previous_output.serialize() + _varbytes(script) + struct.pack("<I", txin.sequence)
    result += _compact(len(tx.outputs))
    for output in tx.outputs:
        result += output.serialize()
    result += struct.pack("<II", tx.lock_time, SIGHASH_ALL)
    return sha256d(result)


def _compact(value: int) -> bytes:
    if value < 253:
        return bytes([value])
    if value <= 0xffff:
        return b"\xfd" + struct.pack("<H", value)
    if value <= 0xffffffff:
        return b"\xfe" + struct.pack("<I", value)
    return b"\xff" + struct.pack("<Q", value)


def _varbytes(value: bytes) -> bytes:
    return _compact(len(value)) + value


def _script_pushes(script: bytes):
    values = []
    pos = 0
    while pos < len(script):
        opcode = script[pos]
        pos += 1
        if not 1 <= opcode <= 75 or pos + opcode > len(script):
            return None
        values.append(script[pos:pos + opcode])
        pos += opcode
    return values


def verify_p2pkh_input(tx: Transaction, input_index: int, previous_output: TxOutput) -> bool:
    """Verify one P2PKH input; unsupported script forms fail closed."""
    if not isinstance(tx, Transaction) or not isinstance(previous_output, TxOutput):
        return False
    if not 0 <= input_index < len(tx.inputs):
        return False
    script = previous_output.script_pubkey
    if len(script) != 25 or script[:3] != bytes([OP_DUP, OP_HASH160, 20]) or script[-2:] != bytes([OP_EQUALVERIFY, OP_CHECKSIG]):
        return False
    pushes = _script_pushes(tx.inputs[input_index].script_sig)
    if pushes is None or len(pushes) != 2:
        return False
    signature_with_type, pubkey = pushes
    if len(signature_with_type) < 2 or signature_with_type[-1] != SIGHASH_ALL:
        return False
    if _hash160(pubkey) != script[3:23]:
        return False
    point = _parse_pubkey(pubkey)
    parsed = _der_signature(signature_with_type[:-1])
    if point is None or parsed is None:
        return False
    r, s = parsed
    z = int.from_bytes(legacy_sighash_all(tx, input_index, script), "big")
    w = pow(s, N - 2, N)
    candidate = _add(_mul((z * w) % N), _mul((r * w) % N, point))
    return candidate is not None and candidate[0] % N == r


def validate_transaction_scripts(tx: Transaction, utxos: dict[OutPoint, TxOutput]) -> None:
    """Require every input to pass the supported P2PKH authorization check."""
    for index, txin in enumerate(tx.inputs):
        previous = utxos.get(txin.previous_output)
        if previous is None:
            raise ValueError("referenced UTXO does not exist")
        if not verify_p2pkh_input(tx, index, previous):
            raise ValueError("input script verification failed or script type unsupported")
