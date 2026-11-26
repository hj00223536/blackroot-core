import unittest
from collections.abc import Mapping
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.blackroot_blocks import COINBASE_INDEX
from src.blackroot_monetary import COIN, FOUNDER_ALLOCATION, MINING_ALLOCATION, TOTAL_SUPPLY_CAP
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_genesis_approval import approval_message, verify_validated_genesis_manifest_approval
from src.blackroot_genesis_manifest_v2 import (
    calculate_genesis_manifest_v2_digest,
    parse_genesis_manifest_v2_json,
    validate_genesis_manifest_v2,
)

NETWORK_ID = "11" * 32
BLOCK_HASH = "22" * 32
SCHEDULE_ID = "33" * 32
FOUNDER_SCRIPT = bytes.fromhex("76a914" + "55" * 20 + "88ac")


def coinbase():
    return Transaction(
        1,
        (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\\x01\\x01"),),
        (TxOutput(0, b"\\x6a"), TxOutput(FOUNDER_ALLOCATION, FOUNDER_SCRIPT)),
        0,
    )


def manifest():
    tx = coinbase()
    value = {
        "manifest_version": 2,
        "manifest_digest": "00" * 32,
        "network_id": NETWORK_ID,
        "genesis_block_hash": BLOCK_HASH,
        "genesis_coinbase_tx": tx.serialize().hex(),
        "founder_output_index": 1,
        "founder_amount_sats": FOUNDER_ALLOCATION,
        "founder_script_pub_key": FOUNDER_SCRIPT.hex(),
        "total_supply_cap_sats": TOTAL_SUPPLY_CAP,
        "mining_schedule_id": SCHEDULE_ID,
    }
    value["manifest_digest"] = calculate_genesis_manifest_v2_digest(value)
    return value


def validate(value):
    return validate_genesis_manifest_v2(
        value,
        expected_network_id=NETWORK_ID,
        expected_genesis_block_hash=BLOCK_HASH,
        expected_genesis_txid=coinbase().display_txid,
        expected_founder_amount_sats=FOUNDER_ALLOCATION,
        expected_total_supply_cap_sats=TOTAL_SUPPLY_CAP,
        expected_mining_schedule_id=SCHEDULE_ID,
        maximum_mining_issuance_sats=MINING_ALLOCATION,
    )


class MutatingManifest(Mapping):
    """Expose a changed value if validation re-reads the caller mapping."""

    def __init__(self, values):
        self.values = dict(values)
        self.amount_reads = 0

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)

    def __getitem__(self, key):
        value = self.values[key]
        if key == "founder_amount_sats":
            self.amount_reads += 1
            if self.amount_reads > 1:
                return value + 1
        return value


class GenesisManifestV2Tests(unittest.TestCase):
    def test_valid_v2_manifest_decodes_founder_output_without_approval_field(self):
        value = manifest()
        self.assertNotIn("approval_record", value)
        validated = validate(value)
        self.assertEqual(validated.manifest_digest, value["manifest_digest"])
        self.assertEqual(validated.network_id, NETWORK_ID)
        self.assertEqual(validated.founder_amount_sats, 20_000_000 * COIN)
        self.assertEqual(validated.founder_script_pub_key, FOUNDER_SCRIPT)
        self.assertEqual(validated.approval_record, "")

    def test_validation_uses_one_snapshot_of_caller_mapping(self):
        supplied = MutatingManifest(manifest())
        validated = validate(supplied)
        self.assertEqual(validated.founder_amount_sats, FOUNDER_ALLOCATION)
        self.assertEqual(supplied.amount_reads, 1)

    def test_v1_shape_unknown_fields_and_missing_fields_are_rejected(self):
        old = manifest()
        old["manifest_version"] = 1
        old["approval_record"] = "legacy-placeholder"
        old["manifest_digest"] = calculate_genesis_manifest_v2_digest(old)
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            validate(old)

        missing = manifest()
        del missing["founder_script_pub_key"]
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            validate(missing)

        unknown = manifest()
        unknown["private_key"] = "never-accepted"
        unknown["manifest_digest"] = calculate_genesis_manifest_v2_digest(unknown)
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            validate(unknown)

    def test_digest_network_genesis_and_schedule_are_bound(self):
        changed = manifest()
        changed["founder_amount_sats"] += 1
        with self.assertRaisesRegex(ValueError, "manifest_digest"):
            validate(changed)

        for field in ("network_id", "genesis_block_hash", "mining_schedule_id"):
            altered = manifest()
            altered[field] = "99" * 32
            altered["manifest_digest"] = calculate_genesis_manifest_v2_digest(altered)
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "frozen configuration"):
                    validate(altered)

    def test_transaction_and_founder_script_are_bound(self):
        altered = manifest()
        altered["genesis_coinbase_tx"] = "00"
        altered["manifest_digest"] = calculate_genesis_manifest_v2_digest(altered)
        with self.assertRaises(ValueError):
            validate(altered)

        altered = manifest()
        altered["founder_script_pub_key"] = "51"
        altered["manifest_digest"] = calculate_genesis_manifest_v2_digest(altered)
        with self.assertRaisesRegex(ValueError, "locking script"):
            validate(altered)

    def test_supply_cap_and_version_are_enforced(self):
        altered = manifest()
        altered["total_supply_cap_sats"] -= 1
        altered["manifest_digest"] = calculate_genesis_manifest_v2_digest(altered)
        with self.assertRaisesRegex(ValueError, "supply cap"):
            validate(altered)

        altered = manifest()
        altered["manifest_version"] = True
        altered["manifest_digest"] = calculate_genesis_manifest_v2_digest(altered)
        with self.assertRaisesRegex(ValueError, "safe integer"):
            validate(altered)

    def test_v2_validated_manifest_accepts_only_matching_detached_approval(self):
        validated = validate(manifest())
        # Public RFC 8032 test seed only; never an owner key.
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
        ))
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        key_id = hashlib.sha256(public).hexdigest()
        record = {
            "record_version": 1,
            "network_id": validated.network_id,
            "manifest_digest": validated.manifest_digest,
            "approval_scope": "genesis-founder-allocation",
            "signing_key_id": key_id,
            "signature_algorithm": "Ed25519",
            "signature": private.sign(
                approval_message(validated.network_id, validated.manifest_digest)
            ).hex(),
        }
        self.assertEqual(
            verify_validated_genesis_manifest_approval(
                validated,
                json.dumps(record, separators=(",", ":")),
                trusted_public_keys={key_id: public},
            ),
            key_id,
        )
        altered = dict(record, network_id="44" * 32)
        with self.assertRaisesRegex(ValueError, "network_id"):
            verify_validated_genesis_manifest_approval(
                validated,
                json.dumps(altered),
                trusted_public_keys={key_id: public},
            )

    def test_v2_json_parser_rejects_duplicate_keys_floats_and_wrong_schema(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_genesis_manifest_v2_json('{"manifest_version":2,"manifest_version":2}')
        with self.assertRaisesRegex(ValueError, "floating-point"):
            parse_genesis_manifest_v2_json('{"manifest_version":2.0}')
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            parse_genesis_manifest_v2_json('{"manifest_version":2}')
        with self.assertRaisesRegex(ValueError, "unsupported"):
            parse_genesis_manifest_v2_json(
                __import__("json").dumps(dict(manifest(), manifest_version=1,
                    manifest_digest=calculate_genesis_manifest_v2_digest(
                        dict(manifest(), manifest_version=1))))
            )

    def test_published_cross_language_v2_digest_vector(self):
        vector = {
            "manifest_version": 2,
            "network_id": "11" * 32,
            "genesis_block_hash": "22" * 32,
            "genesis_coinbase_tx": "00",
            "founder_output_index": 1,
            "founder_amount_sats": 2000000000000000,
            "founder_script_pub_key": "51",
            "total_supply_cap_sats": 4000000000000000,
            "mining_schedule_id": "33" * 32,
        }
        self.assertEqual(
            calculate_genesis_manifest_v2_digest(vector),
            "d5d7ee8495437bc233533966de69a8cb59583dc15f311fea8819a6bff6f604dd",
        )

    def test_json_parser_is_strict(self):
        from src.blackroot_genesis_manifest import parse_genesis_manifest_json
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_genesis_manifest_json('{"manifest_version":2,"manifest_version":2}')
        with self.assertRaisesRegex(ValueError, "floating-point"):
            parse_genesis_manifest_json('{"manifest_version":2.0}')


if __name__ == "__main__":
    unittest.main()
