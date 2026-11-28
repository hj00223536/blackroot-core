"""Version-2 P2P identity envelope for BLACKROOT.

The envelope binds the legacy version fields to the locally configured network
and genesis identity. It is a network-mismatch guard, not cryptographic peer
authentication or Sybil resistance.
"""
from __future__ import annotations

from dataclasses import dataclass

from .blackroot_p2p_handshake import VersionMessage, decode_version, encode_version

WIRE_VERSION = 2
_MAGIC = b"BRP2"
_IDENTITY_SIZE = 32
_PREFIX_SIZE = len(_MAGIC) + 2 * _IDENTITY_SIZE


@dataclass(frozen=True)
class Version2Message:
    network_id: bytes
    genesis_hash: bytes
    version: VersionMessage

    def __post_init__(self) -> None:
        if not isinstance(self.network_id, bytes) or len(self.network_id) != _IDENTITY_SIZE:
            raise ValueError("network_id must be exactly 32 bytes")
        if not isinstance(self.genesis_hash, bytes) or len(self.genesis_hash) != _IDENTITY_SIZE:
            raise ValueError("genesis_hash must be exactly 32 bytes")
        if not isinstance(self.version, VersionMessage):
            raise TypeError("version must be a VersionMessage")


def encode_version2(message: Version2Message) -> bytes:
    if not isinstance(message, Version2Message):
        raise TypeError("message must be a Version2Message")
    return _MAGIC + message.network_id + message.genesis_hash + encode_version(message.version)


def decode_version2(payload: bytes) -> Version2Message:
    if not isinstance(payload, bytes):
        raise TypeError("version-2 payload must be bytes")
    if len(payload) < _PREFIX_SIZE:
        raise ValueError("truncated version-2 identity envelope")
    if payload[:len(_MAGIC)] != _MAGIC:
        raise ValueError("invalid version-2 envelope marker")
    network_id = payload[4:36]
    genesis_hash = payload[36:68]
    version = decode_version(payload[68:])
    return Version2Message(network_id, genesis_hash, version)
