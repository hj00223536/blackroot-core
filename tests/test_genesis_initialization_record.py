import copy
import unittest

from src.blackroot_genesis_initialization_record import (
    build_genesis_initialization_record,
    validate_genesis_initialization_record,
)
from src.blackroot_genesis_manifest_v2 import (
    calculate_genesis_manifest_v2_digest,
    validate_genesis_manifest_v2,
)
from src.blackroot_monetary import FOUNDER_ALLOCATION, MINING_ALLOCATION, TOTAL_SUPPLY_CAP
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_blocks import COINBASE_INDEX

NETWORK_ID = "11" * 32
BLOCK_HASH = "22" * 32
SCHEDULE_ID = "33" * 32
FOUNDER_SCRIPT = bytes.fromhex("76a914" + "55" * 20 + "88ac")


def validated_manifest():
    tx = Transaction(
        1,
        (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\x01\x01"),),
        (TxOutput(0, b"\x6a"), TxOutput(FOUNDER_ALLOCATION, FOUNDER_SCRIPT)),
        0,
    )
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
    return validate_genesis_manifest_v2(
        value,
        expected_network_id=NETWORK_ID,
        expected_genesis_block_hash=BLOCK_HASH,
        expected_genesis_txid=tx.display_txid,
        expected_founder_amount_sats=FOUNDER_ALLOCATION,
        expected_total_supply_cap_sats=TOTAL_SUPPLY_CAP,
        expected_mining_schedule_id=SCHEDULE_ID,
        maximum_mining_issuance_sats=MINING_ALLOCATION,
    )


class GenesisInitializationRecordTests(unittest.TestCase):
    def test_record_is_deterministic_and_matches_validated_manifest(self):
        manifest = validated_manifest()
        record = build_genesis_initialization_record(manifest)
        self.assertEqual(record, build_genesis_initialization_record(manifest))
        self.assertEqual(record["record_kind"], "genesis-integrity-snapshot-v1")
        self.assertNotIn("initialization_complete", record)
        self.assertEqual(record["founder_amount_sats"], FOUNDER_ALLOCATION)
        self.assertEqual(record["total_supply_cap_sats"], TOTAL_SUPPLY_CAP)
        self.assertIsNone(validate_genesis_initialization_record(record, manifest))

    def test_every_field_is_bound_to_manifest(self):
        manifest = validated_manifest()
        original = build_genesis_initialization_record(manifest)
        for field in original:
            altered = copy.deepcopy(original)
            value = altered[field]
            if type(value) is bool:
                altered[field] = not value
            elif type(value) is int:
                altered[field] = value + 1
            elif type(value) is str:
                altered[field] = "00" if value != "00" else "11"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                validate_genesis_initialization_record(altered, manifest)

    def test_missing_and_unknown_fields_are_rejected(self):
        manifest = validated_manifest()
        record = build_genesis_initialization_record(manifest)
        missing = dict(record)
        del missing["manifest_digest"]
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            validate_genesis_initialization_record(missing, manifest)
        unknown = dict(record, private_key="never-accepted")
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            validate_genesis_initialization_record(unknown, manifest)

    def test_bool_cannot_substitute_for_integer_version_or_amount(self):
        manifest = validated_manifest()
        record = build_genesis_initialization_record(manifest)
        record["record_version"] = True
        with self.assertRaisesRegex(ValueError, "record_version"):
            validate_genesis_initialization_record(record, manifest)
        record = build_genesis_initialization_record(manifest)
        record["founder_amount_sats"] = True
        with self.assertRaisesRegex(ValueError, "founder_amount_sats"):
            validate_genesis_initialization_record(record, manifest)

    def test_wrong_manifest_type_is_rejected(self):
        with self.assertRaises(TypeError):
            build_genesis_initialization_record(object())
        with self.assertRaises(TypeError):
            validate_genesis_initialization_record({}, object())


if __name__ == "__main__":
    unittest.main()
