"""Node-level wiring for peer lifecycle, header sync, and fork-body downloads.

The service is opt-in and is attached to an existing PeerManager. It routes
messages by the actual PeerConnection object, owns one header coordinator per
peer, and shares one fork-body assignment pool across the node.
"""
from __future__ import annotations

from .blackroot_chain import HeaderChain
from .blackroot_p2p_header_sync import PeerHeaderSync
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
    ) -> None:
        if not isinstance(chain, HeaderChain):
            raise TypeError("chain must be a HeaderChain")
        if not isinstance(request_timeout, (int, float)) or isinstance(request_timeout, bool) or request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        self.manager = manager
        self.chain = chain
        self.store = store
        self.request_timeout = float(request_timeout)
        self.reorg = MultiPeerReorganizationSync(chain, store)
        self._header_sync: dict[object, PeerHeaderSync] = {}
        self._previous_factory = getattr(manager, "on_peer_message_factory", None)
        self._previous_disconnect = getattr(manager, "on_peer_disconnected", None)
        manager.on_peer_message_factory = self.message_handler_factory
        manager.on_peer_disconnected = self.peer_disconnected
        self.protocol_version = protocol_version
        self.adjusted_time = adjusted_time

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
                await self.reorg.request_missing_bodies(self._peers())
            elif command == "block":
                self.reorg.accept_block(peer, payload)
            elif command == "notfound":
                released = self.reorg.peer_notfound(peer, payload)
                if released:
                    await self.reorg.retry_released_bodies(released, self._peers())
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
        released = self.reorg.peer_disconnected(peer)
        if released:
            try:
                await self.reorg.retry_released_bodies(released, self._peers())
            except ValueError:
                # No eligible peer is currently available; the caller can
                # initiate another sync attempt when a new peer connects.
                pass
        if self._previous_disconnect is not None:
            result = self._previous_disconnect(peer)
            if hasattr(result, "__await__"):
                await result
