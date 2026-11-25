"""Bounded peer-address message codec for the BLACKROOT P2P prototype.

Addresses are wire-format endpoints only. Decoding does not make an endpoint
trusted, reachable, safe to dial, or eligible for public address relay.
"""
from __future__ import annotations

import ipaddress
import struct
from dataclasses import dataclass

MAX_ADDRESSES_PER_MESSAGE = 1_000
_COMPACT_SIZE_MAX = 0xFFFF


@dataclass(frozen=True)
class PeerAddress:
    timestamp: int
    services: int
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, int) or isinstance(self.timestamp, bool) or not 0 <= self.timestamp <= 0xFFFFFFFF:
            raise ValueError("address timestamp must fit uint32")
        if not isinstance(self.services, int) or isinstance(self.services, bool) or not 0 <= self.services <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("address services must fit uint64")
        if not isinstance(self.ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            raise TypeError("ip must be an IPv4Address or IPv6Address")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("address port must be between 1 and 65535")

    @property
    def endpoint(self) -> tuple[str, int]:
        return str(self.ip), self.port


def _compact_size(value: int) -> bytes:
    if value < 0xFD:
        return bytes((value,))
    if value <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", value)
    return b"\xfe" + struct.pack("<I", value)


def _read_compact_size(payload: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(payload):
        raise ValueError("truncated address count")
    prefix = payload[offset]
    offset += 1
    if prefix < 0xFD:
        return prefix, offset
    widths = {0xFD: (2, 0xFD), 0xFE: (4, 0x10000), 0xFF: (8, 0x100000000)}
    width, minimum = widths[prefix]
    if len(payload) - offset < width:
        raise ValueError("truncated address count")
    value = int.from_bytes(payload[offset:offset + width], "little")
    if value < minimum:
        raise ValueError("non-canonical address count")
    return value, offset + width


def _wire_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bytes:
    if isinstance(ip, ipaddress.IPv4Address):
        return b"\x00" * 10 + b"\xff\xff" + ip.packed
    if ip.ipv4_mapped is not None:
        return b"\x00" * 10 + b"\xff\xff" + ip.ipv4_mapped.packed
    return ip.packed


def encode_addr(addresses: list[PeerAddress]) -> bytes:
    """Encode a bounded addr payload (time, services, 16-byte IP, big-endian port)."""
    if not isinstance(addresses, list):
        raise TypeError("addresses must be a list")
    if len(addresses) > MAX_ADDRESSES_PER_MESSAGE:
        raise ValueError("address count exceeds configured limit")
    chunks = [_compact_size(len(addresses))]
    for address in addresses:
        if not isinstance(address, PeerAddress):
            raise TypeError("every address must be a PeerAddress")
        chunks.append(struct.pack("<IQ", address.timestamp, address.services))
        chunks.append(_wire_ip(address.ip))
        chunks.append(struct.pack(">H", address.port))
    return b"".join(chunks)


def decode_addr(payload: bytes) -> list[PeerAddress]:
    """Decode one canonical, bounded addr payload and reject trailing bytes."""
    if not isinstance(payload, bytes):
        raise TypeError("address payload must be bytes")
    count, offset = _read_compact_size(payload, 0)
    if count > MAX_ADDRESSES_PER_MESSAGE:
        raise ValueError("address count exceeds configured limit")
    record_size = 30
    expected = offset + count * record_size
    if len(payload) < expected:
        raise ValueError("truncated address entry")
    if len(payload) > expected:
        raise ValueError("trailing bytes after address entries")
    addresses = []
    for _ in range(count):
        timestamp, services = struct.unpack_from("<IQ", payload, offset)
        offset += 12
        raw_ip = payload[offset:offset + 16]
        offset += 16
        port = struct.unpack_from(">H", payload, offset)[0]
        offset += 2
        ip = ipaddress.ip_address(raw_ip)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        addresses.append(PeerAddress(timestamp, services, ip, port))
    return addresses


def encode_getaddr() -> bytes:
    """The getaddr request has an empty payload."""
    return b""


def decode_getaddr(payload: bytes) -> None:
    """Validate the empty getaddr payload."""
    if payload != b"":
        raise ValueError("getaddr payload must be empty")
