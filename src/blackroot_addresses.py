"""Generic Base58Check and legacy P2PKH address helpers.

These helpers deliberately require an explicit version byte. BLACKROOT has
not frozen a production address prefix; callers must not infer one here.
This module does not generate or store private keys.
"""
from __future__ import annotations

import hashlib

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
# Bound untrusted text before doing repeated big-integer arithmetic.
MAX_BASE58_TEXT_LENGTH = 512
_INDEX = {char: index for index, char in enumerate(ALPHABET)}


def _checksum(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]


def b58encode(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise TypeError("raw value must be bytes")
    zeros = len(raw) - len(raw.lstrip(b"\x00"))
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded
    return "1" * zeros + encoded


def b58decode(text: str) -> bytes:
    if not isinstance(text, str):
        raise TypeError("Base58 value must be text")
    if len(text) > MAX_BASE58_TEXT_LENGTH:
        raise ValueError("Base58 value exceeds maximum length")
    number = 0
    for char in text:
        try:
            digit = _INDEX[char]
        except KeyError as exc:
            raise ValueError("invalid Base58 character") from exc
        number = number * 58 + digit
    zeros = len(text) - len(text.lstrip("1"))
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * zeros + body


def encode_base58check(version: int, payload: bytes) -> str:
    if not isinstance(version, int) or isinstance(version, bool) or not 0 <= version <= 255:
        raise ValueError("version must be a uint8")
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("payload must be non-empty bytes")
    body = bytes([version]) + payload
    return b58encode(body + _checksum(body))


def decode_base58check(address: str, *, expected_version: int | None = None,
                       payload_length: int | None = None) -> tuple[int, bytes]:
    if expected_version is not None and (
        not isinstance(expected_version, int)
        or isinstance(expected_version, bool)
        or not 0 <= expected_version <= 255
    ):
        raise ValueError("expected_version must be a uint8")
    if payload_length is not None and (
        not isinstance(payload_length, int)
        or isinstance(payload_length, bool)
        or payload_length <= 0
    ):
        raise ValueError("payload_length must be a positive integer")
    raw = b58decode(address)
    if len(raw) < 6:
        raise ValueError("Base58Check value is too short")
    body, supplied = raw[:-4], raw[-4:]
    if _checksum(body) != supplied:
        raise ValueError("Base58Check checksum mismatch")
    version, payload = body[0], body[1:]
    if expected_version is not None and version != expected_version:
        raise ValueError("unexpected address version")
    if payload_length is not None and len(payload) != payload_length:
        raise ValueError("unexpected address payload length")
    return version, payload


def p2pkh_address(hash160: bytes, *, version: int) -> str:
    """Encode a 20-byte HASH160; version is mandatory and has no default."""
    if not isinstance(hash160, bytes) or len(hash160) != 20:
        raise ValueError("P2PKH HASH160 must be exactly 20 bytes")
    return encode_base58check(version, hash160)


def p2pkh_script_from_address(address: str, *, expected_version: int) -> bytes:
    """Decode a version-checked P2PKH address into the 25-byte scriptPubKey."""
    _, digest = decode_base58check(
        address, expected_version=expected_version, payload_length=20
    )
    return bytes([0x76, 0xA9, 0x14]) + digest + bytes([0x88, 0xAC])
