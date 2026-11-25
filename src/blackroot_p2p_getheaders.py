"""Bounded getheaders locator message codec for BLACKROOT P2P."""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAX_BLOCK_LOCATOR_HASHES = 101


@dataclass(frozen=True)
class GetHeadersMessage:
    protocol_version: int
    locator_hashes: tuple[bytes, ...]
    stop_hash: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.protocol_version, int) or isinstance(self.protocol_version, bool) or not 1 <= self.protocol_version <= 0x7FFFFFFF:
            raise ValueError("protocol version must be a positive int32")
        if not isinstance(self.locator_hashes, tuple):
            raise TypeError("locator_hashes must be a tuple")
        if len(self.locator_hashes) > MAX_BLOCK_LOCATOR_HASHES:
            raise ValueError("block locator exceeds configured limit")
        if any(not isinstance(item, bytes) or len(item) != 32 for item in self.locator_hashes):
            raise ValueError("each locator hash must be exactly 32 bytes")
        if not isinstance(self.stop_hash, bytes) or len(self.stop_hash) != 32:
            raise ValueError("stop hash must be exactly 32 bytes")


def _encode_compact_size(value: int) -> bytes:
    if value < 0xFD:
        return bytes((value,))
    if value <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", value)
    return b"\xfe" + struct.pack("<I", value)


def _decode_compact_size(payload: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(payload):
        raise ValueError("truncated locator count")
    marker = payload[offset]
    offset += 1
    if marker < 0xFD:
        return marker, offset
    width, minimum = {0xFD: (2, 0xFD), 0xFE: (4, 0x10000), 0xFF: (8, 0x100000000)}[marker]
    if len(payload) - offset < width:
        raise ValueError("truncated locator count")
    count = int.from_bytes(payload[offset:offset + width], "little")
    if count < minimum:
        raise ValueError("non-canonical locator count")
    return count, offset + width


def encode_getheaders(message: GetHeadersMessage) -> bytes:
    """Encode version, bounded locator vector, and stop hash."""
    if not isinstance(message, GetHeadersMessage):
        raise TypeError("message must be a GetHeadersMessage")
    return (
        struct.pack("<i", message.protocol_version)
        + _encode_compact_size(len(message.locator_hashes))
        + b"".join(message.locator_hashes)
        + message.stop_hash
    )


def decode_getheaders(payload: bytes) -> GetHeadersMessage:
    """Decode one exact getheaders payload with canonical bounded locator."""
    if not isinstance(payload, bytes):
        raise TypeError("getheaders payload must be bytes")
    if len(payload) < 4:
        raise ValueError("truncated getheaders version")
    version = struct.unpack_from("<i", payload, 0)[0]
    count, offset = _decode_compact_size(payload, 4)
    if count > MAX_BLOCK_LOCATOR_HASHES:
        raise ValueError("block locator exceeds configured limit")
    expected = offset + count * 32 + 32
    if len(payload) < expected:
        raise ValueError("truncated getheaders locator or stop hash")
    if len(payload) > expected:
        raise ValueError("trailing bytes after getheaders payload")
    hashes = tuple(
        payload[offset + index * 32:offset + (index + 1) * 32]
        for index in range(count)
    )
    stop_hash = payload[offset + count * 32:expected]
    return GetHeadersMessage(version, hashes, stop_hash)
