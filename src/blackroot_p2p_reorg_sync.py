"""Download missing best-fork bodies and activate a higher-work branch.

Headers are assumed to have passed HeaderChain validation already. Bodies are
requested from connected peers, checked against their exact header and Merkle
commitment, archived, and only then handed to UTXOStore's atomic reorganization
path. This component does not discover headers or provide production consensus.
"""
from __future__ import annotations

from collections.abc import Mapping

from .blackroot_blocks import Block
from .blackroot_chain import HeaderChain
from .blackroot_p2p_inventory import INV_TYPE_BLOCK, InventoryVector, encode_inventory
from .blackroot_p2p_request_pool import MultiPeerBlockRequestPool
from .blackroot_transactions import merkle_root


class MultiPeerReorganizationSync:
    def __init__(self, chain: HeaderChain, store, *, request_pool=None) -> None:
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

    def missing_best_branch_bodies(self) -> tuple[bytes, ...]:
        active = self.store.tip()
        if active is None:
            raise ValueError("cannot sync a fork before the UTXO chain is initialized")
        height, active_hash = active
        active_node = self.chain.node(active_hash)
        best_node = self.chain.node(self.chain.best_hash)
        if active_node is None or active_node.height != height:
            raise ValueError("active UTXO tip is inconsistent with header DAG")
        if best_node is None or best_node.chainwork <= active_node.chainwork:
            return ()
        _disconnect, connect = self.chain.reorganization(active_hash)
        return tuple(
            header.hash for header in connect
            if self.store.load_block_body(header.hash) is None
        )

    async def request_missing_bodies(self, peers: Mapping[object, object]) -> dict[bytes, object]:
        """Request all currently missing bodies; return hash-to-peer assignments."""
        requested = {}
        for block_hash in self.missing_best_branch_bodies():
            available = [
                peer_id for peer_id, peer in peers.items()
                if getattr(peer, "connected", False)
            ]
            peer_id = self.pool.assign(block_hash, available)
            try:
                await peers[peer_id].send(
                    "getdata",
                    encode_inventory([InventoryVector(INV_TYPE_BLOCK, block_hash)]),
                )
            except Exception:
                self.pool.cancel(block_hash)
                raise
            requested[block_hash] = peer_id
        return requested

    def accept_block(self, peer_id: object, payload: bytes):
        """Archive an assigned fork body and activate the branch when complete."""
        if not isinstance(payload, bytes):
            raise TypeError("block payload must be bytes")
        block = Block.deserialize(payload)
        block_hash = block.header.hash
        if self.pool.assigned_peer(block_hash) != peer_id:
            raise ValueError("fork block came from an unassigned peer")
        node = self.chain.node(block_hash)
        if node is None or node.header.serialize() != block.header.serialize():
            raise ValueError("fork block header is not in the validated header DAG")
        if merkle_root(tx.txid for tx in block.transactions) != block.header.merkle_root:
            raise ValueError("fork block Merkle root mismatch")
        self.store.store_block_body(block)
        if not self.pool.complete(block_hash, peer_id):
            raise RuntimeError("fork body assignment disappeared during acceptance")
        if not self.missing_best_branch_bodies() and not self.pool.pending_hashes:
            return self.store.reorganize_to_best(self.chain)
        return None

    def peer_disconnected(self, peer_id: object) -> tuple[bytes, ...]:
        """Release assignments so another connected peer can be selected."""
        return self.pool.release_peer(peer_id)
