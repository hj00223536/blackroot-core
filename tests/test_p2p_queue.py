import asyncio
import unittest

from src.blackroot_p2p_queue import MessageQueueClosed, ReservedMessageQueue
from src.blackroot_p2p_resources import ResourceBudget, reserve_resources


class ReservedMessageQueueTests(unittest.IsolatedAsyncioTestCase):
    def make_reservation(self):
        budget = ResourceBudget(max_items=4, max_bytes=256, name="queue")
        reservation = reserve_resources(((budget, 1, 32),))
        return budget, reservation

    async def test_queue_owns_reservation_until_consumer_releases(self):
        budget, reservation = self.make_reservation()
        queue = ReservedMessageQueue(max_items=1)
        queue.put_nowait("inv", b"payload", reservation)
        self.assertEqual(queue.qsize, 1)
        self.assertEqual((budget.items_in_use, budget.bytes_in_use), (1, 32))
        message = await queue.get()
        self.assertEqual((message.command, message.payload), ("inv", b"payload"))
        self.assertEqual((budget.items_in_use, budget.bytes_in_use), (1, 32))
        try:
            message.release()
        finally:
            queue.task_done()
        await queue.join()
        self.assertEqual((budget.items_in_use, budget.bytes_in_use), (0, 0))

    async def test_full_queue_keeps_reservation_with_caller(self):
        budget1, reservation1 = self.make_reservation()
        budget2, reservation2 = self.make_reservation()
        queue = ReservedMessageQueue(max_items=1)
        queue.put_nowait("inv", b"one", reservation1)
        with self.assertRaises(asyncio.QueueFull):
            queue.put_nowait("inv", b"two", reservation2)
        self.assertFalse(reservation2.released)
        reservation2.release()
        message = await queue.get()
        message.release()
        queue.task_done()
        self.assertEqual((budget1.items_in_use, budget1.bytes_in_use), (0, 0))
        self.assertEqual((budget2.items_in_use, budget2.bytes_in_use), (0, 0))

    async def test_close_releases_queued_messages_and_wakes_consumer(self):
        budget, reservation = self.make_reservation()
        queue = ReservedMessageQueue(max_items=2)
        waiting = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        queue.put_nowait("inv", b"payload", reservation)
        queue.close()
        self.assertEqual((budget.items_in_use, budget.bytes_in_use), (0, 0))
        self.assertIsNone(await waiting)
        self.assertTrue(queue.closed)
        with self.assertRaises(MessageQueueClosed):
            queue.put_nowait("inv", b"late", reservation)

    async def test_acknowledgement_releases_reservation_and_gates_next_get(self):
        budget, reservation = self.make_reservation()
        queue = ReservedMessageQueue(max_items=2)
        queue.put_nowait("inv", b"payload", reservation)
        message = await queue.get()
        with self.assertRaisesRegex(RuntimeError, "acknowledged"):
            await queue.get()
        self.assertFalse(reservation.released)
        queue.task_done()
        self.assertTrue(reservation.released)
        self.assertEqual((budget.items_in_use, budget.bytes_in_use), (0, 0))
        await queue.join()
        queue.close()
        self.assertIsNone(await queue.get())
        self.assertIsNone(await queue.get())

    async def test_close_does_not_release_message_already_owned_by_consumer(self):
        budget, reservation = self.make_reservation()
        queue = ReservedMessageQueue(max_items=1)
        queue.put_nowait("inv", b"payload", reservation)
        message = await queue.get()
        queue.close()
        self.assertEqual((budget.items_in_use, budget.bytes_in_use), (1, 32))
        message.release()
        queue.task_done()
        self.assertEqual((budget.items_in_use, budget.bytes_in_use), (0, 0))

    async def test_rejects_multiple_concurrent_consumers(self):
        queue = ReservedMessageQueue(max_items=1)
        first = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        with self.assertRaisesRegex(RuntimeError, "exactly one consumer"):
            await queue.get()
        queue.close()
        self.assertIsNone(await first)


if __name__ == "__main__":
    unittest.main()
