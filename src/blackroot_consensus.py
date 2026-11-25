"""BLACKROOT consensus reference helpers.

This module is deliberately small and is NOT a full node or production consensus
implementation. It provides testable helpers for the 80-byte header, SHA-256d,
Bitcoin-style compact targets, proof-of-work comparison, and subsidy schedule.
"""
from __future__ import annotations

import hashlib
import struct

COIN = 100_000_000
INITIAL_SUBSIDY = 50 * COIN
HALVING_INTERVAL = 210_000
TARGET_SPACING = 600
DIFFICULTY_INTERVAL = 2_016
MAX_MONEY = 21_000_000 * COIN


def block_subsidy(height: int) -> int:
    """Return scheduled block subsidy in atomic units for a non-negative height."""
    if not isinstance(height, int) or isinstance(height, bool) or height < 0:
        raise ValueError("height must be a non-negative integer")
    halvings = height // HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return INITIAL_SUBSIDY >> halvings


def sha256d(data: bytes) -> bytes:
    """Return the raw 32-byte double-SHA256 digest."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def serialize_header(
    version: int,
    prev_hash: bytes,
    merkle_root: bytes,
    timestamp: int,
    bits: int,
    nonce: int,
) -> bytes:
    """Serialize a Bitcoin-style 80-byte block header."""
    for name, value in (("prev_hash", prev_hash), ("merkle_root", merkle_root)):
        if not isinstance(value, bytes) or len(value) != 32:
            raise ValueError(f"{name} must be exactly 32 bytes")
    for name, value in (
        ("version", version),
        ("timestamp", timestamp),
        ("bits", bits),
        ("nonce", nonce),
    ):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"{name} must fit in uint32")
    return (
        struct.pack("<I", version)
        + prev_hash
        + merkle_root
        + struct.pack("<III", timestamp, bits, nonce)
    )


def decode_compact_target(bits: int) -> int:
    """Decode Bitcoin-style nBits and reject negative/overflow/zero targets."""
    if not isinstance(bits, int) or isinstance(bits, bool) or not 0 <= bits <= 0xFFFFFFFF:
        raise ValueError("bits must fit in uint32")
    size = bits >> 24
    word = bits & 0x007FFFFF
    negative = word != 0 and (bits & 0x00800000) != 0
    if size <= 3:
        target = word >> (8 * (3 - size))
    else:
        target = word << (8 * (size - 3))
    overflow = word != 0 and (
        size > 34 or (word > 0xFF and size > 33) or (word > 0xFFFF and size > 32)
    )
    if negative or overflow or target == 0:
        raise ValueError("invalid compact target")
    return target


def check_proof_of_work(header: bytes, bits: int, pow_limit: int) -> bool:
    """Check SHA-256d(header) <= target, with an explicit network pow_limit."""
    if not isinstance(header, bytes) or len(header) != 80:
        raise ValueError("header must be exactly 80 bytes")
    if not isinstance(pow_limit, int) or isinstance(pow_limit, bool) or pow_limit <= 0:
        raise ValueError("pow_limit must be a positive integer")
    target = decode_compact_target(bits)
    if target > pow_limit:
        return False
    hash_as_integer = int.from_bytes(sha256d(header), "little")
    return hash_as_integer <= target


def format_hash(digest: bytes) -> str:
    """Format a raw SHA-256d digest in conventional reversed display order."""
    if not isinstance(digest, bytes) or len(digest) != 32:
        raise ValueError("digest must be exactly 32 bytes")
    return digest[::-1].hex()
