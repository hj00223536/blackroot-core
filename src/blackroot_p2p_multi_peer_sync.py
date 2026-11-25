"""Network-facing multi-peer block download scheduler.

This component owns a shared request tracker and source assignment pool for a
single node. It sends getdata to the selected connected peer and accepts a
response only from that assigned peer, then delegates full validation and
connection to the existing UTXO store boundary.
"""
from __future__ import annotations

from collections.abc import Mapping

from .blackroot_chain import HeaderChain
from .blackroot_p2p_block_sync import BlockBodyRequestTracker
from .blackroot_p2p_inventory import INV_TYPE_BLOCK, InventoryVector, encode_inventory
from .blackroot_p2p_request_pool import MultiPeerBlockRequestPool


class MultiPeerBlockScheduler:
    def __init__(
        self,
        chain: HeaderChain,
        store,
        *,
        request_pool: MultiPeerBlockRequestPool | None = None,
        request_tracker: BlockBodyRequestTracker | None = None,
    ) -> None:
        if not isinstance(chain, HeaderChain):
            raise TypeError("chain must be a HeaderChain")
        if not callable(getattr(store, "connect_validated_block", None)):
            raise TypeError("store must provide connect_validated_block")
        self.chain = chain
        self.store = store
        self.pool = request_pool or MultiPeerBlockRequestPool()
        self.tracker = request_tracker or BlockBodyRequestTracker()

    async def request_block(self, block_hash: bytes, peers: Mapping[object, object]):
        """Assign and send one block request; return the selected peer ID."""
        available = [
            peer_id for peer_id, peer in peers.items()
            if getattr(peer, "connected", False)
        ]
        peer_id = self.pool.assign(block_hash, available)
        peer = peers[peer_id]
        try:
            self.tracker.request(block_hash, self.chain)
            await peer.send(
                "getdata",
                encode_inventory([InventoryVector(INV_TYPE_BLOCK, block_hash)]),
            )
        except Exception:
            self.tracker.cancel(block_hash)
            self.pool.cancel(block_hash)
            raise
        return peer_id

    def accept_block(self, peer_id: object, payload: bytes) -> tuple[int, int]:
        """Accept only a block from its assigned peer and validate it fully."""
        from .blackroot_blocks import Block

        block = Block.deserialize(payload)
        block_hash = block.header.hash
        if self.pool.assigned_peer(block_hash) != peer_id:
            raise ValueError("block response came from an unassigned peer")
        result = self.tracker.accept_payload(
            block_hash, payload, self.chain, self.store
        )
        if not self.pool.complete(block_hash, peer_id):
            raise RuntimeError("request assignment disappeared during acceptance")
        return result

    def peer_disconnected(self, peer_id: object) -> tuple[bytes, ...]:
        """Release a disconnected peer's assignments and tracker entries."""
        hashes = self.pool.release_peer(peer_id)
        for block_hash in hashes:
            self.tracker.cancel(block_hash)
        return hashes
