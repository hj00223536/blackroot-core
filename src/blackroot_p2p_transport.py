"""Asyncio TCP peer session for the BLACKROOT P2P prototype.

This implements a single established TCP stream and the version/verack plus
ping/pong message lifecycle. It intentionally does not provide peer discovery,
listening sockets, encryption, authentication, address reputation, or a
production-ready network policy.
"""
from __future__ import annotations

import asyncio
import inspect
import math
import secrets
import struct
import time
from collections.abc import Awaitable, Callable

from .blackroot_p2p import DEFAULT_MAX_PAYLOAD, HEADER_SIZE, decode_message, encode_message
from .blackroot_p2p_handshake import VersionMessage
from .blackroot_p2p_state import PeerHandshake, encode_local_version
from .blackroot_blocks import MAX_BLOCK_SIZE
from .blackroot_p2p_headers import MAX_HEADERS_PER_MESSAGE
from .blackroot_p2p_inventory import MAX_INVENTORY_ITEMS
from .blackroot_p2p_getheaders import MAX_BLOCK_LOCATOR_HASHES
from .blackroot_p2p_resources import ResourceBudget, reserve_resources

MessageHandler = Callable[[str, bytes], object | Awaitable[object]]

# Reject fixed/small control-message lengths from the header before reading
# attacker-controlled payload bytes from the TCP stream.
_VERSION_MAX_PAYLOAD = 32 + 2 + 256
_CONTROL_PAYLOAD_LENGTHS = {
    b"verack" + bytes(6): 0,
    b"ping" + bytes(8): 8,
    b"pong" + bytes(8): 8,
}

# Derive per-command receive ceilings from the corresponding bounded codecs.
# These are prototype wire/resource limits, not frozen consensus parameters.
_COMMAND_MAX_PAYLOADS = {
    b"block" + bytes(7): MAX_BLOCK_SIZE,
    b"headers" + bytes(5): 3 + MAX_HEADERS_PER_MESSAGE * 81,
    b"getheaders" + bytes(2): 4 + 1 + MAX_BLOCK_LOCATOR_HASHES * 32 + 32,
}
_INVENTORY_MAX_PAYLOAD = 3 + MAX_INVENTORY_ITEMS * 36
for _command in ("inv", "getdata", "notfound"):
    _COMMAND_MAX_PAYLOADS[_command.encode("ascii").ljust(12, b"\x00")] = _INVENTORY_MAX_PAYLOAD


def _validate_control_payload_length(command_field: bytes, length: int) -> None:
    if command_field == b"version" + bytes(5):
        if length > _VERSION_MAX_PAYLOAD:
            raise PeerProtocolError("version payload exceeds configured byte limit")
        return
    expected = _CONTROL_PAYLOAD_LENGTHS.get(command_field)
    if expected is not None and length != expected:
        command = command_field.split(b"\x00", 1)[0].decode("ascii")
        raise PeerProtocolError(f"{command} payload must be exactly {expected} bytes")
    maximum = _COMMAND_MAX_PAYLOADS.get(command_field)
    if maximum is not None and length > maximum:
        command = command_field.split(b"\x00", 1)[0].decode("ascii")
        raise PeerProtocolError(f"{command} payload exceeds its command-specific limit")


def _validate_timeout(name: str, value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a finite positive number")


class _TokenBucket:
    """Small monotonic-clock token bucket owned by one peer connection."""

    def __init__(self, rate: float, capacity: float, now: float) -> None:
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.updated_at = now

    def refill(self, now: float) -> None:
        if now > self.updated_at:
            self.tokens = min(
                self.capacity, self.tokens + (now - self.updated_at) * self.rate
            )
            self.updated_at = now

    def can_consume(self, amount: float, now: float) -> bool:
        self.refill(now)
        return self.tokens >= amount

    def consume(self, amount: float) -> None:
        self.tokens -= amount


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
        control_messages_per_second: float = 20.0,
        control_message_burst: float = 40.0,
        data_messages_per_second: float = 20.0,
        data_message_burst: float = 40.0,
        data_bytes_per_second: float = 2 * 1024 * 1024,
        data_bytes_burst: float = 4 * 1024 * 1024,
        monotonic_clock: Callable[[], float] = time.monotonic,
        send_resource_budgets: tuple[ResourceBudget, ResourceBudget] | None = None,
        receive_resource_budgets: tuple[ResourceBudget, ResourceBudget] | None = None,
    ) -> None:
        if not isinstance(magic, bytes) or len(magic) != 4:
            raise ValueError("network magic must be exactly four bytes")
        if not isinstance(max_payload, int) or isinstance(max_payload, bool) or not 0 <= max_payload <= 0xFFFFFFFF:
            raise ValueError("max_payload must fit uint32")
        _validate_timeout("handshake_timeout", handshake_timeout)
        _validate_timeout("idle_timeout", idle_timeout)
        if (
            not isinstance(min_protocol_version, int)
            or isinstance(min_protocol_version, bool)
            or min_protocol_version < 1
        ):
            raise ValueError("minimum protocol version must be a positive integer")
        self.reader = reader
        self.writer = writer
        self.magic = magic
        self.max_payload = max_payload
        self.handshake_timeout = handshake_timeout
        self.idle_timeout = idle_timeout
        self.min_protocol_version = min_protocol_version
        self.on_message = on_message
        rate_settings = (
            ("control_messages_per_second", control_messages_per_second),
            ("control_message_burst", control_message_burst),
            ("data_messages_per_second", data_messages_per_second),
            ("data_message_burst", data_message_burst),
            ("data_bytes_per_second", data_bytes_per_second),
            ("data_bytes_burst", data_bytes_burst),
        )
        for name, value in rate_settings:
            _validate_timeout(name, value)
        if not callable(monotonic_clock):
            raise ValueError("monotonic_clock must be callable")
        now = monotonic_clock()
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
        ):
            raise ValueError("monotonic_clock must return a finite number")
        if send_resource_budgets is not None:
            if (
                not isinstance(send_resource_budgets, tuple)
                or len(send_resource_budgets) != 2
                or any(not isinstance(item, ResourceBudget) for item in send_resource_budgets)
                or send_resource_budgets[0] is send_resource_budgets[1]
            ):
                raise ValueError("send_resource_budgets must be a distinct (peer, node) budget pair")
        self._send_resource_budgets = send_resource_budgets
        if receive_resource_budgets is not None:
            if (
                not isinstance(receive_resource_budgets, tuple)
                or len(receive_resource_budgets) != 2
                or any(not isinstance(item, ResourceBudget) for item in receive_resource_budgets)
                or receive_resource_budgets[0] is receive_resource_budgets[1]
            ):
                raise ValueError("receive_resource_budgets must be a distinct (peer, node) budget pair")
        self._receive_resource_budgets = receive_resource_budgets
        self._pending_receive_reservation = None
        self._monotonic_clock = monotonic_clock
        self._control_message_bucket = _TokenBucket(
            control_messages_per_second, control_message_burst, now
        )
        self._data_message_bucket = _TokenBucket(
            data_messages_per_second, data_message_burst, now
        )
        self._data_byte_bucket = _TokenBucket(
            data_bytes_per_second, data_bytes_burst, now
        )
        self.handshake = PeerHandshake(local_version)
        self._send_lock = asyncio.Lock()
        self._closed = False
        self.remote_version: VersionMessage | None = None

    @property
    def connected(self) -> bool:
        return self.handshake.complete and not self._closed

    async def send(self, command: str, payload: bytes = b"") -> None:
        """Send one frame; when configured, reserve peer and node capacity first."""
        if self._closed:
            raise ConnectionError("peer connection is closed")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        reservation = None
        if self._send_resource_budgets is not None:
            peer_budget, node_budget = self._send_resource_budgets
            reservation = reserve_resources(
                (
                    (peer_budget, 1, HEADER_SIZE + len(payload)),
                    (node_budget, 1, HEADER_SIZE + len(payload)),
                )
            )
            if reservation is None:
                raise PeerProtocolError("outbound resource budget exhausted")
        write_started = False
        try:
            # Encoding happens only after both budgets have admitted the exact
            # frame size. The reservation remains owned through drain completion.
            frame = encode_message(
                self.magic, command, payload, max_payload=self.max_payload
            )
            async with self._send_lock:
                if self._closed:
                    raise ConnectionError("peer connection is closed")
                self.writer.write(frame)
                write_started = True
                await self.writer.drain()
        except BaseException:
            # Once handed to the stream transport, a cancelled/failed drain has
            # ambiguous delivery and retained-buffer ownership. Fail closed by
            # closing this peer before releasing the reservation.
            if write_started:
                await self.close()
            raise
        finally:
            if reservation is not None:
                reservation.release()

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

    def _consume_inbound_budget(self, command: str, payload_length: int) -> None:
        """Charge this peer's message and byte budgets before reading its body."""
        now = self._monotonic_clock()
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
        ):
            raise PeerProtocolError("monotonic clock returned an invalid value")
        if command in {"version", "verack", "ping", "pong"}:
            bucket = self._control_message_bucket
            if not bucket.can_consume(1, now):
                raise PeerProtocolError("peer exceeded control-message rate limit")
            bucket.consume(1)
            return

        message_bucket = self._data_message_bucket
        byte_bucket = self._data_byte_bucket
        message_ok = message_bucket.can_consume(1, now)
        bytes_ok = byte_bucket.can_consume(payload_length, now)
        if not message_ok or not bytes_ok:
            raise PeerProtocolError("peer exceeded data-message rate limit")
        message_bucket.consume(1)
        byte_bucket.consume(payload_length)

    async def _read_message(self) -> tuple[str, bytes]:
        header = await self.reader.readexactly(HEADER_SIZE)
        if header[:4] != self.magic:
            raise PeerProtocolError("message network magic mismatch")
        length = struct.unpack_from("<I", header, 16)[0]
        if length > self.max_payload:
            raise PeerProtocolError("message payload exceeds configured limit")
        _validate_control_payload_length(header[4:16], length)
        command = header[4:16].split(b"\x00", 1)[0].decode("ascii")
        self._consume_inbound_budget(command, length)

        reservation = None
        if self._receive_resource_budgets is not None:
            if self._pending_receive_reservation is not None:
                raise PeerProtocolError("previous inbound message reservation is still owned")
            peer_budget, node_budget = self._receive_resource_budgets
            reservation = reserve_resources(
                (
                    (peer_budget, 1, HEADER_SIZE + length),
                    (node_budget, 1, HEADER_SIZE + length),
                )
            )
            if reservation is None:
                raise PeerProtocolError("inbound resource budget exhausted")

        try:
            payload = await self.reader.readexactly(length)
            try:
                message = decode_message(
                    header + payload, self.magic, max_payload=self.max_payload
                )
            except ValueError as exc:
                raise PeerProtocolError(str(exc)) from exc
            self._pending_receive_reservation = reservation
            return message
        except BaseException:
            if reservation is not None:
                reservation.release()
            raise

    async def handle_message(self, command: str, payload: bytes) -> None:
        """Dispatch a message and release its receive reservation on completion."""
        try:
            await self._handle_message(command, payload)
        finally:
            reservation = self._pending_receive_reservation
            self._pending_receive_reservation = None
            if reservation is not None:
                reservation.release()

    async def _handle_message(self, command: str, payload: bytes) -> None:
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
        if not self._closed:
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
    control_messages_per_second: float = 20.0,
    control_message_burst: float = 40.0,
    data_messages_per_second: float = 20.0,
    data_message_burst: float = 40.0,
    data_bytes_per_second: float = 2 * 1024 * 1024,
    data_bytes_burst: float = 4 * 1024 * 1024,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> PeerConnection:
    """Open one outbound TCP connection and return its configured peer session.

    The caller must run ``await peer.run()`` (normally in a retained task) to
    execute the handshake and receive loop. The caller owns the session lifetime.
    """
    if not host or not isinstance(host, str):
        raise ValueError("host must be non-empty text")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    _validate_timeout("connect_timeout", connect_timeout)
    _validate_timeout("handshake_timeout", handshake_timeout)
    _validate_timeout("idle_timeout", idle_timeout)
    if (
        not isinstance(min_protocol_version, int)
        or isinstance(min_protocol_version, bool)
        or min_protocol_version < 1
    ):
        raise ValueError("minimum protocol version must be a positive integer")
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
        control_messages_per_second=control_messages_per_second,
        control_message_burst=control_message_burst,
        data_messages_per_second=data_messages_per_second,
        data_message_burst=data_message_burst,
        data_bytes_per_second=data_bytes_per_second,
        data_bytes_burst=data_bytes_burst,
        monotonic_clock=monotonic_clock,
    )
