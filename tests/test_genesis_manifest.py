import unittest

from src.blackroot_monetary import (
    COIN,
    FOUNDER_ALLOCATION,
    MINING_ALLOCATION,
    TOTAL_SUPPLY_CAP,
)
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_blocks import COINBASE_INDEX
from src.blackroot_genesis_manifest import validate_genesis_manifest_structure


NETWORK_ID = "11" * 32
BLOCK_HASH = "22" * 32
SCHEDULE_ID = "33" * 32
MANIFEST_DIGEST = "44" * 32
FOUNDER_SCRIPT = bytes.fromhex("76a914" + "55" * 20 + "88ac")


def _coinbase():
    return Transaction(
        1,
        (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\x01\x01"),),
        (
            TxOutput(0, b"\x6a"),
            TxOutput(FOUNDER_ALLOCATION, FOUNDER_SCRIPT),
        ),
        0,
    )


def _manifest():
    coinbase = _coinbase()
    return {
        "manifest_version": 1,
        "manifest_digest": MANIFEST_DIGEST,
        "network_id": NETWORK_ID,
        "genesis_block_hash": BLOCK_HASH,
        "genesis_coinbase_tx": coinbase.serialize().hex(),
        "founder_output_index": 1,
        "founder_amount_sats": FOUNDER_ALLOCATION,
        "founder_script_pub_key": FOUNDER_SCRIPT.hex(),
        "total_supply_cap_sats": TOTAL_SUPPLY_CAP,
        "mining_schedule_id": SCHEDULE_ID,
        "approval_record": "test-only-fixture; not owner approval",
    }


def _validate(manifest):
    return validate_genesis_manifest_structure(
        manifest,
        expected_network_id=NETWORK_ID,
        expected_genesis_block_hash=BLOCK_HASH,
        expected_genesis_txid=_coinbase().display_txid,
        expected_founder_amount_sats=FOUNDER_ALLOCATION,
        expected_total_supply_cap_sats=TOTAL_SUPPLY_CAP,
        expected_mining_schedule_id=SCHEDULE_ID,
        maximum_mining_issuance_sats=MINING_ALLOCATION,
    )


class GenesisManifestStructureTests(unittest.TestCase):
    """Structural checks only; these fixtures do not authorize real issuance."""

    def test_valid_manifest_decodes_exact_founder_output(self):
        validated = _validate(_manifest())
        self.assertEqual(validated.coinbase, _coinbase())
        self.assertEqual(validated.founder_output_index, 1)
        self.assertEqual(validated.founder_amount_sats, 20_000_000 * COIN)
        self.assertEqual(validated.founder_script_pub_key, FOUNDER_SCRIPT)
        self.assertEqual(
            validated.founder_amount_sats + MINING_ALLOCATION,
            TOTAL_SUPPLY_CAP,
        )

    def test_missing_or_unknown_fields_are_rejected(self):
        missing = _manifest()
        del missing["approval_record"]
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            _validate(missing)

        unknown = _manifest()
        unknown["private_key"] = "not-allowed"
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            _validate(unknown)

    def test_noncanonical_hex_and_boolean_integer_are_rejected(self):
        malformed_hex = _manifest()
        malformed_hex["network_id"] = NETWORK_ID.upper()
        with self.assertRaisesRegex(ValueError, "lowercase"):
            _validate(malformed_hex)

        boolean_amount = _manifest()
        boolean_amount["founder_amount_sats"] = True
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            _validate(boolean_amount)

    def test_network_genesis_and_schedule_must_match_frozen_values(self):
        for field in ("network_id", "genesis_block_hash", "mining_schedule_id"):
            with self.subTest(field=field):
                manifest = _manifest()
                manifest[field] = "99" * 32
                with self.assertRaises(ValueError):
                    _validate(manifest)

    def test_coinbase_txid_and_founder_output_are_bound(self):
        wrong_txid = _manifest()
        wrong_txid["genesis_coinbase_tx"] = Transaction(
            1,
            (TxInput(OutPoint(bytes(32), COINBASE_INDEX), b"\x01\x01"),),
            (TxOutput(FOUNDER_ALLOCATION, FOUNDER_SCRIPT),),
            0,
        ).serialize().hex()
        with self.assertRaisesRegex(ValueError, "txid"):
            _validate(wrong_txid)

        wrong_script = _manifest()
        wrong_script["founder_script_pub_key"] = "51"
        with self.assertRaisesRegex(ValueError, "locking script"):
            _validate(wrong_script)

        wrong_index = _manifest()
        wrong_index["founder_output_index"] = 9
        with self.assertRaisesRegex(ValueError, "outside"):
            _validate(wrong_index)

    def test_supply_cap_and_mining_budget_must_match(self):
        wrong_cap = _manifest()
        wrong_cap["total_supply_cap_sats"] -= 1
        with self.assertRaisesRegex(ValueError, "supply cap"):
            _validate(wrong_cap)

        with self.assertRaisesRegex(ValueError, "must equal supply cap"):
            validate_genesis_manifest_structure(
                _manifest(),
                expected_network_id=NETWORK_ID,
                expected_genesis_block_hash=BLOCK_HASH,
                expected_genesis_txid=_coinbase().display_txid,
                expected_founder_amount_sats=FOUNDER_ALLOCATION,
                expected_total_supply_cap_sats=TOTAL_SUPPLY_CAP,
                expected_mining_schedule_id=SCHEDULE_ID,
                maximum_mining_issuance_sats=MINING_ALLOCATION - 1,
            )

    def test_malformed_transaction_and_empty_approval_reference_fail_closed(self):
        malformed_tx = _manifest()
        malformed_tx["genesis_coinbase_tx"] = "00"
        with self.assertRaises(ValueError):
            _validate(malformed_tx)

        missing_approval = _manifest()
        missing_approval["approval_record"] = "   "
        with self.assertRaisesRegex(ValueError, "approval_record"):
            _validate(missing_approval)


if __name__ == "__main__":
    unittest.main()
