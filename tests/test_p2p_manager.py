import asyncio
import unittest

from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_manager import PeerManager
from src.blackroot_p2p_resources import ResourceBudget, reserve_resources
from src.blackroot_p2p_queue import ReservedMessageQueue

MAGIC = bytes.fromhex("b2a1c3d4")


def version():
    return VersionMessage(1, 0, 1_800_000_000, 42, 0, "/blackroot:test/")


class PeerManagerConfigurationTests(unittest.TestCase):
    def test_rejects_non_finite_boolean_and_non_positive_timeouts(self):
        for name in ("connect_timeout", "handshake_timeout", "idle_timeout"):
            for value in (True, float("nan"), float("inf"), float("-inf"), 0, -1):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, "finite positive"):
                        PeerManager(magic=MAGIC, local_version=version(), **{name: value})

    def test_rejects_invalid_payload_limits(self):
        for value in (True, -1, "100", 2**32):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "max_payload"):
                    PeerManager(magic=MAGIC, local_version=version(), max_payload=value)

    def test_rejects_invalid_minimum_protocol_version(self):
        for value in (True, 0, -1, "1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "minimum protocol"):
                    PeerManager(magic=MAGIC, local_version=version(), min_protocol_version=value)

    def test_rejects_invalid_rate_limit_settings(self):
        for name in (
            "control_messages_per_second",
            "control_message_burst",
            "data_messages_per_second",
            "data_message_burst",
            "data_bytes_per_second",
            "data_bytes_burst",
        ):
            for value in (True, 0, -1, float("nan"), float("inf")):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, "finite positive"):
                        PeerManager(
                            magic=MAGIC,
                            local_version=version(),
                            **{name: value},
                        )

    def test_rejects_non_callable_rate_limit_clock(self):
        with self.assertRaisesRegex(ValueError, "monotonic_clock must be callable"):
            PeerManager(
                magic=MAGIC,
                local_version=version(),
                monotonic_clock=123,
            )


    def test_resource_budget_pair_requires_node_and_peer_factory_together(self):
        node_budget = ResourceBudget(max_items=4, max_bytes=4096, name="node")
        with self.assertRaisesRegex(ValueError, "configured together"):
            PeerManager(
                magic=MAGIC, local_version=version(),
                send_node_budget=node_budget,
            )
        with self.assertRaisesRegex(ValueError, "configured together"):
            PeerManager(
                magic=MAGIC, local_version=version(),
                receive_peer_budget_factory=lambda: ResourceBudget(
                    max_items=1, max_bytes=1024, name="peer"
                ),
            )

    def test_manager_injects_shared_node_and_fresh_peer_budgets(self):
        send_node = ResourceBudget(max_items=8, max_bytes=8192, name="send-node")
        receive_node = ResourceBudget(max_items=8, max_bytes=8192, name="receive-node")
        manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            send_node_budget=send_node,
            send_peer_budget_factory=lambda: ResourceBudget(
                max_items=2, max_bytes=2048, name="send-peer"
            ),
            receive_node_budget=receive_node,
            receive_peer_budget_factory=lambda: ResourceBudget(
                max_items=2, max_bytes=2048, name="receive-peer"
            ),
        )
        first = manager._new_peer(asyncio.StreamReader(), object())
        second = manager._new_peer(asyncio.StreamReader(), object())
        self.assertIs(first._send_resource_budgets[1], send_node)
        self.assertIs(second._send_resource_budgets[1], send_node)
        self.assertIsNot(first._send_resource_budgets[0], second._send_resource_budgets[0])
        self.assertIs(first._receive_resource_budgets[1], receive_node)
        self.assertIs(second._receive_resource_budgets[1], receive_node)
        self.assertIsNot(first._receive_resource_budgets[0], second._receive_resource_budgets[0])

    def test_application_queue_requires_receive_budgets_and_exclusive_handler(self):
        with self.assertRaisesRegex(ValueError, "requires receive resource budgets"):
            PeerManager(
                magic=MAGIC, local_version=version(),
                application_queue_factory=lambda peer: ReservedMessageQueue(max_items=2),
            )
        receive_node = ResourceBudget(max_items=8, max_bytes=8192, name="receive-node")
        factory = lambda: ResourceBudget(max_items=4, max_bytes=4096, name="receive-peer")
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            PeerManager(
                magic=MAGIC, local_version=version(),
                receive_node_budget=receive_node,
                receive_peer_budget_factory=factory,
                application_queue_factory=lambda peer: ReservedMessageQueue(max_items=2),
                on_message=lambda command, payload: None,
            )

    def test_rejects_non_callable_handlers(self):
        for kwargs in ({"on_message": 1}, {"on_peer_error": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TypeError):
                PeerManager(magic=MAGIC, local_version=version(), **kwargs)


class PeerManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server_manager = PeerManager(
            magic=MAGIC, local_version=version(), max_peers=2,
            handshake_timeout=1, idle_timeout=5,
        )
        self.client_manager = PeerManager(
            magic=MAGIC, local_version=version(), max_peers=2,
            handshake_timeout=1, idle_timeout=5,
        )

    async def asyncTearDown(self):
        await self.client_manager.close()
        await self.server_manager.close()

    async def test_application_queue_receives_transferred_peer_reservation(self):
        node_budget = ResourceBudget(max_items=8, max_bytes=8192, name="receive-node")
        peer_budgets = []
        manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            receive_node_budget=node_budget,
            receive_peer_budget_factory=lambda: peer_budgets.append(
                ResourceBudget(max_items=4, max_bytes=4096, name="receive-peer")
            ) or peer_budgets[-1],
            application_queue_factory=lambda peer: ReservedMessageQueue(max_items=2),
        )
        peer = manager._new_peer(asyncio.StreamReader(), object())
        peer.handshake.local_version_sent = True
        peer.handshake.remote_version = version()
        peer.handshake.local_verack_sent = True
        peer.handshake.remote_verack_received = True
        peer.handshake._refresh_complete()
        reservation = reserve_resources(
            ((peer._receive_resource_budgets[0], 1, 35),
             (peer._receive_resource_budgets[1], 1, 35))
        )
        peer._pending_receive_reservation = reservation
        await peer.handle_message("inv", b"inventory")
        queue = manager.application_queue_for(peer)
        self.assertEqual(queue.qsize, 1)
        self.assertFalse(reservation.released)
        self.assertEqual(node_budget.bytes_in_use, 35)
        message = await queue.get()
        self.assertEqual((message.command, message.payload), ("inv", b"inventory"))
        queue.task_done()
        self.assertTrue(reservation.released)
        self.assertEqual(node_budget.bytes_in_use, 0)
        queue.close()

    async def test_application_queue_full_releases_rejected_message_reservation(self):
        node_budget = ResourceBudget(max_items=8, max_bytes=8192, name="receive-node")
        manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            receive_node_budget=node_budget,
            receive_peer_budget_factory=lambda: ResourceBudget(
                max_items=4, max_bytes=4096, name="receive-peer"
            ),
            application_queue_factory=lambda peer: ReservedMessageQueue(max_items=1),
        )
        peer = manager._new_peer(asyncio.StreamReader(), object())
        peer.handshake.local_version_sent = True
        peer.handshake.remote_version = version()
        peer.handshake.local_verack_sent = True
        peer.handshake.remote_verack_received = True
        peer.handshake._refresh_complete()
        peer_budget, shared_budget = peer._receive_resource_budgets
        first = reserve_resources(((peer_budget, 1, 30), (shared_budget, 1, 30)))
        peer._pending_receive_reservation = first
        await peer.handle_message("inv", b"first")
        rejected = reserve_resources(((peer_budget, 1, 31), (shared_budget, 1, 31)))
        peer._pending_receive_reservation = rejected
        with self.assertRaises(asyncio.QueueFull):
            await peer.handle_message("inv", b"second")
        self.assertTrue(rejected.released)
        self.assertEqual(node_budget.bytes_in_use, 30)
        queue = manager.application_queue_for(peer)
        queue.close()
        self.assertTrue(first.released)
        self.assertEqual(node_budget.bytes_in_use, 0)

    async def test_inbound_and_outbound_peers_complete_handshake(self):
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        outbound = await self.client_manager.connect(host, port)

        async def wait_connected():
            while not (outbound.connected and self.server_manager.peer_count == 1):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_connected(), timeout=2)
        inbound = self.server_manager.peers[0]
        self.assertTrue(inbound.connected)
        self.assertTrue(outbound.connected)
        self.assertNotEqual(
            inbound.handshake.local_version.nonce,
            outbound.handshake.local_version.nonce,
        )

    async def test_manager_propagates_rate_limits_to_inbound_and_outbound_peers(self):
        clock = lambda: 123.0
        self.server_manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            max_peers=2,
            handshake_timeout=1,
            idle_timeout=5,
            control_messages_per_second=3,
            control_message_burst=4,
            data_messages_per_second=5,
            data_message_burst=6,
            data_bytes_per_second=7,
            data_bytes_burst=8,
            monotonic_clock=clock,
        )
        self.client_manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            max_peers=2,
            handshake_timeout=1,
            idle_timeout=5,
            control_messages_per_second=9,
            control_message_burst=10,
            data_messages_per_second=11,
            data_message_burst=12,
            data_bytes_per_second=13,
            data_bytes_burst=14,
        )
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        outbound = await self.client_manager.connect(host, port)

        async def wait_connected():
            while not (outbound.connected and self.server_manager.peer_count == 1):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_connected(), timeout=2)
        inbound = self.server_manager.peers[0]
        self.assertEqual(outbound._control_message_bucket.rate, 9)
        self.assertEqual(outbound._data_message_bucket.capacity, 12)
        self.assertEqual(outbound._data_byte_bucket.rate, 13)
        self.assertEqual(inbound._control_message_bucket.rate, 3)
        self.assertEqual(inbound._data_message_bucket.capacity, 6)
        self.assertEqual(inbound._data_byte_bucket.rate, 7)
        self.assertIs(inbound._monotonic_clock, clock)

    async def test_outbound_reservation_is_released_when_dial_fails(self):
        from unittest.mock import patch

        async def fail_dial(*args, **kwargs):
            raise OSError("dial failed")

        with patch("src.blackroot_p2p_manager.asyncio.open_connection", side_effect=fail_dial):
            with self.assertRaisesRegex(OSError, "dial failed"):
                await self.client_manager.connect("127.0.0.1", 1)

        self.assertEqual(self.client_manager._outbound_reservations, 0)
        self.assertEqual(self.client_manager.peer_count, 0)

    async def test_outbound_reservation_is_released_when_dial_is_cancelled(self):
        from unittest.mock import patch

        dial_started = asyncio.Event()
        never_complete = asyncio.Event()

        async def blocked_dial(*args, **kwargs):
            dial_started.set()
            await never_complete.wait()

        with patch("src.blackroot_p2p_manager.asyncio.open_connection", side_effect=blocked_dial):
            task = asyncio.create_task(self.client_manager.connect("127.0.0.1", 1))
            await asyncio.wait_for(dial_started.wait(), timeout=1)
            self.assertEqual(self.client_manager._outbound_reservations, 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(self.client_manager._outbound_reservations, 0)
        self.assertEqual(self.client_manager.peer_count, 0)

    async def test_close_during_pending_dial_prevents_peer_registration(self):
        from unittest.mock import patch
        from unittest.mock import MagicMock

        dial_started = asyncio.Event()
        finish_dial = asyncio.Event()
        writer = MagicMock()

        async def blocked_dial(*args, **kwargs):
            dial_started.set()
            await finish_dial.wait()
            return asyncio.StreamReader(), writer

        with patch("src.blackroot_p2p_manager.asyncio.open_connection", side_effect=blocked_dial):
            task = asyncio.create_task(self.client_manager.connect("127.0.0.1", 1))
            await asyncio.wait_for(dial_started.wait(), timeout=1)
            self.assertEqual(self.client_manager._outbound_reservations, 1)
            await self.client_manager.close()
            finish_dial.set()
            with self.assertRaisesRegex(RuntimeError, "closed during connect"):
                await task

        writer.close.assert_called_once_with()
        self.assertEqual(self.client_manager._outbound_reservations, 0)
        self.assertEqual(self.client_manager.peer_count, 0)

    async def test_concurrent_outbound_dials_cannot_oversubscribe_peer_cap(self):
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        results = await asyncio.gather(
            *(self.client_manager.connect(host, port) for _ in range(8)),
            return_exceptions=True,
        )

        successful = [item for item in results if not isinstance(item, BaseException)]
        rejected = [item for item in results if isinstance(item, RuntimeError)]
        self.assertEqual(len(successful), self.client_manager.max_peers)
        self.assertEqual(len(rejected), 8 - self.client_manager.max_peers)
        self.assertEqual(self.client_manager.peer_count, self.client_manager.max_peers)
        self.assertEqual(self.client_manager._outbound_reservations, 0)

    async def test_mixed_inbound_and_outbound_race_respects_shared_peer_cap(self):
        manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            max_peers=1,
            handshake_timeout=1,
            idle_timeout=5,
        )
        external_writers = []

        def hold_external_connection(reader, writer):
            external_writers.append(writer)

        external_server = await asyncio.start_server(
            hold_external_connection, "127.0.0.1", 0
        )
        external_host, external_port, *_ = external_server.sockets[0].getsockname()
        inbound_host, inbound_port, *_ = await manager.start_server("127.0.0.1", 0)
        inbound_writer = None
        try:
            outbound_result, inbound_result = await asyncio.gather(
                manager.connect(external_host, external_port),
                asyncio.open_connection(inbound_host, inbound_port),
                return_exceptions=True,
            )
            if not isinstance(inbound_result, BaseException):
                _, inbound_writer = inbound_result

            self.assertLessEqual(manager._load(), 1)
            self.assertLessEqual(manager.peer_count, 1)
            self.assertEqual(manager._outbound_reservations, 0)
            self.assertTrue(
                not isinstance(outbound_result, BaseException)
                or isinstance(outbound_result, RuntimeError)
            )
        finally:
            if inbound_writer is not None:
                inbound_writer.close()
                await asyncio.gather(inbound_writer.wait_closed(), return_exceptions=True)
            await manager.close()
            external_server.close()
            await external_server.wait_closed()
            for writer in external_writers:
                writer.close()
            if external_writers:
                await asyncio.gather(
                    *(writer.wait_closed() for writer in external_writers),
                    return_exceptions=True,
                )

    async def test_inbound_accept_burst_cannot_oversubscribe_peer_cap(self):
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        clients = await asyncio.gather(
            *(asyncio.open_connection(host, port) for _ in range(8))
        )
        try:
            await asyncio.sleep(0.05)
            self.assertLessEqual(
                self.server_manager.peer_count,
                self.server_manager.max_peers,
            )
            self.assertEqual(self.server_manager.peer_count, self.server_manager.max_peers)
            self.assertEqual(self.server_manager._load(), self.server_manager.max_peers)
        finally:
            for _, writer in clients:
                writer.close()
            await asyncio.gather(
                *(writer.wait_closed() for _, writer in clients),
                return_exceptions=True,
            )

        async def wait_for_cleanup():
            while self.server_manager.peer_count:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_cleanup(), timeout=2)
        self.assertEqual(self.server_manager.peer_count, 0)

    async def test_slow_inbound_handshake_is_timed_out_and_releases_peer_slot(self):
        manager = PeerManager(
            magic=MAGIC,
            local_version=version(),
            max_peers=1,
            handshake_timeout=0.03,
            idle_timeout=1,
        )
        host, port, *_ = await manager.start_server("127.0.0.1", 0)
        reader, writer = await asyncio.open_connection(host, port)
        try:
            async def wait_admitted():
                while manager.peer_count != 1:
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(wait_admitted(), timeout=1)
            self.assertEqual(manager.peer_count, 1)

            async def wait_released():
                while manager.peer_count:
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(wait_released(), timeout=1)
            self.assertEqual(manager.peer_count, 0)
            self.assertTrue(
                any("handshake timeout" in str(error) for error in manager.background_errors)
            )
        finally:
            writer.close()
            await asyncio.gather(writer.wait_closed(), return_exceptions=True)
            await manager.close()

    async def test_enforces_outbound_peer_limit(self):
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        await self.client_manager.connect(host, port)
        await self.client_manager.connect(host, port)
        with self.assertRaisesRegex(RuntimeError, "maximum peer count"):
            await self.client_manager.connect(host, port)

    async def test_disconnect_callback_runs_for_removed_peer(self):
        disconnected = []
        callback_done = asyncio.Event()

        async def on_disconnected(peer):
            disconnected.append(peer)
            callback_done.set()

        self.server_manager.on_peer_disconnected = on_disconnected
        host, port, *_ = await self.server_manager.start_server("127.0.0.1", 0)
        outbound = await self.client_manager.connect(host, port)

        async def wait_connected():
            while not (outbound.connected and self.server_manager.peer_count == 1):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_connected(), timeout=2)
        await self.client_manager.close()
        await asyncio.wait_for(callback_done.wait(), timeout=2)
        self.assertEqual(len(disconnected), 1)
        self.assertFalse(disconnected[0].connected)

    async def test_close_stops_listener_and_removes_peers(self):
        await self.server_manager.start_server("127.0.0.1", 0)
        self.assertTrue(self.server_manager.listening)
        await self.server_manager.close()
        self.assertFalse(self.server_manager.listening)
        self.assertEqual(self.server_manager.peer_count, 0)

    async def test_unexpected_peer_failure_is_recorded_and_peer_is_removed(self):
        class FailingPeer:
            closed = False

            async def run(self):
                raise RuntimeError("unexpected handler failure")

            async def close(self):
                self.closed = True

        reported = []

        def on_error(error):
            reported.append(error)

        self.server_manager.on_peer_error = on_error
        peer = FailingPeer()
        task = self.server_manager._track(peer)
        task_ref = next(iter(self.server_manager._tasks))
        await asyncio.wait_for(asyncio.gather(task_ref), timeout=1)

        self.assertTrue(peer.closed)
        self.assertEqual(self.server_manager.peer_count, 0)
        self.assertEqual(len(reported), 1)
        self.assertIsInstance(reported[0], RuntimeError)
        self.assertEqual(len(self.server_manager.background_errors), 1)

    async def test_callback_failures_do_not_skip_peer_cleanup(self):
        class FailingPeer:
            closed = False

            async def run(self):
                raise ValueError("peer run failed")

            async def close(self):
                self.closed = True

        def broken_error_callback(error):
            raise RuntimeError("error callback failed")

        def broken_disconnect_callback(peer):
            raise LookupError("disconnect callback failed")

        self.server_manager.on_peer_error = broken_error_callback
        self.server_manager.on_peer_disconnected = broken_disconnect_callback
        peer = FailingPeer()
        self.server_manager._track(peer)
        task = next(iter(self.server_manager._tasks))
        await asyncio.wait_for(asyncio.gather(task), timeout=1)

        self.assertTrue(peer.closed)
        self.assertEqual(self.server_manager.peer_count, 0)
        self.assertEqual(
            [type(error) for error in self.server_manager.background_errors],
            [ValueError, RuntimeError, LookupError],
        )

    async def test_background_error_history_is_bounded(self):
        for index in range(105):
            self.server_manager._background_errors.append(RuntimeError(str(index)))
        self.assertEqual(len(self.server_manager.background_errors), 100)
        self.assertEqual(str(self.server_manager.background_errors[0]), "5")


if __name__ == "__main__":
    unittest.main()
