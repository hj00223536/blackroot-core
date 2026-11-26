"""Peer wiring for header sync, block downloads, and fork-body activation.

The service is opt-in and is attached to an existing PeerManager. It routes
messages by the actual PeerConnection object, owns one header coordinator per
peer, and shares one fork-body assignment pool across the node. Persistent-node
callers must pass a lifecycle adapter (as BlackrootNodeRuntime does), not a raw
UTXOStore, so activation participates in the node recovery-journal boundary.
"""
from __future__ import annotations

import math

from .blackroot_chain import HeaderChain
from .blackroot_p2p_header_sync import PeerHeaderSync
from .blackroot_p2p_multi_peer_sync import MultiPeerBlockScheduler
from .blackroot_p2p_inventory import INV_TYPE_BLOCK, decode_inventory
from .blackroot_p2p_reorg_sync import MultiPeerReorganizationSync


class P2PSyncService:
    """Wire a PeerManager to shared header and best-fork body synchronization."""

    def __init__(
        self,
        manager,
        chain: HeaderChain,
        store,
        *,
        protocol_version: int,
        request_timeout: float = 30.0,
        adjusted_time=None,
        persist_headers=None,
        require_node_state_lifecycle: bool = False,
    ) -> None:
        if not isinstance(require_node_state_lifecycle, bool):
            raise TypeError("require_node_state_lifecycle must be a bool")
        if require_node_state_lifecycle and getattr(store, "_blackroot_node_state_lifecycle", False) is not True:
            raise ValueError("persistent-node P2P sync requires a node-state lifecycle adapter")
        if not isinstance(chain, HeaderChain):
            raise TypeError("chain must be a HeaderChain")
        if (not isinstance(request_timeout, (int, float)) or isinstance(request_timeout, bool)
                or not math.isfinite(request_timeout) or request_timeout <= 0):
            raise ValueError("request_timeout must be positive")
        self.manager = manager
        self.chain = chain
        self.store = store
        self.request_timeout = float(request_timeout)
        self.reorg = MultiPeerReorganizationSync(
            chain, store, require_node_state_lifecycle=require_node_state_lifecycle
        )
        self.blocks = MultiPeerBlockScheduler(
            chain, store, require_node_state_lifecycle=require_node_state_lifecycle
        )
        self._header_sync: dict[object, PeerHeaderSync] = {}
        self._previous_factory = getattr(manager, "on_peer_message_factory", None)
        self._previous_disconnect = getattr(manager, "on_peer_disconnected", None)
        manager.on_peer_message_factory = self.message_handler_factory
        manager.on_peer_disconnected = self.peer_disconnected
        self.protocol_version = protocol_version
        self.adjusted_time = adjusted_time
        if persist_headers is not None and not callable(persist_headers):
            raise TypeError("persist_headers must be callable")
        self.persist_headers = persist_headers

    def _peers(self) -> dict[object, object]:
        return {peer: peer for peer in self.manager.peers if getattr(peer, "connected", False)}

    def message_handler_factory(self, peer):
        """Create the per-connection dispatcher expected by PeerManager."""
        if self._previous_factory is not None:
            previous = self._previous_factory(peer)
        else:
            previous = None
        self._header_sync[peer] = PeerHeaderSync(
            self.chain,
            protocol_version=self.protocol_version,
            adjusted_time=self.adjusted_time,
        )

        async def dispatch(command: str, payload: bytes) -> None:
            if command in ("headers", "getheaders"):
                await self._header_sync[peer].handle_message(peer, command, payload)
                if command == "headers" and self.persist_headers is not None:
                    self.persist_headers(self.chain)
                # A fresh node has no active UTXO tip until its genesis body is
                # explicitly bootstrapped. Header sync must remain usable without
                # turning that expected bootstrap state into a peer-disconnect error.
                if self.store.tip() is not None:
                    peers = self._peers()
                    await self.reorg.request_missing_bodies(peers)
            elif command == "inv":
                unknown_headers = False
                for item in decode_inventory(payload):
                    if item.kind != INV_TYPE_BLOCK:
                        continue
                    node = self.chain.node(item.item_hash)
                    if node is None:
                        unknown_headers = True
                    elif self.chain.get(node.height).hash == item.item_hash:
                        peers = self._peers()
                        if self.store.tip() is None:
                            # Only the selected genesis body can bootstrap an
                            # empty UTXO store; later heights must wait for it.
                            if node.height == 0:
                                try:
                                    await self.blocks.request_block(item.item_hash, peers)
                                except ValueError as exc:
                                    if "already has an assigned source" not in str(exc) and "already outstanding" not in str(exc):
                                        raise
                        else:
                            # Once initialized, the fork synchronizer owns all
                            # missing bodies from the active tip to the selected
                            # best header, avoiding out-of-order direct connects.
                            await self.reorg.request_missing_bodies(peers)
                        else:
                            # Once initialized, the fork synchronizer owns all
                            # missing bodies from the active tip to the selected
                            # best header. Avoid a second independent request
                            # pool that could deliver an out-of-order block to
                            # the direct-extension connector.
                            await self.reorg.request_missing_bodies(peers)
                if unknown_headers:
                    await self._header_sync[peer].request_headers(peer)
            elif command == "block":
                from .blackroot_blocks import Block
                block_hash = Block.deserialize(payload).header.hash
                if self.reorg.pool.assigned_peer(block_hash) == peer:
                    self.reorg.accept_block(peer, payload)
                elif self.blocks.pool.assigned_peer(block_hash) == peer:
                    self.blocks.accept_block(peer, payload)
                    # Completing genesis may turn on ordered body sync for
                    # headers that arrived before the UTXO chain was bootstrapped.
                    if self.store.tip() is not None:
                        await self.reorg.request_missing_bodies(self._peers())
                else:
                    raise ValueError("block response was not assigned to this peer")
            elif command == "notfound":
                released_forks = self.reorg.peer_notfound(peer, payload)
                released_best = []
                for item in decode_inventory(payload):
                    if item.kind == INV_TYPE_BLOCK and self.blocks.pool.assigned_peer(item.item_hash) == peer:
                        if self.blocks.pool.cancel(item.item_hash):
                            self.blocks.tracker.cancel(item.item_hash)
                            released_best.append(item.item_hash)
                alternatives = self._peers()
                alternatives.pop(peer, None)
                if released_forks and alternatives:
                    await self.reorg.retry_released_bodies(released_forks, alternatives)
                for block_hash in released_best:
                    if alternatives:
                        try:
                            await self.blocks.request_block(block_hash, alternatives)
                        except ValueError:
                            pass
            elif previous is not None:
                result = previous(command, payload)
                if hasattr(result, "__await__"):
                    await result

        return dispatch

    async def start_peer_sync(self, peer=None) -> dict[object, bytes]:
        """Request headers from one peer or every currently connected peer."""
        selected = (peer,) if peer is not None else tuple(self._peers())
        sent = {}
        for current in selected:
            if current not in self._header_sync:
                raise ValueError("peer is not registered with this sync service")
            sent[current] = await self._header_sync[current].request_headers(current)
        return sent

    async def retry_expired(self, *, now: float | None = None) -> dict[bytes, object]:
        """Reassign timed-out fork bodies; call from the application's timer loop."""
        return await self.reorg.retry_expired_requests(
            self._peers(), self.request_timeout, now=now
        )

    async def peer_disconnected(self, peer) -> None:
        """Release a disconnected source and immediately retry on remaining peers."""
        self._header_sync.pop(peer, None)
        released_forks = self.reorg.peer_disconnected(peer)
        released_best = self.blocks.peer_disconnected(peer)
        remaining = self._peers()
        if released_forks:
            try:
                await self.reorg.retry_released_bodies(released_forks, remaining)
            except ValueError:
                pass
        for block_hash in released_best:
            if remaining:
                try:
                    await self.blocks.request_block(block_hash, remaining)
                except ValueError:
                    pass
        if self._previous_disconnect is not None:
            result = self._previous_disconnect(peer)
            if hasattr(result, "__await__"):
                await result
