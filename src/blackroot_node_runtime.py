"""Explicit lifecycle wrapper joining persistent node state and P2P sync.

The runtime owns a PeerManager and synchronization adapter, and can supervise
periodic retries for expired fork-body requests. Network/genesis parameters
remain the caller's responsibility.
"""
from __future__ import annotations

import asyncio
import math

from .blackroot_node_state import PersistentNodeState
from .blackroot_p2p_manager import PeerManager
from .blackroot_p2p_service import P2PSyncService


class _NodeStateSyncStore:
    """Adapt P2P storage while routing activation through persistent node state."""

    _blackroot_node_state_lifecycle = True

    def __init__(self, state: PersistentNodeState) -> None:
        if not isinstance(state, PersistentNodeState):
            raise TypeError("state must be a PersistentNodeState")
        self._state = state
        self._utxos = state.utxos

    def tip(self):
        return self._utxos.tip()

    def store_block_body(self, block):
        return self._state.archive_block_body(block)

    def load_block_body(self, block_hash):
        return self._utxos.load_block_body(block_hash)

    def discard_block_bodies(self, block_hashes):
        return self._utxos.discard_block_bodies(block_hashes)

    def connect_validated_block(self, block, height, chain):
        if chain is not self._state.headers.chain:
            raise ValueError("P2P header chain is not the node state's validated chain")
        return self._state.connect_best_block(block, height)

    def reorganize_to_best(self, chain):
        if chain is not self._state.headers.chain:
            raise ValueError("P2P header chain is not the node state's validated chain")
        return self._state.reorganize_best()


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
        require_locked_state: bool = False,
        require_authenticated_bootstrap: bool = False,
    ) -> None
        if not isinstance(state, PersistentNodeState):
            raise TypeError("state must be a PersistentNodeState")
        if not isinstance(manager, PeerManager):
            raise TypeError("manager must be a PeerManager")
        if not isinstance(require_locked_state, bool):
            raise TypeError("require_locked_state must be a bool")
        if not isinstance(require_authenticated_bootstrap, bool):
            raise TypeError("require_authenticated_bootstrap must be a bool")
        if require_locked_state and not state.data_directory_locked:
            raise RuntimeError(
                "node runtime requires persistent state holding the data-directory lock"
            )
        state_adjusted_time = state.headers.adjusted_time_provider
        if not callable(state_adjusted_time):
            raise ValueError(
                "persistent node runtime requires the node state's adjusted-time provider"
            )
        if adjusted_time is not None and adjusted_time is not state_adjusted_time:
            raise ValueError(
                "runtime adjusted-time provider must match the persistent node state's provider"
            )
        if require_authenticated_bootstrap:
            state.utxos.verify_integrity(require_authenticated_bootstrap=True)
            if not state.require_authenticated_bootstrap:
                raise RuntimeError(
                    "node runtime requires persistent state opened with "
                    "require_authenticated_bootstrap=True"
                )
        self.state = state
        self.manager = manager
        self._sync_store = _NodeStateSyncStore(state)
        self.sync = P2PSyncService(
            manager,
            state.headers.chain,
            self._sync_store,
            protocol_version=protocol_version,
            request_timeout=request_timeout,
            adjusted_time=state_adjusted_time,
            persist_headers=state.persist_synced_headers,
            require_node_state_lifecycle=True,
        )
        self._closed = False
        self._retry_task: asyncio.Task | None = None
        self._retry_last_error: Exception | None = None

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
        """Retry timed-out fork-body requests immediately."""
        self._ensure_open()
        return await self.sync.retry_expired(now=now)

    @property
    def retry_loop_running(self) -> bool:
        """Whether the supervised block-request retry task is currently active."""
        return self._retry_task is not None and not self._retry_task.done()

    @property
    def retry_last_error(self) -> Exception | None:
        """Most recent retry error, cleared after a successful retry."""
        return self._retry_last_error

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
                    try:
                        await self.sync.retry_expired()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._retry_last_error = exc
                    else:
                        self._retry_last_error = None
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
