"""Explicit, local-development-only testnet configuration boundary.

No network constants are selected here. Callers must supply and review every
chain identity and genesis parameter. This is configuration plumbing, not a
normative protocol specification or a production node launcher.
"""
from __future__ import annotations

import ipaddress
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .blackroot_chain import BlockHeader, ZERO_HASH
from .blackroot_consensus import check_proof_of_work, decode_compact_target
from .blackroot_p2p import DEFAULT_MAX_PAYLOAD
from .blackroot_p2p_handshake import VersionMessage
from .blackroot_p2p_manager import PeerManager


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_float(value: str):
    raise ValueError(f"floating-point JSON value is forbidden: {value}")


def _decode_lower_hex(value: object, field: str, length: int) -> bytes:
    if (not isinstance(value, str) or len(value) != length
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"{field} must be exactly {length} lowercase hex characters")
    return bytes.fromhex(value)


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
        if self.network_id != self.network_id.strip() or not self.network_id.isprintable():
            raise ValueError("network_id must be canonical printable text without surrounding whitespace")
        if self.network_id.strip().lower() in {"main", "mainnet", "bitcoin", "production"}:
            raise ValueError("testnet configuration cannot use a production network name")
        if not isinstance(self.message_magic, bytes) or len(self.message_magic) != 4:
            raise ValueError("message_magic must be exactly four bytes")
        if self.message_magic == bytes(4):
            raise ValueError("all-zero message_magic is not permitted")
        if (not isinstance(self.protocol_version, int)
                or isinstance(self.protocol_version, bool)
                or not 1 <= self.protocol_version <= 0x7FFFFFFF):
            raise ValueError("protocol_version must be a positive int32")
        if not isinstance(self.genesis_header, BlockHeader):
            raise TypeError("genesis_header must be a BlockHeader")
        if self.genesis_header.prev_hash != ZERO_HASH:
            raise ValueError("configured genesis header must have a null previous hash")
        if not isinstance(self.genesis_hash, bytes) or len(self.genesis_hash) != 32:
            raise ValueError("genesis_hash must be exactly 32 raw bytes")
        if self.genesis_header.hash != self.genesis_hash:
            raise ValueError("genesis_hash does not match the configured genesis header")
        if (not isinstance(self.pow_limit, int)
                or isinstance(self.pow_limit, bool)
                or not 0 < self.pow_limit < 1 << 256):
            raise ValueError("pow_limit must be a positive uint256")
        target = decode_compact_target(self.genesis_header.bits)
        if target > self.pow_limit:
            raise ValueError("genesis target exceeds configured proof-of-work limit")
        if not check_proof_of_work(self.genesis_header.serialize(), self.genesis_header.bits, self.pow_limit):
            raise ValueError("configured genesis header does not satisfy proof of work")
        if not isinstance(self.p2p_port, int) or isinstance(self.p2p_port, bool) or not 0 <= self.p2p_port <= 65535:
            raise ValueError("p2p_port must be between 0 and 65535")
        if not isinstance(self.max_peers, int) or isinstance(self.max_peers, bool) or self.max_peers < 1:
            raise ValueError("max_peers must be a positive integer")
        if (not isinstance(self.max_payload, int)
                or isinstance(self.max_payload, bool)
                or not 1 <= self.max_payload <= DEFAULT_MAX_PAYLOAD):
            raise ValueError("max_payload must be within the P2P implementation limit")

    @classmethod
    def from_json_file(cls, path: str | Path) -> "TestnetConfig":
        """Load a strict JSON config; unknown/missing fields fail closed."""
        try:
            raw = json.loads(
                Path(path).read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_float=_reject_json_float,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"invalid JSON constant: {value}")
                ),
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read testnet config: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("testnet config root must be a JSON object")
        required = {
            "network_id", "message_magic", "protocol_version",
            "genesis_header", "genesis_hash", "pow_limit",
            "p2p_port", "max_peers",
        }
        allowed = required | {"max_payload"}
        missing = required - raw.keys()
        unknown = raw.keys() - allowed
        if missing:
            raise ValueError(f"missing testnet config fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"unknown testnet config fields: {', '.join(sorted(unknown))}")
        header = raw["genesis_header"]
        if not isinstance(header, dict) or set(header) != {
            "version", "prev_hash", "merkle_root", "timestamp", "bits", "nonce"
        }:
            raise ValueError("genesis_header must contain exactly version, prev_hash, merkle_root, timestamp, bits, nonce")
        try:
            for field in ("version", "timestamp", "bits", "nonce"):
                value = header[field]
                if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
                    raise ValueError(
                        f"genesis_header.{field} must be a uint32 integer"
                    )
            genesis_header = BlockHeader(
                version=header["version"],
                prev_hash=_decode_lower_hex(header["prev_hash"], "genesis_header.prev_hash", 64),
                merkle_root=_decode_lower_hex(header["merkle_root"], "genesis_header.merkle_root", 64),
                timestamp=header["timestamp"],
                bits=header["bits"],
                nonce=header["nonce"],
            )
            magic = _decode_lower_hex(raw["message_magic"], "message_magic", 8)
            genesis_hash = _decode_lower_hex(raw["genesis_hash"], "genesis_hash", 64)
            if isinstance(raw["pow_limit"], str):
                encoded_limit = raw["pow_limit"]
                if (not encoded_limit.startswith("0x")
                        or len(encoded_limit) <= 2
                        or any(char not in "0123456789abcdef" for char in encoded_limit[2:])):
                    raise ValueError("pow_limit must use canonical lowercase 0x hexadecimal")
                pow_limit = int(encoded_limit, 16)
                if hex(pow_limit) != encoded_limit:
                    raise ValueError("pow_limit must use canonical lowercase 0x hexadecimal")
            else:
                pow_limit = raw["pow_limit"]
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid hex or numeric testnet config field: {exc}") from exc
        return cls(
            network_id=raw["network_id"],
            message_magic=magic,
            protocol_version=raw["protocol_version"],
            genesis_header=genesis_header,
            genesis_hash=genesis_hash,
            pow_limit=pow_limit,
            p2p_port=raw["p2p_port"],
            max_peers=raw["max_peers"],
            max_payload=raw.get("max_payload", DEFAULT_MAX_PAYLOAD),
        )

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
            network_id=hashlib.sha256(self.network_id.encode("utf-8")).digest(),
            genesis_hash=self.genesis_hash,
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
