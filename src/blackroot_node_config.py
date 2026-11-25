"""Explicit, local-development-only testnet configuration boundary.

No network constants are selected here. Callers must supply and review every
chain identity and genesis parameter. This is configuration plumbing, not a
normative protocol specification or a production node launcher.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .blackroot_chain import BlockHeader, ZERO_HASH
from .blackroot_consensus import check_proof_of_work, decode_compact_target
from .blackroot_p2p import DEFAULT_MAX_PAYLOAD
from .blackroot_p2p_handshake import VersionMessage
from .blackroot_p2p_manager import PeerManager


@dataclass(frozen=True)
class TestnetConfig:
    """A fully explicit testnet identity and bounded local P2P configuration."""

    network_id: str
    message_magic: bytes
    protocol_version: int
    genesis_header: BlockHeader
    genesis_hash: bytes
    pow_limit: int
    p2p_port: int
    max_peers: int
    max_payload: int = DEFAULT_MAX_PAYLOAD

    def __post_init__(self) -> None:
        if not isinstance(self.network_id, str) or not self.network_id.strip():
            raise ValueError("network_id must be non-empty")
        if self.network_id.strip().lower() in {"main", "mainnet", "bitcoin", "production"}:
            raise ValueError("testnet configuration cannot use a production network name")
        if not isinstance(self.message_magic, bytes) or len(self.message_magic) != 4:
            raise ValueError("message_magic must be exactly four bytes")
        if self.message_magic == bytes(4):
            raise ValueError("all-zero message_magic is not permitted")
        if not isinstance(self.protocol_version, int) or isinstance(self.protocol_version, bool) or self.protocol_version < 1:
            raise ValueError("protocol_version must be a positive integer")
        if not isinstance(self.genesis_header, BlockHeader):
            raise TypeError("genesis_header must be a BlockHeader")
        if self.genesis_header.prev_hash != ZERO_HASH:
            raise ValueError("configured genesis header must have a null previous hash")
        if not isinstance(self.genesis_hash, bytes) or len(self.genesis_hash) != 32:
            raise ValueError("genesis_hash must be exactly 32 raw bytes")
        if self.genesis_header.hash != self.genesis_hash:
            raise ValueError("genesis_hash does not match the configured genesis header")
        if not isinstance(self.pow_limit, int) or isinstance(self.pow_limit, bool) or self.pow_limit <= 0:
            raise ValueError("pow_limit must be a positive integer")
        target = decode_compact_target(self.genesis_header.bits)
        if target > self.pow_limit:
            raise ValueError("genesis target exceeds configured proof-of-work limit")
        if not check_proof_of_work(self.genesis_header.serialize(), self.genesis_header.bits, self.pow_limit):
            raise ValueError("configured genesis header does not satisfy proof of work")
        if not isinstance(self.p2p_port, int) or isinstance(self.p2p_port, bool) or not 0 <= self.p2p_port <= 65535:
            raise ValueError("p2p_port must be between 0 and 65535")
        if not isinstance(self.max_peers, int) or isinstance(self.max_peers, bool) or self.max_peers < 1:
            raise ValueError("max_peers must be a positive integer")
        if not isinstance(self.max_payload, int) or isinstance(self.max_payload, bool) or not 1 <= self.max_payload <= 0xFFFFFFFF:
            raise ValueError("max_payload must be between 1 and uint32 max")

    def create_peer_manager(
        self,
        local_version: VersionMessage,
        *,
        handshake_timeout: float = 10.0,
        idle_timeout: float = 120.0,
    ) -> PeerManager:
        """Create a peer manager bound to this exact magic/version identity."""
        if not isinstance(local_version, VersionMessage):
            raise TypeError("local_version must be a VersionMessage")
        if local_version.protocol_version != self.protocol_version:
            raise ValueError("local version does not match configured testnet protocol")
        return PeerManager(
            magic=self.message_magic,
            local_version=local_version,
            max_peers=self.max_peers,
            max_payload=self.max_payload,
            handshake_timeout=handshake_timeout,
            idle_timeout=idle_timeout,
            min_protocol_version=self.protocol_version,
        )

    def validate_bind_host(self, host: str) -> str:
        """Reject public listener addresses; this prototype permits loopback only."""
        if not isinstance(host, str) or not host:
            raise ValueError("bind host must be non-empty text")
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("bind host must be a literal loopback IP address") from exc
        if not address.is_loopback:
            raise ValueError("testnet prototype listener may bind only to loopback")
        return host
