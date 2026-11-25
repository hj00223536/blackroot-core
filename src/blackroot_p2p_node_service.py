"""Node-level dispatcher wiring managed peers to the shared block scheduler.

The service handles only already-validated best-chain headers. Header discovery,
fork-body reorganization, transaction relay, peer scoring, and background task
scheduling remain explicit responsibilities of the embedding application.
"""
from __future__ import annotations

from collections.abc import Mapping

from .blackroot_p2p_inventory import (
    INV_TYPE_BLOCK,
    decode_inventory,
)
from .blackroot_p2p_multi_peer_sync import MultiPeerBlockScheduler


class NodePeerSyncService:
    """Route block inventory and responses through one shared scheduler."""

    def __init__(self, scheduler: MultiPeerBlockScheduler) -> None:
        if not isinstance(scheduler, MultiPeerBlockScheduler):
            raise TypeError("scheduler must be a MultiPeerBlockScheduler")
        self.scheduler = scheduler
        self._peers: dict[object, object] = {}

    @property
    def peers(self) -> Mapping[object, object]:
        """Snapshot of peer-ID to connected peer mappings."""
        return dict(self._peers)

    def register_peer(self, peer_id: object, peer: object) -> None:
        if peer_id in self._peers:
            raise ValueError("peer ID is already registered")
        self._peers[peer_id] = peer

    def _resolve_peer_id(self, peer_or_id: object) -> object:
        if peer_or_id in self._peers:
            return peer_or_id
        for peer_id, peer in self._peers.items():
            if peer is peer_or_id:
                return peer_id
        raise ValueError("peer is not registered")

    def on_peer_message_factory(self, peer: object):
        """Return the MessageHandler expected by PeerManager for this peer."""
        try:
            peer_id = self._resolve_peer_id(peer)
        except ValueError:
            # PeerManager creates the connection before invoking this factory;
            # use the connection object itself as its stable in-process ID.
            peer_id = peer
            self.register_peer(peer_id, peer)

        async def on_message(command: str, payload: bytes) -> None:
            await self.handle_message(peer_id, peer, command, payload)
        return on_message

    async def handle_message(self, peer_id: object, peer: object,
                             command: str, payload: bytes) -> None:
        if not getattr(peer, "connected", False):
            raise ConnectionError("peer handshake is not complete")
        if self._peers.get(peer_id) is not peer:
            raise ValueError("message received from an unregistered peer")

        if command == "inv":
            for item in decode_inventory(payload):
                if item.kind != INV_TYPE_BLOCK:
                    continue
                node = self.scheduler.chain.node(item.item_hash)
                if node is None:
                    continue
                if self.scheduler.chain.get(node.height).hash != item.item_hash:
                    continue
                if self.scheduler.pool.assigned_peer(item.item_hash) is not None:
                    continue
                await self.scheduler.request_block(item.item_hash, self._peers)
            return

        if command == "block":
            self.scheduler.accept_block(peer_id, payload)
            return

        if command == "notfound":
            released = []
            for item in decode_inventory(payload):
                if item.kind != INV_TYPE_BLOCK:
                    continue
                if self.scheduler.pool.assigned_peer(item.item_hash) != peer_id:
                    continue
                if self.scheduler.pool.cancel(item.item_hash):
                    self.scheduler.tracker.cancel(item.item_hash)
                    released.append(item.item_hash)
            await self._retry_hashes(released, exclude={peer_id})
            return

        raise ValueError(f"unsupported node sync command: {command}")

    async def _retry_hashes(self, hashes, *, exclude=frozenset()) -> dict[bytes, object]:
        retried = {}
        eligible = {
            peer_id: peer for peer_id, peer in self._peers.items()
            if peer_id not in exclude and getattr(peer, "connected", False)
        }
        for block_hash in hashes:
            if not eligible:
                break
            retried[block_hash] = await self.scheduler.request_block(block_hash, eligible)
        return retried

    async def peer_disconnected(self, peer_id: object) -> dict[bytes, object]:
        """Release a peer's requests and immediately reassign where possible."""
        peer_id = self._resolve_peer_id(peer_id)
        self._peers.pop(peer_id, None)
        released = self.scheduler.peer_disconnected(peer_id)
        return await self._retry_hashes(released)

    async def retry_expired(self, timeout: float, *, now: float | None = None) -> dict[bytes, object]:
        """Release timed-out requests and reassign them to connected peers."""
        expired = self.scheduler.tracker.expire(timeout, now=now)
        for block_hash in expired:
            self.scheduler.pool.cancel(block_hash)
        return await self._retry_hashes(expired)
