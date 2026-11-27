"""Download missing best-fork bodies and activate the HeaderChain-selected best branch.

Headers are assumed to have passed HeaderChain validation already. Bodies are
requested from connected peers, checked against their exact header and Merkle
commitment, archived, and only then handed to UTXOStore's atomic reorganization
path. This component does not discover headers or provide production consensus.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
import time

from .blackroot_blocks import Block
from .blackroot_chain import HeaderChain
from .blackroot_p2p_inventory import INV_TYPE_BLOCK, InventoryVector, decode_inventory, encode_inventory
from .blackroot_p2p_request_pool import MultiPeerBlockRequestPool
from .blackroot_transactions import merkle_root


class MultiPeerReorganizationSync:
    def __init__(self, chain: HeaderChain, store, *, request_pool=None, require_node_state_lifecycle: bool = False) -> None:
        if not isinstance(require_node_state_lifecycle, bool):
            raise TypeError("require_node_state_lifecycle must be a bool")
        if require_node_state_lifecycle and getattr(store, "_blackroot_node_state_lifecycle", False) is not True:
            raise ValueError("persistent-node fork sync requires a node-state lifecycle adapter")
        if not isinstance(chain, HeaderChain):
            raise TypeError("chain must be a HeaderChain")
        if not callable(getattr(store, "tip", None)):
            raise TypeError("store must provide tip")
        if not callable(getattr(store, "store_block_body", None)):
            raise TypeError("store must provide store_block_body")
        if not callable(getattr(store, "load_block_body", None)):
            raise TypeError("store must provide load_block_body")
        if not callable(getattr(store, "reorganize_to_best", None)):
            raise TypeError("store must provide reorganize_to_best")
        self.chain = chain
        self.store = store
        self.pool = request_pool or MultiPeerBlockRequestPool()
        self._requested_at: dict[bytes, float] = {}
        self._tried_peers: dict[bytes, set[object]] = {}

    def missing_best_branch_bodies(self) -> tuple[bytes, ...]:
        active = self.store.tip()
        if active is None:
            raise ValueError("cannot sync a fork before the UTXO chain is initialized")
        height, active_hash = active
        active_node = self.chain.node(active_hash)
        best_node = self.chain.node(self.chain.best_hash)
        if active_node is None or active_node.height != height:
            raise ValueError("active UTXO tip is inconsistent with header DAG")
        if best_node is None or best_node.chainwork < active_node.chainwork or best_node.header.hash == active_hash:
            return ()
        _disconnect, connect = self.chain.reorganization(active_hash)
        return tuple(
            header.hash for header in connect
            if self.store.load_block_body(header.hash) is None
        )

    def _activate_if_complete(self):
        """Activate an already-complete selected branch without waiting for another body."""
        active = self.store.tip()
        if active is None:
            return None
        active_node = self.chain.node(active[1])
        best_node = self.chain.node(self.chain.best_hash)
        if active_node is None or active_node.height != active[0]:
            raise ValueError("active UTXO tip is inconsistent with header DAG")
        if best_node is None or best_node.chainwork < active_node.chainwork:
            return None
        if best_node.header.hash == active[1]:
            return None
        if self.missing_best_branch_bodies():
            return None
        _disconnect, connect = self.chain.reorganization(active[1])
        if not connect:
            return None
        try:
            return self.store.reorganize_to_best(self.chain)
        except ValueError:
            # A merkle-valid body can still fail transaction, script, or
            # reward validation. Do not leave rejected branch bodies archived.
            self.store.discard_block_bodies(tuple(header.hash for header in connect))
            raise

    def _available_peers(self, block_hash: bytes, peers: Mapping[object, object]) -> list[object]:
        connected = [peer_id for peer_id, peer in peers.items()
                     if getattr(peer, "connected", False)]
        tried = self._tried_peers.get(block_hash, set())
        return [peer_id for peer_id in connected if peer_id not in tried]

    async def request_missing_bodies(self, peers: Mapping[object, object]) -> dict[bytes, object]:
        """Request all currently missing bodies; return hash-to-peer assignments."""
        requested = {}
        missing = self.missing_best_branch_bodies()
        wanted = set(missing)
        # Header selection can change while old fork requests are outstanding.
        # Release work that no longer belongs to the selected best branch so
        # obsolete downloads cannot consume the bounded global/per-peer budget.
        for tracked_hash in set(self._requested_at) | set(self._tried_peers):
            if tracked_hash not in wanted:
                self._requested_at.pop(tracked_hash, None)
                self._tried_peers.pop(tracked_hash, None)
        for pending_hash in self.pool.pending_hashes:
            if pending_hash not in wanted:
                self.pool.cancel(pending_hash)
                self._requested_at.pop(pending_hash, None)
        for block_hash in missing:
            # Header announcements and inventory messages can both trigger
            # this method. Keep the shared pool idempotent instead of assigning
            # the same body twice.
            if self.pool.assigned_peer(block_hash) is not None:
                continue
            available = self._available_peers(block_hash, peers)
            if not available:
                continue
            peer_id = self.pool.assign(block_hash, available)
            try:
                await peers[peer_id].send(
                    "getdata",
                    encode_inventory([InventoryVector(INV_TYPE_BLOCK, block_hash)]),
                )
            except Exception:
                self._tried_peers.setdefault(block_hash, set()).add(peer_id)
                self.pool.cancel(block_hash)
                self._requested_at[block_hash] = time.monotonic()
                raise
            self._requested_at[block_hash] = time.monotonic()
            requested[block_hash] = peer_id
        # The complete best branch may already be archived (for example after
        # header selection changes). In that case there is no body response to
        # trigger activation, so perform the same guarded activation here.
        self._activate_if_complete()
        return requested

    def accept_block(self, peer_id: object, payload: bytes):
        """Archive an assigned fork body and activate the branch when complete."""
        if not isinstance(payload, bytes):
            raise TypeError("block payload must be bytes")
        block = Block.deserialize(payload)
        block_hash = block.header.hash
        if self.pool.assigned_peer(block_hash) != peer_id:
            raise ValueError("fork block came from an unassigned peer")
        try:
            node = self.chain.node(block_hash)
            if node is None or node.header.serialize() != block.header.serialize():
                raise ValueError("fork block header is not in the validated header DAG")
            if merkle_root(tx.txid for tx in block.transactions) != block.header.merkle_root:
                raise ValueError("fork block Merkle root mismatch")
            self.store.store_block_body(block)
            if not self.pool.complete(block_hash, peer_id):
                raise RuntimeError("fork body assignment disappeared during acceptance")
        except Exception:
            # Invalid or unpersistable responses must not pin the request slot.
            # The caller may disconnect the peer; another peer can then retry.
            self._tried_peers.setdefault(block_hash, set()).add(peer_id)
            self.pool.cancel(block_hash)
            self._requested_at[block_hash] = time.monotonic()
            raise
        self._requested_at.pop(block_hash, None)
        self._tried_peers.pop(block_hash, None)
        return self._activate_if_complete()

    def expire_requests(self, timeout: float, *, now: float | None = None) -> tuple[bytes, ...]:
        """Release body requests older than timeout, using a monotonic clock."""
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be a positive number")
        current = time.monotonic() if now is None else now
        if (not isinstance(current, (int, float)) or isinstance(current, bool)
                or not math.isfinite(current)):
            raise ValueError("now must be a finite monotonic timestamp")
        expired = tuple(
            block_hash for block_hash, requested_at in self._requested_at.items()
            if current - requested_at >= timeout
        )
        for block_hash in expired:
            self._requested_at.pop(block_hash, None)
            self.pool.cancel(block_hash)
        return expired

    async def retry_expired_requests(
        self, peers: Mapping[object, object], timeout: float, *, now: float | None = None
    ) -> dict[bytes, object]:
        """Reassign timed-out fork bodies to currently connected peers."""
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be a positive number")
        current = time.monotonic() if now is None else now
        if (not isinstance(current, (int, float)) or isinstance(current, bool)
                or not math.isfinite(current)):
            raise ValueError("now must be a finite monotonic timestamp")
        expiring_peers = {
            block_hash: self.pool.assigned_peer(block_hash)
            for block_hash, requested_at in self._requested_at.items()
            if current - requested_at >= timeout
        }
        expired = self.expire_requests(timeout, now=current)
        retried = {}
        for block_hash in expired:
            previous_peer = expiring_peers.get(block_hash)
            if previous_peer is not None:
                self._tried_peers.setdefault(block_hash, set()).add(previous_peer)
            available = self._available_peers(block_hash, peers)
            if not available:
                # Keep the timed-out request eligible for a later timer tick.
                self._requested_at[block_hash] = current
                continue
            peer_id = self.pool.assign(block_hash, available)
            try:
                await peers[peer_id].send(
                    "getdata",
                    encode_inventory([InventoryVector(INV_TYPE_BLOCK, block_hash)]),
                )
            except Exception:
                self._tried_peers.setdefault(block_hash, set()).add(peer_id)
                self.pool.cancel(block_hash)
                self._requested_at[block_hash] = current
                raise
            self._requested_at[block_hash] = current
            retried[block_hash] = peer_id
        return retried

    def peer_notfound(self, peer_id: object, payload: bytes) -> tuple[bytes, ...]:
        """Release only block requests that this peer was assigned but lacks."""
        released = []
        for item in decode_inventory(payload):
            if item.kind != INV_TYPE_BLOCK:
                continue
            if self.pool.assigned_peer(item.item_hash) != peer_id:
                continue
            if self.pool.cancel(item.item_hash):
                self._tried_peers.setdefault(item.item_hash, set()).add(peer_id)
                # Retain a retry deadline even if no alternate peer is online.
                self._requested_at[item.item_hash] = time.monotonic()
                released.append(item.item_hash)
        return tuple(released)

    async def retry_released_bodies(
        self, block_hashes, peers: Mapping[object, object]
    ) -> dict[bytes, object]:
        """Assign previously released body hashes to other connected peers."""
        retried = {}
        for block_hash in block_hashes:
            if self.store.load_block_body(block_hash) is not None:
                continue
            if self.pool.assigned_peer(block_hash) is not None:
                continue
            available = self._available_peers(block_hash, peers)
            if not available:
                continue
            peer_id = self.pool.assign(block_hash, available)
            try:
                await peers[peer_id].send(
                    "getdata",
                    encode_inventory([InventoryVector(INV_TYPE_BLOCK, block_hash)]),
                )
            except Exception:
                self._tried_peers.setdefault(block_hash, set()).add(peer_id)
                self.pool.cancel(block_hash)
                self._requested_at[block_hash] = time.monotonic()
                raise
            self._requested_at[block_hash] = time.monotonic()
            retried[block_hash] = peer_id
        return retried

    def peer_disconnected(self, peer_id: object) -> tuple[bytes, ...]:
        """Release assignments so another connected peer can be selected."""
        released = self.pool.release_peer(peer_id)
        for block_hash in released:
            # Keep a timed retry queued in case the node currently has no peers.
            self._requested_at[block_hash] = time.monotonic()
        # A disconnected session is no longer a candidate for any pending
        # block, including requests that timed out before the disconnect.
        for block_hash, tried in tuple(self._tried_peers.items()):
            tried.discard(peer_id)
            if not tried:
                self._tried_peers.pop(block_hash, None)
        return released
