"""Strict P2PKH authorization checks for the BLACKROOT prototype.

Supports only legacy P2PKH, SIGHASH_ALL and secp256k1 ECDSA. Unsupported
scripts or sighash modes are rejected. This is not a complete Script engine.
"""
from __future__ import annotations

import hashlib
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from .blackroot_transactions import OutPoint, Transaction, TxOutput
from .blackroot_consensus import sha256d

# secp256k1 group order, used for strict low-S signature validation.
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
SIGHASH_ALL = 1
OP_DUP = 0x76
OP_HASH160 = 0xA9
OP_EQUALVERIFY = 0x88
OP_CHECKSIG = 0xAC


def _hash160(data: bytes) -> bytes:
    sha = hashlib.sha256(data).digest()
    try:
        return hashlib.new("ripemd160", sha).digest()
    except ValueError as exc:
        raise RuntimeError("RIPEMD160 is unavailable in this runtime") from exc


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
    parsed = _der_signature(signature_with_type[:-1])
    if parsed is None:
        return False
    # Delegate curve-point parsing and ECDSA verification to the maintained
    # cryptography/OpenSSL backend. Keep the consensus-specific strict-DER,
    # low-S, key-hash, and SIGHASH_ALL checks above this boundary.
    digest = legacy_sighash_all(tx, input_index, script)
    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256K1(), pubkey
        )
        public_key.verify(
            signature_with_type[:-1],
            digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def validate_transaction_scripts(tx: Transaction, utxos: dict[OutPoint, TxOutput]) -> None:
    """Require every input to pass the supported P2PKH authorization check."""
    for index, txin in enumerate(tx.inputs):
        previous = utxos.get(txin.previous_output)
        if previous is None:
            raise ValueError("referenced UTXO does not exist")
        if not verify_p2pkh_input(tx, index, previous):
            raise ValueError("input script verification failed or script type unsupported")
