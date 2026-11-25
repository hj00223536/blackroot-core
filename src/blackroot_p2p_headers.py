"""Bounded codec for the prototype P2P headers message.

The payload follows the Bitcoin-style count + 80-byte header + zero tx-count
layout. It validates framing/canonical CompactSize only; consensus validation
must be performed separately by HeaderChain and full block validation.
"""
from __future__ import annotations

import struct

from .blackroot_chain import BlockHeader

MAX_HEADERS_PER_MESSAGE = 2_000


def _read_compact_size(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise ValueError("truncated headers count")
    marker = data[offset]
    offset += 1
    if marker < 253:
        return marker, offset
    sizes = {253: 2, 254: 4, 255: 8}
    size = sizes[marker]
    if len(data) - offset < size:
        raise ValueError("truncated headers count")
    value = int.from_bytes(data[offset:offset + size], "little")
    if (marker == 253 and value < 253) or (marker == 254 and value <= 0xFFFF) or (marker == 255 and value <= 0xFFFFFFFF):
        raise ValueError("non-canonical headers count")
    return value, offset + size


def _encode_compact_size(value: int) -> bytes:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("headers count must be a non-negative integer")
    if value < 253:
        return bytes((value,))
    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, "little")
    if value <= 0xFFFFFFFF:
        return b"\xfe" + value.to_bytes(4, "little")
    if value <= 0xFFFFFFFFFFFFFFFF:
        return b"\xff" + value.to_bytes(8, "little")
    raise ValueError("headers count exceeds uint64")


def encode_headers(headers: list[BlockHeader]) -> bytes:
    """Encode up to MAX_HEADERS_PER_MESSAGE headers with zero tx-count suffixes."""
    if not isinstance(headers, list):
        raise TypeError("headers must be a list")
    if len(headers) > MAX_HEADERS_PER_MESSAGE:
        raise ValueError("headers message exceeds configured header limit")
    output = bytearray(_encode_compact_size(len(headers)))
    for header in headers:
        if not isinstance(header, BlockHeader):
            raise TypeError("every item must be a BlockHeader")
        output.extend(header.serialize())
        output.append(0)  # CompactSize transaction count for headers messages
    return bytes(output)


def decode_headers(payload: bytes) -> list[BlockHeader]:
    """Decode one exact headers payload, rejecting non-canonical or trailing data."""
    if not isinstance(payload, bytes):
        raise TypeError("headers payload must be bytes")
    count, offset = _read_compact_size(payload, 0)
    if count > MAX_HEADERS_PER_MESSAGE:
        raise ValueError("headers message exceeds configured header limit")
    # Each entry is exactly 80 header bytes followed by a one-byte zero tx count.
    expected = offset + count * 81
    if len(payload) < expected:
        raise ValueError("truncated headers payload")
    if len(payload) > expected:
        raise ValueError("headers payload has trailing bytes")
    result = []
    for _ in range(count):
        raw = payload[offset:offset + 80]
        tx_count = payload[offset + 80]
        if tx_count != 0:
            raise ValueError("headers entry transaction count must be zero")
        version = struct.unpack_from("<I", raw, 0)[0]
        timestamp, bits, nonce = struct.unpack_from("<III", raw, 68)
        result.append(BlockHeader(
            version=version,
            prev_hash=raw[4:36],
            merkle_root=raw[36:68],
            timestamp=timestamp,
            bits=bits,
            nonce=nonce,
        ))
        offset += 81
    return result
