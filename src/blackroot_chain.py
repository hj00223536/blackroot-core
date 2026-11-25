"""In-memory BLACKROOT header-chain prototype.

This is educational scaffolding, not production consensus. It validates only
header linkage, proof of work, and strictly increasing timestamps. It does not
validate transactions, UTXO state, cumulative chainwork, retargets, median-time
past, future-time limits, or reorganization safety.
"""
from __future__ import annotations

from dataclasses import dataclass

from .blackroot_consensus import (
    block_work,
    check_proof_of_work,
    decode_compact_target,
    format_hash,
    serialize_header,
    sha256d,
)

ZERO_HASH = bytes(32)


@dataclass(frozen=True)
class BlockHeader:
    version: int
    prev_hash: bytes
    merkle_root: bytes
    timestamp: int
    bits: int
    nonce: int

    def serialize(self) -> bytes:
        return serialize_header(
            self.version,
            self.prev_hash,
            self.merkle_root,
            self.timestamp,
            self.bits,
            self.nonce,
        )

    @property
    def hash(self) -> bytes:
        return sha256d(self.serialize())

    @property
    def display_hash(self) -> str:
        return format_hash(self.hash)


class HeaderChain:
    """Minimal in-memory linked-header prototype for local tests only."""

    def __init__(self, pow_limit: int, genesis: BlockHeader):
        if not isinstance(pow_limit, int) or isinstance(pow_limit, bool) or pow_limit <= 0:
            raise ValueError("pow_limit must be a positive integer")
        if genesis.prev_hash != ZERO_HASH:
            raise ValueError("genesis previous hash must be all zeroes")
        self.pow_limit = pow_limit
        self._headers: list[BlockHeader] = []
        self._chainwork = 0
        self.add(genesis)

    @property
    def height(self) -> int:
        return len(self._headers) - 1

    @property
    def tip(self) -> BlockHeader:
        return self._headers[-1]

    @property
    def chainwork(self) -> int:
        """Cumulative work for headers accepted by this prototype."""
        return self._chainwork

    def get(self, height: int) -> BlockHeader:
        return self._headers[height]

    def add(self, header: BlockHeader) -> str:
        if not isinstance(header, BlockHeader):
            raise TypeError("header must be a BlockHeader")
        if self._headers:
            if header.prev_hash != self.tip.hash:
                raise ValueError("header does not extend current tip")
            if header.timestamp <= self.tip.timestamp:
                raise ValueError("timestamp must be greater than previous header")
        target = decode_compact_target(header.bits)
        if target > self.pow_limit:
            raise ValueError("target exceeds network proof-of-work limit")
        if not check_proof_of_work(header.serialize(), header.bits, self.pow_limit):
            raise ValueError("insufficient proof of work")
        self._headers.append(header)
        self._chainwork += block_work(target)
        return header.display_hash
