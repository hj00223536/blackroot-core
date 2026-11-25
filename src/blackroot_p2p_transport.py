"""Asyncio TCP peer session for the BLACKROOT P2P prototype.

This implements a single established TCP stream and the version/verack plus
ping/pong message lifecycle. It intentionally does not provide peer discovery,
listening sockets, encryption, authentication, address reputation, or a
production-ready network policy.
"""
from __future__ import annotations

import asyncio
import inspect
import secrets
import struct
from collections.abc import Awaitable, Callable

from .blackroot_p2p import DEFAULT_MAX_PAYLOAD, HEADER_SIZE, decode_message, encode_message
from .blackroot_p2p_handshake import VersionMessage
from .blackroot_p2p_state import PeerHandshake, encode_local_version

MessageHandler = Callable[[str, bytes], object | Awaitable[object]]


class PeerProtocolError(ValueError):
    """Raised when a remote peer violates the session protocol."""


class PeerConnection:
    """Own one asyncio reader/writer pair and enforce the peer handshake."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        magic: bytes,
        local_version: VersionMessage,
        max_payload: int = DEFAULT_MAX_PAYLOAD,
        handshake_timeout: float = 10.0,
        idle_timeout: float = 120.0,
        min_protocol_version: int = 1,
        on_message: MessageHandler | None = None,
    ) -> None:
        if not isinstance(magic, bytes) or len(magic) != 4:
            raise ValueError("network magic must be exactly four bytes")
        if not isinstance(max_payload, int) or isinstance(max_payload, bool) or not 0 <= max_payload <= 0xFFFFFFFF:
            raise ValueError("max_payload must fit uint32")
        if handshake_timeout <= 0 or idle_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if not isinstance(min_protocol_version, int) or min_protocol_version < 1:
            raise ValueError("minimum protocol version must be positive")
        self.reader = reader
        self.writer = writer
        self.magic = magic
        self.max_payload = max_payload
        self.handshake_timeout = handshake_timeout
        self.idle_timeout = idle_timeout
        self.min_protocol_version = min_protocol_version
        self.on_message = on_message
        self.handshake = PeerHandshake(local_version)
        self._send_lock = asyncio.Lock()
        self._closed = False
        self.remote_version: VersionMessage | None = None

    @property
    def connected(self) -> bool:
        return self.handshake.complete and not self._closed

    async def send(self, command: str, payload: bytes = b"") -> None:
        """Send one bounded frame, serializing concurrent writes."""
        if self._closed:
            raise ConnectionError("peer connection is closed")
        frame = encode_message(
            self.magic, command, payload, max_payload=self.max_payload
        )
        async with self._send_lock:
            self.writer.write(frame)
            await self.writer.drain()

    async def send_ping(self, nonce: int | None = None) -> int:
        """Send an eight-byte ping after handshake and return its nonce."""
        if not self.connected:
            raise PeerProtocolError("cannot ping before handshake completion")
        if nonce is None:
            nonce = secrets.randbits(64)
        if not isinstance(nonce, int) or isinstance(nonce, bool) or not 0 <= nonce <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("ping nonce must fit uint64")
        await self.send("ping", struct.pack("<Q", nonce))
        return nonce

    async def _read_message(self) -> tuple[str, bytes]:
        header = await self.reader.readexactly(HEADER_SIZE)
        if header[:4] != self.magic:
            raise PeerProtocolError("message network magic mismatch")
        length = struct.unpack_from("<I", header, 16)[0]
        if length > self.max_payload:
            raise PeerProtocolError("message payload exceeds configured limit")
        payload = await self.reader.readexactly(length)
        try:
            return decode_message(header + payload, self.magic, max_payload=self.max_payload)
        except ValueError as exc:
            raise PeerProtocolError(str(exc)) from exc

    async def handle_message(self, command: str, payload: bytes) -> None:
        """Apply one decoded message to the handshake or active session."""
        if command == "version":
            if self.handshake.remote_version is not None:
                raise PeerProtocolError("duplicate version message")
            remote = self.handshake.receive_version(payload)
            if remote.protocol_version < self.min_protocol_version:
                raise PeerProtocolError("peer protocol version is unsupported")
            self.remote_version = remote
            await self.send("verack")
            self.handshake.mark_local_verack_sent()
            return

        if command == "verack":
            try:
                self.handshake.receive_verack(payload)
            except ValueError as exc:
                raise PeerProtocolError(str(exc)) from exc
            return

        if not self.handshake.complete:
            raise PeerProtocolError("application message received before handshake completion")

        if command == "ping":
            if len(payload) != 8:
                raise PeerProtocolError("ping payload must be exactly eight bytes")
            await self.send("pong", payload)
            return

        if command == "pong":
            if len(payload) != 8:
                raise PeerProtocolError("pong payload must be exactly eight bytes")
            return

        if self.on_message is not None:
            result = self.on_message(command, payload)
            if inspect.isawaitable(result):
                await result

    async def run(self) -> None:
        """Send version, complete handshake, then process messages until EOF."""
        if self.handshake.local_version_sent:
            raise PeerProtocolError("peer session has already been started")
        try:
            await self.send("version", encode_local_version(self.handshake))
            while not self._closed:
                timeout = self.idle_timeout if self.handshake.complete else self.handshake_timeout
                try:
                    command, payload = await asyncio.wait_for(
                        self._read_message(), timeout=timeout
                    )
                except asyncio.TimeoutError as exc:
                    phase = "idle" if self.handshake.complete else "handshake"
                    raise TimeoutError(f"peer {phase} timeout") from exc
                await self.handle_message(command, payload)
        except asyncio.IncompleteReadError:
            return
        finally:
            await self.close()

    async def close(self) -> None:
        """Close the stream and release its transport resources."""
        if self._closed:
            return
        self._closed = True
        self.writer.close()
        wait_closed = getattr(self.writer, "wait_closed", None)
        if callable(wait_closed):
            try:
                await wait_closed()
            except (ConnectionError, OSError):
                pass


async def connect_peer(
    host: str,
    port: int,
    *,
    magic: bytes,
    local_version: VersionMessage,
    max_payload: int = DEFAULT_MAX_PAYLOAD,
    connect_timeout: float = 10.0,
    handshake_timeout: float = 10.0,
    idle_timeout: float = 120.0,
    min_protocol_version: int = 1,
    on_message: MessageHandler | None = None,
) -> PeerConnection:
    """Open one outbound TCP connection and run its peer session to completion.

    The returned connection is closed when this coroutine returns. For a
    long-lived session, retain the task running this coroutine.
    """
    if not host or not isinstance(host, str):
        raise ValueError("host must be non-empty text")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=connect_timeout
    )
    return PeerConnection(
        reader,
        writer,
        magic=magic,
        local_version=local_version,
        max_payload=max_payload,
        handshake_timeout=handshake_timeout,
        idle_timeout=idle_timeout,
        min_protocol_version=min_protocol_version,
        on_message=on_message,
    )
