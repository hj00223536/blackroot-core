"""Bounded application queue for inbound P2P messages with transferred reservations.

The queue is deliberately single-consumer. It does not create worker tasks;
the embedding runtime owns and supervises its one consumer task.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .blackroot_p2p_resources import ResourceReservation


class MessageQueueClosed(RuntimeError):
    """Raised when a closed application message queue is used."""


@dataclass
class ReservedMessage:
    """A queued message whose payload remains charged until released."""

    command: str
    payload: bytes
    reservation: ResourceReservation
    _released: bool = False

    def release(self) -> None:
        if self._released:
            raise RuntimeError("queued message released more than once")
        self.reservation.release()
        self._released = True

    def __enter__(self) -> "ReservedMessage":
        if self._released:
            raise RuntimeError("cannot enter a released queued message")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class ReservedMessageQueue:
    """Bounded FIFO that owns reservations while messages are queued/processed.

    Ownership transfers to the queue only after put_nowait succeeds. If the
    queue is full or closed, the caller retains the reservation and must
    release it or retry. One consumer is supported so close can wake it with
    a sentinel without creating unbounded waiter/task state.
    """

    _STOP = object()

    def __init__(self, *, max_items: int) -> None:
        if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items < 1:
            raise ValueError("max_items must be a positive integer")
        self.max_items = max_items
        self._queue: asyncio.Queue[ReservedMessage | object] = asyncio.Queue(
            maxsize=max_items
        )
        self._closed = False
        self._consumer_task: asyncio.Task | None = None
        self._inflight: ReservedMessage | None = None

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def closed(self) -> bool:
        return self._closed

    def put_nowait(
        self, command: str, payload: bytes, reservation: ResourceReservation
    ) -> None:
        if self._closed:
            raise MessageQueueClosed("message queue is closed")
        if not isinstance(command, str) or not command:
            raise ValueError("command must be non-empty text")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if not isinstance(reservation, ResourceReservation):
            raise TypeError("reservation must be a ResourceReservation")
        if reservation.released:
            raise ValueError("reservation is already released")
        self._queue.put_nowait(ReservedMessage(command, payload, reservation))

    async def get(self) -> ReservedMessage | None:
        """Return the next owned message; None is the close sentinel."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("message queue consumer must run in an asyncio task")
        if self._consumer_task is None:
            self._consumer_task = task
        elif self._consumer_task is not task:
            raise RuntimeError("ReservedMessageQueue supports exactly one consumer")
        if self._inflight is not None:
            raise RuntimeError("previous message must be acknowledged before the next get")
        if self._closed and self._queue.empty():
            return None
        item = await self._queue.get()
        if item is self._STOP:
            self._queue.task_done()
            return None
        assert isinstance(item, ReservedMessage)
        if self._inflight is not None:
            raise RuntimeError("previous message must be acknowledged before the next get")
        self._inflight = item
        return item

    def task_done(self) -> None:
        """Acknowledge the current message and release its reservation."""
        if self._inflight is None:
            raise ValueError("task_done called without an in-flight message")
        if not self._inflight._released:
            self._inflight.release()
        self._inflight = None
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def close(self) -> None:
        """Close admission, release queued messages, and wake a waiting consumer.

        A message already returned by get() remains owned by that consumer and
        must be released there. Callers should cancel/await the worker before
        destroying the event loop.
        """
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                if isinstance(item, ReservedMessage):
                    item.release()
                self._queue.task_done()
        # At most one consumer is supported, and the queue was drained above.
        self._queue.put_nowait(self._STOP)
