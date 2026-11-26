"""In-memory BLACKROOT header DAG prototype.

This module validates header linkage, proof of work, canonical compact targets,
parent median-time-past, fixed 2016-block difficulty retargets, and cumulative-
work branch selection. Non-genesis headers require an explicit network-adjusted
time unless the caller opts into the clearly named test-only unchecked mode.

This is not production consensus: it does not validate block bodies, scripts,
UTXOs, or persistent branch state, and it does not itself obtain or require a
trusted network-adjusted clock.
"""
from __future__ import annotations

from dataclasses import dataclass

from .blackroot_consensus import (DIFFICULTY_INTERVAL, TARGET_SPACING, block_work, check_proof_of_work, decode_compact_target, encode_compact_target, format_hash, retarget_compact, serialize_header, sha256d)

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

    def __init__(
        self, pow_limit: int, genesis: BlockHeader, *,
        allow_unchecked_time_for_tests: bool = False,
    ):
        if not isinstance(allow_unchecked_time_for_tests, bool):
            raise TypeError("allow_unchecked_time_for_tests must be a boolean")
        if not isinstance(pow_limit, int) or isinstance(pow_limit, bool) or pow_limit <= 0:
            raise ValueError("pow_limit must be a positive integer")
        if not isinstance(genesis, BlockHeader) or genesis.prev_hash != ZERO_HASH:
            raise ValueError("genesis previous hash must be all zeroes")
        self.pow_limit = pow_limit
        self.allow_unchecked_time_for_tests = allow_unchecked_time_for_tests
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

    @property
    def nodes(self) -> tuple[HeaderNode, ...]:
        """Return an immutable, deterministic snapshot of every known DAG node."""
        return tuple(sorted(
            self._nodes.values(),
            key=lambda node: (node.height, node.header.hash),
        ))

    def median_time_past(self, parent_hash: bytes) -> int:
        """Return the median timestamp of up to 11 ancestors ending at parent."""
        if parent_hash not in self._nodes:
            raise ValueError("unknown parent header")
        times = []
        current = parent_hash
        while current != ZERO_HASH and len(times) < 11:
            node = self._nodes[current]
            times.append(node.header.timestamp)
            current = node.parent_hash
        times.sort()
        return times[len(times) // 2]

    def _ancestor_hash(self, tip_hash: bytes, height: int) -> bytes:
        node = self._nodes.get(tip_hash)
        if node is None or not 0 <= height <= node.height:
            raise ValueError("requested ancestor height is out of range")
        current = tip_hash
        while self._nodes[current].height > height:
            current = self._nodes[current].parent_hash
        return current

    def expected_bits(self, parent_hash: bytes, candidate_height: int) -> int:
        """Return required nBits using fixed 2016-block retarget intervals."""
        parent = self._nodes.get(parent_hash)
        if parent is None:
            raise ValueError("unknown parent header")
        if candidate_height != parent.height + 1:
            raise ValueError("candidate height must follow parent")
        if candidate_height % DIFFICULTY_INTERVAL != 0:
            return parent.header.bits

        first_height = candidate_height - DIFFICULTY_INTERVAL
        first_hash = self._ancestor_hash(parent_hash, first_height)
        first_timestamp = self._nodes[first_hash].header.timestamp
        actual_timespan = parent.header.timestamp - first_timestamp
        if actual_timespan <= 0:
            actual_timespan = 1
        return retarget_compact(
            parent.header.bits,
            actual_timespan,
            self.pow_limit,
            TARGET_SPACING * DIFFICULTY_INTERVAL,
        )

    def add(self, header: BlockHeader) -> str:
        if header.prev_hash != self.best_hash:
            raise ValueError("header does not extend current tip")
        return self.add_to_branch(header)

    def add_to_branch(
        self, header: BlockHeader, *, adjusted_time: int | None = None,
        max_future_seconds: int = 7_200,
    ) -> str:
        if not isinstance(header, BlockHeader):
            raise TypeError("header must be a BlockHeader")
        if not isinstance(max_future_seconds, int) or isinstance(max_future_seconds, bool) or max_future_seconds < 0:
            raise ValueError("max_future_seconds must be a non-negative integer")
        is_genesis = header.prev_hash == ZERO_HASH
        if adjusted_time is None:
            if not is_genesis and not self.allow_unchecked_time_for_tests:
                raise ValueError("adjusted_time is required for non-genesis headers")
        else:
            if not isinstance(adjusted_time, int) or isinstance(adjusted_time, bool) or adjusted_time < 0:
                raise ValueError("adjusted_time must be a non-negative integer")
            if header.timestamp > adjusted_time + max_future_seconds:
                raise ValueError("header timestamp exceeds network-adjusted future-time limit")
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
            if header.timestamp <= self.median_time_past(header.prev_hash):
                raise ValueError("timestamp must be greater than median-time-past")
        target = decode_compact_target(header.bits)
        if encode_compact_target(target) != header.bits:
            raise ValueError("non-canonical compact target encoding")
        if target > self.pow_limit:
            raise ValueError("target exceeds network proof-of-work limit")
        if header.prev_hash != ZERO_HASH:
            required_bits = self.expected_bits(header.prev_hash, height)
            if header.bits != required_bits:
                raise ValueError("incorrect proof-of-work difficulty bits")
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

    def add_batch(
        self, headers: list[BlockHeader], *, adjusted_time: int | None = None,
        max_future_seconds: int = 7_200,
    ) -> list[str]:
        """Validate and add a contiguous header batch atomically.

        If any header fails validation, the in-memory DAG and best tip are
        restored to their exact pre-call state.
        """
        if not isinstance(headers, list):
            raise TypeError("headers must be a list")
        original_nodes = self._nodes.copy()
        original_best_hash = self._best_hash
        accepted = []
        try:
            for header in headers:
                accepted.append(self.add_to_branch(
                    header, adjusted_time=adjusted_time,
                    max_future_seconds=max_future_seconds,
                ))
        except Exception:
            self._nodes = original_nodes
            self._best_hash = original_best_hash
            raise
        return accepted

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
