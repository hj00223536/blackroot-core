import asyncio
import unittest
from unittest.mock import Mock

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target, check_proof_of_work
from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_inventory import decode_inventory
from src.blackroot_p2p_manager import PeerManager
from src.blackroot_p2p_multi_peer_sync import MultiPeerBlockScheduler
from src.blackroot_p2p_node_service import NodePeerSyncService

MAGIC = bytes.fromhex("b2a1c3d4")
BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def make_block():
    from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
    coinbase = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), b"\\x01\\x01"),),
        (TxOutput(1, b"miner"),),
    )
    for nonce in range(10000):
        header = BlockHeader(1, ZERO_HASH, merkle_root([coinbase.txid]), 1, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, (coinbase,))
    raise AssertionError("unable to mine integration genesis")


def version(nonce):
    return VersionMessage(1, 0, 1_800_000_000, nonce, 0, "/blackroot:three-node/")


class ThreeNodeLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.block = make_block()
        self.chain = HeaderChain(POW_LIMIT, self.block.header)
        self.store = Mock()
        self.store.connect_validated_block.return_value = 0
        self.scheduler = MultiPeerBlockScheduler(self.chain, self.store)
        self.sync_service = NodePeerSyncService(self.scheduler)
        self.remote_requests = {"peer-1": asyncio.Event(), "peer-2": asyncio.Event()}
        self.remote_managers = []

        def remote_factory(peer_name):
            async def handler(peer, command, payload):
                if command != "getdata":
                    return
                items = decode_inventory(payload)
                if any(item.item_hash == self.block.header.hash for item in items):
                    self.remote_requests[peer_name].set()
                    await peer.send("block", self.block.serialize())
            return lambda peer: (
                lambda command, payload: handler(peer, command, payload)
            )

        for index, peer_name in enumerate(("peer-1", "peer-2"), start=1):
            manager = PeerManager(
                magic=MAGIC,
                local_version=version(100 + index),
                max_peers=2,
                handshake_timeout=2,
                idle_timeout=5,
                on_peer_message_factory=remote_factory(peer_name),
            )
            await manager.start_server("127.0.0.1", 0)
            self.remote_managers.append(manager)

        self.central = PeerManager(
            magic=MAGIC,
            local_version=version(200),
            max_peers=3,
            handshake_timeout=2,
            idle_timeout=5,
            on_peer_message_factory=self.sync_service.on_peer_message_factory,
            on_peer_disconnected=self.sync_service.peer_disconnected,
        )
        self.peer_map = {}
        self.peer_names = {}
        for peer_name, manager in zip(("peer-1", "peer-2"), self.remote_managers):
            host, port, *_ = manager.sockets[0].getsockname()
            peer = await self.central.connect(host, port)
            self.peer_map[peer_name] = peer
            self.peer_names[peer] = peer_name

        async def wait_handshakes():
            while not all(peer.connected for peer in self.peer_map.values()):
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait_handshakes(), timeout=2)

    async def asyncTearDown(self):
        await self.central.close()
        for manager in self.remote_managers:
            await manager.close()

    async def test_three_real_loopback_nodes_download_from_assigned_source(self):
        selected = await self.scheduler.request_block(
            self.block.header.hash, self.sync_service.peers
        )
        selected_name = self.peer_names[selected]
        await asyncio.wait_for(self.remote_requests[selected_name].wait(), timeout=2)
        async def wait_for_store():
            while self.store.connect_validated_block.call_count == 0:
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait_for_store(), timeout=2)
        other = "peer-2" if selected_name == "peer-1" else "peer-1"
        self.assertFalse(self.remote_requests[other].is_set())
        self.store.connect_validated_block.assert_called_once()
        self.assertEqual(self.scheduler.pool.pending_hashes, ())
        self.assertEqual(self.scheduler.tracker.pending_hashes, ())


if __name__ == "__main__":
    unittest.main()
