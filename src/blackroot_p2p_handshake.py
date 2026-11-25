"""Strict version-handshake payload codec for the BLACKROOT P2P prototype.

This module encodes/decodes handshake payloads only. It does not establish
connections, authenticate peers, prevent Sybil attacks, or negotiate consensus.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAX_USER_AGENT_BYTES = 256
_VERSION_STRUCT = struct.Struct("<iQqQi")


@dataclass(frozen=True)
class VersionMessage:
    protocol_version: int
    services: int
    timestamp: int
    nonce: int
    start_height: int
    user_agent: str

    def __post_init__(self) -> None:
        if not 0 < self.protocol_version <= 0x7FFFFFFF:
            raise ValueError("protocol version must be a positive int32")
        if not 0 <= self.services <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("services must fit uint64")
        if not -(1 << 63) <= self.timestamp < (1 << 63):
            raise ValueError("timestamp must fit int64")
        if not 0 <= self.nonce <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("nonce must fit uint64")
        if not 0 <= self.start_height <= 0x7FFFFFFF:
            raise ValueError("start height must be a non-negative int32")
        if not isinstance(self.user_agent, str):
            raise TypeError("user agent must be text")
        encoded = self.user_agent.encode("utf-8")
        if len(encoded) > MAX_USER_AGENT_BYTES:
            raise ValueError("user agent exceeds configured byte limit")
        if any(byte < 0x20 or byte == 0x7F for byte in encoded):
            raise ValueError("user agent contains control characters")


def encode_version(message: VersionMessage) -> bytes:
    """Encode a fixed-field version payload plus a bounded UTF-8 user agent."""
    if not isinstance(message, VersionMessage):
        raise TypeError("message must be a VersionMessage")
    user_agent = message.user_agent.encode("utf-8")
    return _VERSION_STRUCT.pack(
        message.protocol_version,
        message.services,
        message.timestamp,
        message.nonce,
        message.start_height,
    ) + struct.pack("<H", len(user_agent)) + user_agent


def decode_version(payload: bytes) -> VersionMessage:
    """Decode exactly one canonical version payload."""
    if not isinstance(payload, bytes):
        raise TypeError("version payload must be bytes")
    fixed_size = _VERSION_STRUCT.size
    if len(payload) < fixed_size + 2:
        raise ValueError("truncated version payload")
    protocol_version, services, timestamp, nonce, start_height = _VERSION_STRUCT.unpack_from(payload)
    user_agent_length = struct.unpack_from("<H", payload, fixed_size)[0]
    if user_agent_length > MAX_USER_AGENT_BYTES:
        raise ValueError("user agent exceeds configured byte limit")
    expected_size = fixed_size + 2 + user_agent_length
    if len(payload) != expected_size:
        raise ValueError("version payload length mismatch")
    try:
        user_agent = payload[fixed_size + 2:].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("user agent is not valid UTF-8") from exc
    return VersionMessage(
        protocol_version=protocol_version,
        services=services,
        timestamp=timestamp,
        nonce=nonce,
        start_height=start_height,
        user_agent=user_agent,
    )
