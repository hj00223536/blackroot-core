"""Bounded asyncio peer manager for inbound and outbound TCP sessions.

This module composes PeerConnection instances. It does not implement peer
discovery, encryption, cryptographic identity, or production anti-Sybil policy.
"""
from __future__ import annotations

import asyncio
import math
import inspect
import secrets
from collections import deque
from dataclasses import replace
from typing import Callable

from .blackroot_p2p import DEFAULT_MAX_PAYLOAD
from .blackroot_p2p_handshake import VersionMessage
from .blackroot_p2p_transport import MessageHandler, PeerConnection
from .blackroot_p2p_resources import ResourceBudget
from .blackroot_p2p_queue import ReservedMessageQueue


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
        control_messages_per_second: float = 20.0,
        control_message_burst: float = 40.0,
        data_messages_per_second: float = 20.0,
        data_message_burst: float = 40.0,
        data_bytes_per_second: float = 2 * 1024 * 1024,
        data_bytes_burst: float = 4 * 1024 * 1024,
        monotonic_clock: Callable[[], float] | None = None,
        send_node_budget: ResourceBudget | None = None,
        send_peer_budget_factory: Callable[[], ResourceBudget] | None = None,
        receive_node_budget: ResourceBudget | None = None,
        receive_peer_budget_factory: Callable[[], ResourceBudget] | None = None,
        application_queue_factory: Callable[[PeerConnection], ReservedMessageQueue] | None = None,
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
        for name, value in (
            ("control_messages_per_second", control_messages_per_second),
            ("control_message_burst", control_message_burst),
            ("data_messages_per_second", data_messages_per_second),
            ("data_message_burst", data_message_burst),
            ("data_bytes_per_second", data_bytes_per_second),
            ("data_bytes_burst", data_bytes_burst),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number")
        if monotonic_clock is not None and not callable(monotonic_clock):
            raise ValueError("monotonic_clock must be callable")
        for direction, node_budget, peer_factory in (
            ("send", send_node_budget, send_peer_budget_factory),
            ("receive", receive_node_budget, receive_peer_budget_factory),
        ):
            if node_budget is not None and not isinstance(node_budget, ResourceBudget):
                raise TypeError(f"{direction}_node_budget must be a ResourceBudget")
            if peer_factory is not None and not callable(peer_factory):
                raise TypeError(f"{direction}_peer_budget_factory must be callable")
            if (node_budget is None) != (peer_factory is None):
                raise ValueError(
                    f"{direction} node budget and peer budget factory must be configured together"
                )
        if application_queue_factory is not None and not callable(application_queue_factory):
            raise TypeError("application_queue_factory must be callable")
        if application_queue_factory is not None:
            if receive_node_budget is None:
                raise ValueError("application queue requires receive resource budgets")
            if on_message is not None or on_peer_message_factory is not None:
                raise ValueError("application queue cannot be combined with message callbacks")
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
        self.control_messages_per_second = control_messages_per_second
        self.control_message_burst = control_message_burst
        self.data_messages_per_second = data_messages_per_second
        self.data_message_burst = data_message_burst
        self.data_bytes_per_second = data_bytes_per_second
        self.data_bytes_burst = data_bytes_burst
        self.monotonic_clock = monotonic_clock
        self.send_node_budget = send_node_budget
        self.send_peer_budget_factory = send_peer_budget_factory
        self.receive_node_budget = receive_node_budget
        self.receive_peer_budget_factory = receive_peer_budget_factory
        self.application_queue_factory = application_queue_factory
        if on_peer_message_factory is not None and not callable(on_peer_message_factory):
            raise TypeError("on_peer_message_factory must be callable")
        self.on_message = on_message
        self.on_peer_message_factory = on_peer_message_factory
        self.on_peer_error = on_peer_error
        if on_peer_disconnected is not None and not callable(on_peer_disconnected):
            raise TypeError("on_peer_disconnected must be callable")
        self.on_peer_disconnected = on_peer_disconnected
        self._server: asyncio.AbstractServer | None = None
        self._server_starting = False
        self._server_start_complete = asyncio.Event()
        self._server_start_complete.set()
        self._peers: set[PeerConnection] = set()
        self._application_queues: dict[PeerConnection, ReservedMessageQueue] = {}
        self._application_worker_tasks: dict[PeerConnection, asyncio.Task] = {}
        self._application_workers_started: set[PeerConnection] = set()
        self._tasks: set[asyncio.Task] = set()
        self._outbound_reservations = 0
        self._closing = False
        self._close_complete = asyncio.Event()
        self._close_task: asyncio.Task | None = None
        self._background_errors: deque[Exception] = deque(maxlen=100)

    @property
    def background_errors(self) -> tuple[Exception, ...]:
        """Recent peer-task and callback failures, oldest first (bounded)."""
        return tuple(self._background_errors)

    @property
    def peer_count(self) -> int:
        """Number of currently managed peer sessions."""
        return len(self._peers)

    @property
    def peers(self) -> tuple[PeerConnection, ...]:
        """Snapshot of managed peer sessions."""
        return tuple(self._peers)

    def application_queue_for(self, peer: PeerConnection) -> ReservedMessageQueue:
        """Return the opt-in bounded application queue associated with a peer."""
        try:
            return self._application_queues[peer]
        except KeyError as exc:
            raise KeyError("peer has no application message queue") from exc

    def start_application_worker(
        self, peer: PeerConnection, handler: Callable[[str, bytes], object]
    ) -> asyncio.Task:
        """Start the one retained consumer task for a peer's bounded queue.

        The worker is not restarted after failure. Handler failure closes the
        peer and queue; manager shutdown cancels and awaits active workers.
        """
        if self._closing:
            raise RuntimeError("peer manager is closing")
        if not callable(handler):
            raise TypeError("application handler must be callable")
        queue = self.application_queue_for(peer)
        if peer not in self._peers:
            raise RuntimeError("application worker requires a managed peer")
        if peer in self._application_workers_started:
            raise RuntimeError("application worker has already been started")
        self._application_workers_started.add(peer)

        async def consume_messages() -> None:
            try:
                while True:
                    async with queue.consume() as message:
                        if message is None:
                            return
                        result = handler(message.command, message.payload)
                        if inspect.isawaitable(result):
                            await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._background_errors.append(exc)
                try:
                    await self._report_error(exc)
                except Exception as callback_error:
                    self._background_errors.append(callback_error)
                queue.close()
                await peer.close()

        task = asyncio.create_task(consume_messages())
        self._application_worker_tasks[peer] = task

        def worker_finished(done: asyncio.Task) -> None:
            if self._application_worker_tasks.get(peer) is done:
                self._application_worker_tasks.pop(peer, None)

        task.add_done_callback(worker_finished)
        return task

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
        peer: PeerConnection | None = None
        try:
            send_budgets = None
            if self.send_peer_budget_factory is not None:
                peer_budget = self.send_peer_budget_factory()
                if not isinstance(peer_budget, ResourceBudget) or peer_budget is self.send_node_budget:
                    raise TypeError("send peer budget factory must return a distinct ResourceBudget")
                send_budgets = (peer_budget, self.send_node_budget)
            receive_budgets = None
            if self.receive_peer_budget_factory is not None:
                peer_budget = self.receive_peer_budget_factory()
                if not isinstance(peer_budget, ResourceBudget) or peer_budget is self.receive_node_budget:
                    raise TypeError("receive peer budget factory must return a distinct ResourceBudget")
                receive_budgets = (peer_budget, self.receive_node_budget)
            peer = PeerConnection(
                reader, writer, magic=self.magic, local_version=self._new_version(),
                max_payload=self.max_payload, handshake_timeout=self.handshake_timeout,
                idle_timeout=self.idle_timeout, min_protocol_version=self.min_protocol_version,
                on_message=self.on_message,
                control_messages_per_second=self.control_messages_per_second,
                control_message_burst=self.control_message_burst,
                data_messages_per_second=self.data_messages_per_second,
                data_message_burst=self.data_message_burst,
                data_bytes_per_second=self.data_bytes_per_second,
                data_bytes_burst=self.data_bytes_burst,
                send_resource_budgets=send_budgets,
                receive_resource_budgets=receive_budgets,
                **({"monotonic_clock": self.monotonic_clock}
                   if self.monotonic_clock is not None else {}),
            )
            if self.application_queue_factory is not None:
                queue = self.application_queue_factory(peer)
                if not isinstance(queue, ReservedMessageQueue):
                    raise TypeError("application_queue_factory must return a ReservedMessageQueue")
                if not queue.is_pristine or any(
                    existing is queue for existing in self._application_queues.values()
                ):
                    raise ValueError("application_queue_factory must return a fresh unused queue")
                self._application_queues[peer] = queue

                def enqueue_application_message(command: str, payload: bytes) -> None:
                    reservation = peer.take_receive_reservation()
                    try:
                        queue.put_nowait(command, payload, reservation)
                    except BaseException:
                        if not reservation.released:
                            reservation.release()
                        raise

                peer.on_message = enqueue_application_message
            elif self.on_peer_message_factory is not None:
                handler = self.on_peer_message_factory(peer)
                if not callable(handler):
                    raise TypeError("on_peer_message_factory must return a callable")
                peer.on_message = handler
            return peer
        except BaseException:
            if peer is not None:
                queue = self._application_queues.pop(peer, None)
                if queue is not None:
                    queue.close()
            # Budget factories and PeerConnection construction are also part
            # of setup: the caller retains socket ownership until success.
            try:
                writer.close()
            except Exception:
                pass
            raise

    def _track(self, peer: PeerConnection) -> PeerConnection:
        self._peers.add(peer)
        coroutine = self._run_peer(peer)
        try:
            task = asyncio.create_task(coroutine)
        except BaseException:
            coroutine.close()
            self._peers.discard(peer)
            try:
                peer.writer.close()
            except Exception:
                pass
            raise
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._background_errors.append(exc)
            try:
                await self._report_error(exc)
            except Exception as callback_error:
                self._background_errors.append(callback_error)
        finally:
            queue = self._application_queues.pop(peer, None)
            if queue is not None:
                queue.close()
            worker = self._application_worker_tasks.get(peer)
            current = asyncio.current_task()
            if worker is not None and worker is not current:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            try:
                await peer.close()
            except Exception as close_error:
                self._background_errors.append(close_error)
            finally:
                self._application_workers_started.discard(peer)
                self._peers.discard(peer)
                if self.on_peer_disconnected is not None:
                    try:
                        result = self.on_peer_disconnected(peer)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as callback_error:
                        self._background_errors.append(callback_error)

    async def start_server(self, host: str = "127.0.0.1", port: int = 0) -> tuple:
        """Start one inbound listener; serialize startup against close and peers."""
        if self._closing:
            raise RuntimeError("peer manager is closing")
        if self._server is not None or self._server_starting:
            raise RuntimeError("peer listener is already started or starting")
        self._server_starting = True
        self._server_start_complete.clear()
        server = None
        try:
            server = await asyncio.start_server(self._accept, host, port)
            if self._closing:
                server.close()
                await server.wait_closed()
                raise RuntimeError("peer manager closed during listener startup")
            if not server.sockets:
                server.close()
                await server.wait_closed()
                raise OSError("peer listener did not bind a socket")
            self._server = server
            return server.sockets[0].getsockname()
        except BaseException:
            if server is not None and self._server is not server:
                server.close()
                await server.wait_closed()
            raise
        finally:
            self._server_starting = False
            self._server_start_complete.set()

    def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._closing or self._load() >= self.max_peers:
            writer.close()
            return
        peer: PeerConnection | None = None
        try:
            peer = self._new_peer(reader, writer)
            self._track(peer)
        except Exception as exc:
            self._background_errors.append(exc)
            if peer is not None:
                self._peers.discard(peer)
            # Server callbacks are synchronous; record the bounded error and
            # close the transport instead of leaking an unhandled callback error.
            try:
                writer.close()
            except Exception:
                pass

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
        """Await one shielded shutdown task shared by all close callers.

        Cancelling an individual caller must not cancel the manager's teardown
        or signal completion before sockets, peer sessions, and workers stop.
        """
        if self._close_task is None:
            self._closing = True

            async def run_shutdown() -> None:
                try:
                    await self._close_impl()
                finally:
                    self._close_complete.set()

            # No await occurs between checking and assigning this task, so
            # concurrent callers on this event loop join the same operation.
            self._close_task = asyncio.create_task(run_shutdown())
        await asyncio.shield(self._close_task)

    async def _close_impl(self) -> None:
        """Perform manager shutdown once; callers synchronize through close()."""
        # A bind already in progress must finish its own close path before
        # shutdown can report completion; start_server rejects late installs.
        await self._server_start_complete.wait()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        # Stop queue admission and release queued payloads before peer shutdown.
        for queue in tuple(self._application_queues.values()):
            queue.close()
        peers = tuple(self._peers)
        await asyncio.gather(*(peer.close() for peer in peers), return_exceptions=True)
        tasks = tuple(self._tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        worker_tasks = tuple(self._application_worker_tasks.values())
        for task in worker_tasks:
            task.cancel()
        if worker_tasks:
            await asyncio.gather(*worker_tasks, return_exceptions=True)
        self._application_worker_tasks.clear()
        self._peers.clear()
