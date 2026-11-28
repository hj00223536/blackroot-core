import hashlib
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.blackroot_blocks import COINBASE_INDEX
from src.blackroot_monetary import FOUNDER_ALLOCATION, MINING_ALLOCATION, TOTAL_SUPPLY_CAP
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_genesis_approval import approval_message
from src.blackroot_genesis_manifest_v2 import calculate_genesis_manifest_v2_digest
from src.blackroot_genesis_trust import calculate_trust_configuration_digest
from src.blackroot_genesis_authorization import verify_genesis_authorization_package


NETWORK = "11" * 32
BLOCK_HASH = "22" * 32
SCHEDULE = "33" * 32
SCRIPT = bytes.fromhex("76a914" + "55" * 20 + "88ac")
# RFC 8032 public test vector only; this is never an owner key.
TEST_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
))
TEST_PUBLIC = TEST_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)
KEY_ID = hashlib.sha256(TEST_PUBLIC).hexdigest()


def make_manifest():
    tx = Transaction(
        1,
        (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
        (TxOutput(0, b"\\x6a"), TxOutput(FOUNDER_ALLOCATION, SCRIPT)),
        0,
    )
    value = {
        "manifest_version": 2,
        "manifest_digest": "00" * 32,
        "network_id": NETWORK,
        "genesis_block_hash": BLOCK_HASH,
        "genesis_coinbase_tx": tx.serialize().hex(),
        "founder_output_index": 1,
        "founder_amount_sats": FOUNDER_ALLOCATION,
        "founder_script_pub_key": SCRIPT.hex(),
        "total_supply_cap_sats": TOTAL_SUPPLY_CAP,
        "mining_schedule_id": SCHEDULE,
    }
    value["manifest_digest"] = calculate_genesis_manifest_v2_digest(value)
    return value, tx


def make_trust():
    value = {
        "config_version": 1,
        "network_id": NETWORK,
        "sequence": 1,
        "previous_config_digest": None,
        "keys": [{
            "key_id": KEY_ID,
            "public_key": TEST_PUBLIC.hex(),
            "scopes": ["genesis-founder-allocation"],
            "status": "active",
        }],
    }
    value["config_digest"] = calculate_trust_configuration_digest(value)
    return value


def make_approval(manifest):
    return {
        "record_version": 1,
        "network_id": NETWORK,
        "manifest_digest": manifest["manifest_digest"],
        "approval_scope": "genesis-founder-allocation",
        "signing_key_id": KEY_ID,
        "signature_algorithm": "Ed25519",
        "signature": TEST_PRIVATE.sign(
            approval_message(NETWORK, manifest["manifest_digest"])
        ).hex(),
    }


class GenesisAuthorizationCompositionTests(unittest.TestCase):
    def setUp(self):
        self.manifest, tx = make_manifest()
        self.trust = make_trust()
        self.approval = make_approval(self.manifest)
        self.args = {
            "expected_network_id": NETWORK,
            "expected_genesis_block_hash": BLOCK_HASH,
            "expected_genesis_txid": tx.display_txid,
            "expected_founder_amount_sats": FOUNDER_ALLOCATION,
            "expected_total_supply_cap_sats": TOTAL_SUPPLY_CAP,
            "expected_mining_schedule_id": SCHEDULE,
            "maximum_mining_issuance_sats": MINING_ALLOCATION,
            "pinned_trust_config_digest": self.trust["config_digest"],
            "expected_trust_config_sequence": 1,
            "expected_previous_trust_config_digest": None,
        }

    def verify(self, manifest=None, approval=None, trust=None, **overrides):
        args = dict(self.args)
        args.update(overrides)
        return verify_genesis_authorization_package(
            json.dumps(self.manifest if manifest is None else manifest),
            json.dumps(self.approval if approval is None else approval),
            json.dumps(self.trust if trust is None else trust),
            **args,
        )

    def test_valid_package_composes_all_three_independent_validators(self):
        result = self.verify()
        self.assertEqual(result.manifest_digest, self.manifest["manifest_digest"])
        self.assertEqual(result.network_id, NETWORK)
        self.assertEqual(result.genesis_block_hash, BLOCK_HASH)
        self.assertEqual(result.trust_config_digest, self.trust["config_digest"])
        self.assertEqual(result.trust_config_sequence, 1)
        self.assertEqual(result.approving_key_id, KEY_ID)
        with self.assertRaises(AttributeError):
            result.manifest_digest = "ff" * 32

    def test_manifest_substitution_fails_before_approval(self):
        altered = dict(self.manifest)
        altered["founder_amount_sats"] += 1
        with self.assertRaisesRegex(ValueError, "manifest_digest"):
            self.verify(manifest=altered)

    def test_trust_digest_must_match_external_pin(self):
        altered = dict(self.trust)
        altered["keys"] = []
        altered["config_digest"] = calculate_trust_configuration_digest(altered)
        with self.assertRaisesRegex(ValueError, "external pin"):
            self.verify(trust=altered)

    def test_trust_sequence_downgrade_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "pinned sequence"):
            self.verify(expected_trust_config_sequence=2)

    def test_invalid_detached_signature_is_rejected(self):
        altered = dict(self.approval)
        altered["signature"] = "00" * 64
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            self.verify(approval=altered)

    def test_revoked_approval_key_is_rejected(self):
        altered = dict(self.trust)
        altered["keys"] = [dict(altered["keys"][0], status="revoked")]
        altered["config_digest"] = calculate_trust_configuration_digest(altered)
        args = dict(self.args, pinned_trust_config_digest=altered["config_digest"])
        with self.assertRaisesRegex(ValueError, "revoked"):
            verify_genesis_authorization_package(
                json.dumps(self.manifest), json.dumps(self.approval),
                json.dumps(altered), **args,
            )


if __name__ == "__main__":
    unittest.main()
