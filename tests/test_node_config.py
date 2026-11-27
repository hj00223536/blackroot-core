import json
import tempfile
import unittest
from pathlib import Path

from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_consensus import decode_compact_target
from src.blackroot_node_config import TestnetConfig
from src.blackroot_node import parse_connect_endpoint
from src.blackroot_p2p_handshake import VersionMessage

BITS = 0x207FFFFF
LIMIT = decode_compact_target(BITS)


def valid_header():
    # Fixed vector mined in-process solely for this unit fixture.
    from src.blackroot_consensus import check_proof_of_work
    for nonce in range(10000):
        header = BlockHeader(1, ZERO_HASH, b"t" * 32, 1, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, LIMIT):
            return header
    raise AssertionError("could not create test fixture")


def config(**overrides):
    header = valid_header()
    values = dict(
        network_id="blackroot-local-testnet-candidate",
        message_magic=bytes.fromhex("b2a1c3d4"),
        protocol_version=1,
        genesis_header=header,
        genesis_hash=header.hash,
        pow_limit=LIMIT,
        p2p_port=0,
        max_peers=4,
    )
    values.update(overrides)
    return TestnetConfig(**values)


class TestnetConfigTests(unittest.TestCase):
    def test_explicit_config_creates_manager_with_matching_identity(self):
        settings = config()
        version = VersionMessage(1, 0, 1, 2, 0, "/blackroot:config-test/")
        manager = settings.create_peer_manager(version)
        self.assertEqual(manager.magic, settings.message_magic)
        self.assertEqual(manager.local_version.protocol_version, 1)
        self.assertEqual(manager.max_peers, 4)

    def test_protocol_version_and_payload_respect_p2p_bounds(self):
        with self.assertRaisesRegex(ValueError, "positive int32"):
            config(protocol_version=0x80000000)
        with self.assertRaisesRegex(ValueError, "P2P implementation limit"):
            config(max_payload=0xFFFFFFFF)

    def test_genesis_hash_must_match_header(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            config(genesis_hash=bytes(32))

    def test_pow_limit_must_be_a_positive_uint256(self):
        for invalid in (True, 1 << 256, 0, -1):
            with self.subTest(pow_limit=invalid), self.assertRaisesRegex(
                ValueError, "positive uint256"
            ):
                config(pow_limit=invalid)

    def test_genesis_must_satisfy_configured_pow_limit(self):
        with self.assertRaisesRegex(ValueError, "proof-of-work limit"):
            config(pow_limit=1)

    def test_reject_production_network_names_and_zero_magic(self):
        with self.assertRaisesRegex(ValueError, "production network name"):
            config(network_id="mainnet")
        with self.assertRaisesRegex(ValueError, "all-zero"):
            config(message_magic=bytes(4))

    def test_manager_requires_matching_protocol_version(self):
        settings = config()
        version = VersionMessage(2, 0, 1, 2, 0, "/blackroot:test/")
        with self.assertRaisesRegex(ValueError, "does not match"):
            settings.create_peer_manager(version)

    def test_listener_host_is_loopback_only(self):
        settings = config()
        self.assertEqual(settings.validate_bind_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(settings.validate_bind_host("::1"), "::1")
        for host in ("0.0.0.0", "192.0.2.1", "localhost"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                settings.validate_bind_host(host)

    def test_json_config_loads_exact_fields_and_revalidates_genesis(self):
        settings = config()
        header = settings.genesis_header
        raw = {
            "network_id": settings.network_id,
            "message_magic": settings.message_magic.hex(),
            "protocol_version": settings.protocol_version,
            "genesis_header": {
                "version": header.version,
                "prev_hash": header.prev_hash.hex(),
                "merkle_root": header.merkle_root.hex(),
                "timestamp": header.timestamp,
                "bits": header.bits,
                "nonce": header.nonce,
            },
            "genesis_hash": settings.genesis_hash.hex(),
            "pow_limit": hex(settings.pow_limit),
            "p2p_port": settings.p2p_port,
            "max_peers": settings.max_peers,
            "max_payload": settings.max_payload,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "testnet.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded = TestnetConfig.from_json_file(path)
        self.assertEqual(loaded, settings)

    def test_json_config_rejects_duplicate_object_keys(self):
        settings = config()
        header = settings.genesis_header
        raw = {
            "network_id": settings.network_id,
            "message_magic": settings.message_magic.hex(),
            "protocol_version": settings.protocol_version,
            "genesis_header": {
                "version": header.version, "prev_hash": header.prev_hash.hex(),
                "merkle_root": header.merkle_root.hex(), "timestamp": header.timestamp,
                "bits": header.bits, "nonce": header.nonce,
            },
            "genesis_hash": settings.genesis_hash.hex(),
            "pow_limit": hex(settings.pow_limit),
            "p2p_port": settings.p2p_port,
            "max_peers": settings.max_peers,
        }
        encoded = json.dumps(raw)
        encoded = encoded.replace(
            '"network_id":',
            '"network_id": "shadow-network", "network_id":',
            1,
        )
        nested_encoded = json.dumps(raw)
        nested_encoded = nested_encoded.replace(
            '"version":',
            '"version": 99, "version":',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "testnet.json"
            for malformed in (encoded, nested_encoded):
                path.write_text(malformed, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                    TestnetConfig.from_json_file(path)

    def test_json_config_rejects_nonstandard_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "testnet.json"
            path.write_text(
                '{"network_id":"local","genesis_header":{"version":NaN}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid JSON constant"):
                TestnetConfig.from_json_file(path)

    def test_json_config_rejects_noncanonical_hex_fields(self):
        settings = config()
        header = settings.genesis_header
        raw = {
            "network_id": settings.network_id,
            "message_magic": settings.message_magic.hex(),
            "protocol_version": settings.protocol_version,
            "genesis_header": {
                "version": header.version,
                "prev_hash": header.prev_hash.hex(),
                "merkle_root": header.merkle_root.hex(),
                "timestamp": header.timestamp,
                "bits": header.bits,
                "nonce": header.nonce,
            },
            "genesis_hash": settings.genesis_hash.hex(),
            "pow_limit": hex(settings.pow_limit),
            "p2p_port": settings.p2p_port,
            "max_peers": settings.max_peers,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "testnet.json"
            malformed = dict(raw)
            malformed["message_magic"] = settings.message_magic.hex().upper()
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "message_magic"):
                TestnetConfig.from_json_file(path)

            malformed = dict(raw)
            malformed["genesis_header"] = dict(raw["genesis_header"])
            malformed["genesis_header"]["prev_hash"] = " " + header.prev_hash.hex()
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prev_hash"):
                TestnetConfig.from_json_file(path)

            malformed = dict(raw)
            malformed["pow_limit"] = "0X" + hex(settings.pow_limit)[2:]
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pow_limit"):
                TestnetConfig.from_json_file(path)

    def test_json_config_rejects_unknown_and_missing_fields(self):
        settings = config()
        header = settings.genesis_header
        raw = {
            "network_id": settings.network_id,
            "message_magic": settings.message_magic.hex(),
            "protocol_version": settings.protocol_version,
            "genesis_header": {
                "version": header.version, "prev_hash": header.prev_hash.hex(),
                "merkle_root": header.merkle_root.hex(), "timestamp": header.timestamp,
                "bits": header.bits, "nonce": header.nonce,
            },
            "genesis_hash": settings.genesis_hash.hex(),
            "pow_limit": hex(settings.pow_limit),
            "p2p_port": settings.p2p_port,
            "max_peers": settings.max_peers,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "testnet.json"
            raw["unexpected"] = True
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown"):
                TestnetConfig.from_json_file(path)
            del raw["unexpected"]
            del raw["network_id"]
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing"):
                TestnetConfig.from_json_file(path)

    def test_checked_in_local_node_configs_share_candidate_genesis(self):
        root = Path(__file__).resolve().parents[1]
        node_a = TestnetConfig.from_json_file(
            root / "examples" / "testnet-local-node-a.json"
        )
        node_b = TestnetConfig.from_json_file(
            root / "examples" / "testnet-local-node-b.json"
        )

        self.assertEqual(node_a.network_id, node_b.network_id)
        self.assertEqual(node_a.message_magic, node_b.message_magic)
        self.assertEqual(node_a.genesis_header, node_b.genesis_header)
        self.assertEqual(node_a.genesis_hash, node_b.genesis_hash)
        self.assertEqual(node_a.genesis_header.display_hash,
                         "12d0a70715fcc771e2228e8a8e2f85b4ada2b1bf2991c2a564553c0b9c922269")
        self.assertEqual(node_a.p2p_port, 18444)
        self.assertEqual(node_b.p2p_port, 18445)
        self.assertEqual(node_a.validate_bind_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(node_b.validate_bind_host("127.0.0.1"), "127.0.0.1")

    def test_cli_peer_endpoint_accepts_only_literal_loopback(self):
        settings = config()
        self.assertEqual(parse_connect_endpoint("127.0.0.1:18444", settings), ("127.0.0.1", 18444))
        self.assertEqual(parse_connect_endpoint("[::1]:18444", settings), ("::1", 18444))
        for endpoint in ("0.0.0.0:18444", "192.0.2.1:18444", "localhost:18444",
                         "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                parse_connect_endpoint(endpoint, settings)


if __name__ == "__main__":
    unittest.main()
