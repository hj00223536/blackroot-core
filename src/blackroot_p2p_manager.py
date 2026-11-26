"""Bounded asyncio peer manager for inbound and outbound TCP sessions.

This module composes PeerConnection instances. It does not implement peer
discovery, encryption, cryptographic identity, or production anti-Sybil policy.
"""
from __future__ import annotations

import asyncio
import math
import secrets
from dataclasses import replace
from typing import Callable

from .blackroot_p2p import DEFAULT_MAX_PAYLOAD
from .blackroot_p2p_handshake import VersionMessage
from .blackroot_p2p_transport import MessageHandler, PeerConnection, PeerProtocolError


class PeerManager:
    """Manage a bounded set of inbound and outbound peer sessions."""

    def __init__(
        self,
        *,
        magic: bytes,
        local_version: VersionMessage,
        max_peers: int = 16,
        max_payload: int = DEFAULT_MAX_PAYLOAD,
        connect_timeout: float = 10.0,
        handshake_timeout: float = 10.0,
        idle_timeout: float = 120.0,
        min_protocol_version: int = 1,
        on_message: MessageHandler | None = None,
        on_peer_message_factory: Callable[[PeerConnection], MessageHandler] | None = None,
        on_peer_error: Callable[[Exception], object] | None = None,
        on_peer_disconnected: Callable[[PeerConnection], object] | None = None,
    ) -> None:
        if not isinstance(magic, bytes) or len(magic) != 4:
            raise ValueError("network magic must be exactly four bytes")
        if not isinstance(max_peers, int) or isinstance(max_peers, bool) or max_peers < 1:
            raise ValueError("max_peers must be a positive integer")
        for name, value in (
            ("connect_timeout", connect_timeout),
            ("handshake_timeout", handshake_timeout),
            ("idle_timeout", idle_timeout),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number")
        if (
            not isinstance(max_payload, int)
            or isinstance(max_payload, bool)
            or not 0 <= max_payload <= DEFAULT_MAX_PAYLOAD
        ):
            raise ValueError("max_payload must be an integer within the protocol limit")
        if (
            not isinstance(min_protocol_version, int)
            or isinstance(min_protocol_version, bool)
            or min_protocol_version < 1
        ):
            raise ValueError("minimum protocol version must be a positive integer")
        if on_message is not None and not callable(on_message):
            raise TypeError("on_message must be callable")
        if on_peer_error is not None and not callable(on_peer_error):
            raise TypeError("on_peer_error must be callable")
        self.magic = magic
        self.local_version = local_version
        self.max_peers = max_peers
        self.max_payload = max_payload
        self.connect_timeout = connect_timeout
        self.handshake_timeout = handshake_timeout
        self.idle_timeout = idle_timeout
        self.min_protocol_version = min_protocol_version
        if on_peer_message_factory is not None and not callable(on_peer_message_factory):
            raise TypeError("on_peer_message_factory must be callable")
        self.on_message = on_message
        self.on_peer_message_factory = on_peer_message_factory
        self.on_peer_error = on_peer_error
        if on_peer_disconnected is not None and not callable(on_peer_disconnected):
            raise TypeError("on_peer_disconnected must be callable")
        self.on_peer_disconnected = on_peer_disconnected
        self._server: asyncio.AbstractServer | None = None
        self._peers: set[PeerConnection] = set()
        self._tasks: set[asyncio.Task] = set()
        self._outbound_reservations = 0
        self._closing = False

    @property
    def peer_count(self) -> int:
        """Number of currently managed peer sessions."""
        return len(self._peers)

    @property
    def peers(self) -> tuple[PeerConnection, ...]:
        """Snapshot of managed peer sessions."""
        return tuple(self._peers)

    @property
    def listening(self) -> bool:
        return self._server is not None and self._server.is_serving()

    @property
    def sockets(self):
        """Listening sockets, or an empty tuple before server startup."""
        return tuple(self._server.sockets or ()) if self._server is not None else ()

    def _load(self) -> int:
        return len(self._peers) + self._outbound_reservations

    def _new_version(self) -> VersionMessage:
        return replace(self.local_version, nonce=secrets.randbits(64))

    def _new_peer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> PeerConnection:
        peer = PeerConnection(
            reader,
            writer,
            magic=self.magic,
            local_version=self._new_version(),
            max_payload=self.max_payload,
            handshake_timeout=self.handshake_timeout,
            idle_timeout=self.idle_timeout,
            min_protocol_version=self.min_protocol_version,
            on_message=self.on_message,
        )
        if self.on_peer_message_factory is not None:
            peer.on_message = self.on_peer_message_factory(peer)
        return peer

    def _track(self, peer: PeerConnection) -> PeerConnection:
        self._peers.add(peer)
        task = asyncio.create_task(self._run_peer(peer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return peer

    async def _report_error(self, error: Exception) -> None:
        if self.on_peer_error is None:
            return
        result = self.on_peer_error(error)
        if asyncio.iscoroutine(result):
            await result

    async def _run_peer(self, peer: PeerConnection) -> None:
        try:
            await peer.run()
        except (PeerProtocolError, TimeoutError, OSError, ConnectionError) as exc:
            await self._report_error(exc)
        finally:
            await peer.close()
            self._peers.discard(peer)
            if self.on_peer_disconnected is not None:
                result = self.on_peer_disconnected(peer)
                if asyncio.iscoroutine(result):
                    await result

    async def start_server(self, host: str = "127.0.0.1", port: int = 0) -> tuple:
        """Start an inbound TCP listener and return its bound socket address."""
        if self._closing:
            raise RuntimeError("peer manager is closing")
        if self._server is not None:
            raise RuntimeError("peer listener is already started")
        self._server = await asyncio.start_server(self._accept, host, port)
        if not self._server.sockets:
            raise OSError("peer listener did not bind a socket")
        return self._server.sockets[0].getsockname()

    def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._closing or self._load() >= self.max_peers:
            writer.close()
            return
        self._track(self._new_peer(reader, writer))

    async def connect(self, host: str, port: int) -> PeerConnection:
        """Open and manage one outbound session, subject to the peer cap."""
        if self._closing:
            raise RuntimeError("peer manager is closing")
        if not isinstance(host, str) or not host:
            raise ValueError("host must be non-empty text")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self._load() >= self.max_peers:
            raise RuntimeError("maximum peer count reached")
        self._outbound_reservations += 1
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=self.connect_timeout
            )
            if self._closing:
                writer.close()
                raise RuntimeError("peer manager closed during connect")
            return self._track(self._new_peer(reader, writer))
        finally:
            self._outbound_reservations -= 1

    async def close(self) -> None:
        """Stop accepting peers and close all managed sessions."""
        if self._closing:
            return
        self._closing = True
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        peers = tuple(self._peers)
        await asyncio.gather(*(peer.close() for peer in peers), return_exceptions=True)
        tasks = tuple(self._tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._peers.clear()
