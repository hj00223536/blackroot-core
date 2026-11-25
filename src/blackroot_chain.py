"""In-memory BLACKROOT header DAG prototype.

Not production consensus: timestamp rules omit MTP/future-time checks, and no
block bodies, scripts, UTXOs, retarget schedule or persistent branch index are
validated here.
"""
from __future__ import annotations

from dataclasses import dataclass

from .blackroot_consensus import block_work, check_proof_of_work, decode_compact_target, format_hash, serialize_header, sha256d

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
        return serialize_header(self.version, self.prev_hash, self.merkle_root,
                                self.timestamp, self.bits, self.nonce)

    @property
    def hash(self) -> bytes:
        return sha256d(self.serialize())

    @property
    def display_hash(self) -> str:
        return format_hash(self.hash)


@dataclass(frozen=True)
class HeaderNode:
    header: BlockHeader
    height: int
    chainwork: int
    parent_hash: bytes


class HeaderChain:
    """Header DAG selecting the greatest cumulative-work branch."""

    def __init__(self, pow_limit: int, genesis: BlockHeader):
        if not isinstance(pow_limit, int) or isinstance(pow_limit, bool) or pow_limit <= 0:
            raise ValueError("pow_limit must be a positive integer")
        if not isinstance(genesis, BlockHeader) or genesis.prev_hash != ZERO_HASH:
            raise ValueError("genesis previous hash must be all zeroes")
        self.pow_limit = pow_limit
        self._nodes: dict[bytes, HeaderNode] = {}
        self._best_hash: bytes | None = None
        self.add_to_branch(genesis)

    @property
    def height(self) -> int:
        return self._nodes[self._best_hash].height

    @property
    def tip(self) -> BlockHeader:
        return self._nodes[self._best_hash].header

    @property
    def chainwork(self) -> int:
        return self._nodes[self._best_hash].chainwork

    @property
    def best_hash(self) -> bytes:
        return self._best_hash

    def get(self, height: int) -> BlockHeader:
        if not isinstance(height, int) or isinstance(height, bool) or height < 0:
            raise ValueError("height must be a non-negative integer")
        path = self.best_chain()
        if height >= len(path):
            raise IndexError("height is above best-chain tip")
        return path[height]

    def node(self, block_hash: bytes) -> HeaderNode | None:
        return self._nodes.get(block_hash)

    def add(self, header: BlockHeader) -> str:
        if header.prev_hash != self.best_hash:
            raise ValueError("header does not extend current tip")
        return self.add_to_branch(header)

    def add_to_branch(self, header: BlockHeader) -> str:
        if not isinstance(header, BlockHeader):
            raise TypeError("header must be a BlockHeader")
        block_hash = header.hash
        if block_hash in self._nodes:
            raise ValueError("duplicate header")
        if header.prev_hash == ZERO_HASH:
            if self._nodes:
                raise ValueError("additional genesis header is not allowed")
            height, parent_work = 0, 0
        else:
            parent = self._nodes.get(header.prev_hash)
            if parent is None:
                raise ValueError("unknown parent header")
            height, parent_work = parent.height + 1, parent.chainwork
            if header.timestamp <= parent.header.timestamp:
                raise ValueError("timestamp must be greater than previous header")
        target = decode_compact_target(header.bits)
        if target > self.pow_limit:
            raise ValueError("target exceeds network proof-of-work limit")
        if not check_proof_of_work(header.serialize(), header.bits, self.pow_limit):
            raise ValueError("insufficient proof of work")
        node = HeaderNode(header, height, parent_work + block_work(target), header.prev_hash)
        self._nodes[block_hash] = node
        if self._best_hash is None:
            self._best_hash = block_hash
        else:
            best_work = self._nodes[self._best_hash].chainwork
            if node.chainwork > best_work or (
                node.chainwork == best_work and block_hash < self._best_hash
            ):
                self._best_hash = block_hash
        return header.display_hash

    def _path_hashes(self, tip_hash: bytes) -> list[bytes]:
        if tip_hash not in self._nodes:
            raise ValueError("unknown tip hash")
        result = []
        current = tip_hash
        while current != ZERO_HASH:
            result.append(current)
            current = self._nodes[current].parent_hash
        result.reverse()
        return result

    def best_chain(self) -> list[BlockHeader]:
        return [self._nodes[h].header for h in self._path_hashes(self.best_hash)]

    def reorganization(self, old_tip_hash: bytes) -> tuple[list[BlockHeader], list[BlockHeader]]:
        """Return headers to disconnect (tip-first) and connect (fork-first)."""
        old_path = self._path_hashes(old_tip_hash)
        new_path = self._path_hashes(self.best_hash)
        common = 0
        while common < min(len(old_path), len(new_path)) and old_path[common] == new_path[common]:
            common += 1
        disconnect = [self._nodes[h].header for h in reversed(old_path[common:])]
        connect = [self._nodes[h].header for h in new_path[common:]]
        return disconnect, connect
