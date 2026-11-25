"""Bounded inventory-vector codecs for the BLACKROOT P2P prototype."""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAX_INVENTORY_ITEMS = 50_000
INV_TYPE_TX = 1
INV_TYPE_BLOCK = 2
SUPPORTED_INVENTORY_TYPES = frozenset({INV_TYPE_TX, INV_TYPE_BLOCK})


@dataclass(frozen=True)
class InventoryVector:
    """A supported transaction or block identifier."""
    kind: int
    item_hash: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.kind, int) or isinstance(self.kind, bool) or self.kind not in SUPPORTED_INVENTORY_TYPES:
            raise ValueError("unsupported inventory type")
        if not isinstance(self.item_hash, bytes) or len(self.item_hash) != 32:
            raise ValueError("inventory hash must be exactly 32 bytes")


def _compact_size(value: int) -> bytes:
    if value < 0xFD:
        return bytes((value,))
    if value <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", value)
    return b"\xfe" + struct.pack("<I", value)


def _read_compact_size(payload: bytes) -> tuple[int, int]:
    if not payload:
        raise ValueError("truncated inventory count")
    marker = payload[0]
    if marker < 0xFD:
        return marker, 1
    width, minimum = {0xFD: (2, 0xFD), 0xFE: (4, 0x10000), 0xFF: (8, 0x100000000)}[marker]
    if len(payload) < 1 + width:
        raise ValueError("truncated inventory count")
    value = int.from_bytes(payload[1:1 + width], "little")
    if value < minimum:
        raise ValueError("non-canonical inventory count")
    return value, 1 + width


def encode_inventory(items: list[InventoryVector]) -> bytes:
    """Encode a bounded inventory list used by inv/getdata/notfound."""
    if not isinstance(items, list):
        raise TypeError("inventory items must be a list")
    if len(items) > MAX_INVENTORY_ITEMS:
        raise ValueError("inventory count exceeds configured limit")
    output = bytearray(_compact_size(len(items)))
    for item in items:
        if not isinstance(item, InventoryVector):
            raise TypeError("every item must be an InventoryVector")
        output.extend(struct.pack("<I", item.kind))
        output.extend(item.item_hash)
    return bytes(output)


def decode_inventory(payload: bytes) -> list[InventoryVector]:
    """Decode one exact inventory payload, rejecting unsupported types."""
    if not isinstance(payload, bytes):
        raise TypeError("inventory payload must be bytes")
    count, offset = _read_compact_size(payload)
    if count > MAX_INVENTORY_ITEMS:
        raise ValueError("inventory count exceeds configured limit")
    expected = offset + count * 36
    if len(payload) < expected:
        raise ValueError("truncated inventory vector")
    if len(payload) > expected:
        raise ValueError("trailing bytes after inventory vectors")
    items = []
    for _ in range(count):
        kind = struct.unpack_from("<I", payload, offset)[0]
        item_hash = payload[offset + 4:offset + 36]
        offset += 36
        items.append(InventoryVector(kind, item_hash))
    return items
