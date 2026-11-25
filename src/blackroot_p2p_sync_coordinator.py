"""Per-peer P2P dispatcher joining header and block-body synchronization.

This coordinator is deliberately opt-in: callers bind it to an already
handshaken peer and provide a block-body lookup callback for serving data.
Unknown inventory triggers header discovery; only bodies requested through
BlockBodyRequestTracker can be connected. Transaction relay/mempool is not
implemented.
"""
from __future__ import annotations

from collections.abc import Callable

from .blackroot_blocks import Block
from .blackroot_p2p_block_sync import BlockBodyRequestTracker
from .blackroot_p2p_header_sync import PeerHeaderSync
from .blackroot_p2p_inventory import (
    INV_TYPE_BLOCK,
    InventoryVector,
    decode_inventory,
    encode_inventory,
)

BlockProvider = Callable[[bytes], bytes | None]


class PeerSyncCoordinator:
    """Dispatch inventory, header, getdata, and block messages for one peer."""

    def __init__(
        self,
        header_sync: PeerHeaderSync,
        *,
        block_provider: BlockProvider | None = None,
        request_tracker: BlockBodyRequestTracker | None = None,
    ) -> None:
        if not isinstance(header_sync, PeerHeaderSync):
            raise TypeError("header_sync must be a PeerHeaderSync")
        if block_provider is not None and not callable(block_provider):
            raise TypeError("block_provider must be callable")
        if request_tracker is not None and not isinstance(request_tracker, BlockBodyRequestTracker):
            raise TypeError("request_tracker must be a BlockBodyRequestTracker")
        self.header_sync = header_sync
        self.chain = header_sync.chain
        self.block_provider = block_provider
        self.requests = request_tracker or BlockBodyRequestTracker()
        self._header_request_pending = False

    def bind(self, peer):
        """Return the callback shape expected by PeerConnection for this peer."""
        async def on_message(command: str, payload: bytes) -> None:
            await self.handle_message(peer, command, payload)
        return on_message

    async def handle_message(self, peer, command: str, payload: bytes) -> None:
        if not getattr(peer, "connected", False):
            raise ConnectionError("peer handshake is not complete")

        if command in ("headers", "getheaders"):
            await self.header_sync.handle_message(peer, command, payload)
            if command == "headers":
                self._header_request_pending = False
            return

        if command == "inv":
            await self._handle_inventory(peer, payload)
            return

        if command == "getdata":
            await self._handle_getdata(peer, payload)
            return

        if command == "block":
            await self._handle_block(payload)
            return

        if command == "notfound":
            for item in decode_inventory(payload):
                if item.kind == INV_TYPE_BLOCK:
                    self.requests.cancel(item.item_hash)
            return

        raise ValueError(f"unsupported sync command: {command}")

    async def _handle_inventory(self, peer, payload: bytes) -> None:
        items = decode_inventory(payload)
        missing_headers = False
        for item in items:
            if item.kind != INV_TYPE_BLOCK:
                # Transaction inventory is decoded but transaction relay is not
                # enabled until a mempool and transaction policy exist.
                continue
            node = self.chain.node(item.item_hash)
            if node is None:
                missing_headers = True
                continue
            if self.chain.get(node.height).hash != item.item_hash:
                continue
            try:
                self.requests.request(item.item_hash, self.chain)
            except ValueError as exc:
                if "already outstanding" in str(exc):
                    continue
                if "maximum outstanding" in str(exc):
                    break
                raise
            await peer.send(
                "getdata",
                encode_inventory([InventoryVector(INV_TYPE_BLOCK, item.item_hash)]),
            )
        if missing_headers and not self._header_request_pending:
            await self.header_sync.request_headers(peer)
            self._header_request_pending = True

    async def _handle_getdata(self, peer, payload: bytes) -> None:
        items = decode_inventory(payload)
        unavailable: list[InventoryVector] = []
        for item in items:
            if item.kind != INV_TYPE_BLOCK or self.block_provider is None:
                unavailable.append(item)
                continue
            body = self.block_provider(item.item_hash)
            if body is None:
                unavailable.append(item)
                continue
            if not isinstance(body, bytes):
                raise TypeError("block_provider must return bytes or None")
            block = Block.deserialize(body)
            if block.header.hash != item.item_hash:
                raise ValueError("block provider returned a body for a different hash")
            await peer.send("block", body)
        if unavailable:
            await peer.send("notfound", encode_inventory(unavailable))

    async def _handle_block(self, payload: bytes) -> None:
        block = Block.deserialize(payload)
        block_hash = block.header.hash
        self.requests.accept_payload(
            block_hash,
            payload,
            self.chain,
            self._store,
        )

    @property
    def _store(self):
        store = getattr(self, "store", None)
        if store is None:
            raise RuntimeError("a UTXO store must be attached before accepting block bodies")
        return store

    def attach_store(self, store) -> None:
        """Attach the UTXO store used to validate and connect requested bodies."""
        if not callable(getattr(store, "connect_validated_block", None)):
            raise TypeError("store must provide connect_validated_block")
        self.store = store
