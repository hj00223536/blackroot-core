"""Explicit lifecycle wrapper joining persistent node state and P2P sync.

The runtime owns a PeerManager and the synchronization adapter, but does not
create background retry timers or choose network/genesis parameters. The caller
must invoke retry_expired from its own supervised event loop.
"""
from __future__ import annotations

from .blackroot_node_state import PersistentNodeState
from .blackroot_p2p_manager import PeerManager
from .blackroot_p2p_service import P2PSyncService


class BlackrootNodeRuntime:
    """Bind validated persistent state to one managed P2P network lifecycle."""

    def __init__(
        self,
        state: PersistentNodeState,
        manager: PeerManager,
        *,
        protocol_version: int,
        request_timeout: float = 30.0,
        adjusted_time=None,
    ) -> None:
        if not isinstance(state, PersistentNodeState):
            raise TypeError("state must be a PersistentNodeState")
        if not isinstance(manager, PeerManager):
            raise TypeError("manager must be a PeerManager")
        self.state = state
        self.manager = manager
        self.sync = P2PSyncService(
            manager,
            state.headers.chain,
            state.utxos,
            protocol_version=protocol_version,
            request_timeout=request_timeout,
            adjusted_time=adjusted_time,
            persist_headers=state.headers.persist_chain,
        )
        self._closed = False

    @property
    def peer_count(self) -> int:
        """Number of managed peer sessions, including handshaking peers."""
        return self.manager.peer_count

    @property
    def listening(self) -> bool:
        """Whether the managed TCP listener is accepting inbound sessions."""
        return self.manager.listening

    async def listen(self, host: str = "127.0.0.1", port: int = 0) -> tuple:
        """Start the inbound listener; returns the bound socket address."""
        self._ensure_open()
        return await self.manager.start_server(host, port)

    async def connect(self, host: str, port: int):
        """Open and manage an outbound peer session."""
        self._ensure_open()
        return await self.manager.connect(host, port)

    async def synchronize(self) -> dict[object, bytes]:
        """Start header synchronization with every currently handshaken peer."""
        self._ensure_open()
        return await self.sync.start_peer_sync()

    async def retry_expired(self, *, now: float | None = None) -> dict[bytes, object]:
        """Retry timed-out fork-body requests; caller owns timer scheduling."""
        self._ensure_open()
        return await self.sync.retry_expired(now=now)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("node runtime is closed")

    async def close(self) -> None:
        """Close the peer manager once; SQLite state remains available for reopen."""
        if self._closed:
            return
        self._closed = True
        await self.manager.close()
