"""Explicit lifecycle wrapper joining persistent node state and P2P sync.

The runtime owns a PeerManager and the synchronization adapter, but does not
create background retry timers or choose network/genesis parameters. The caller
must invoke retry_expired from its own supervised event loop.
"""
from __future__ import annotations

import asyncio
import math

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
            persist_headers=state.persist_synced_headers,
        )
        self._closed = False
        self._retry_task: asyncio.Task | None = None

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

    async def start_retry_loop(self, *, interval: float = 1.0) -> None:
        """Start one supervised periodic retry loop for expired block requests."""
        self._ensure_open()
        if (isinstance(interval, bool) or not isinstance(interval, (int, float))
                or not math.isfinite(interval) or interval <= 0):
            raise ValueError("interval must be a finite positive number")
        if self._retry_task is not None and not self._retry_task.done():
            return
        self._retry_task = asyncio.create_task(
            self._run_retry_loop(float(interval)),
            name="blackroot-block-request-retry",
        )

    async def _run_retry_loop(self, interval: float) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(interval)
                if not self._closed:
                    await self.sync.retry_expired()
        except asyncio.CancelledError:
            raise

    async def stop_retry_loop(self) -> None:
        """Cancel and await the retry loop without closing persistent state."""
        task = self._retry_task
        self._retry_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("node runtime is closed")

    async def close(self) -> None:
        """Close the peer manager once; SQLite state remains available for reopen."""
        if self._closed:
            return
        self._closed = True
        await self.stop_retry_loop()
        await self.manager.close()
