import unittest

from src.blackroot_blocks import COINBASE_INDEX
from src.blackroot_monetary import (
    COIN,
    FOUNDER_ALLOCATION,
    MINING_ALLOCATION,
    TOTAL_SUPPLY_CAP,
)
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput
from src.blackroot_genesis_manifest import (
    calculate_genesis_manifest_digest,
    canonicalize_genesis_manifest,
    parse_genesis_manifest_json,
    validate_genesis_manifest_structure,
)

NETWORK_ID = "11" * 32
BLOCK_HASH = "22" * 32
SCHEDULE_ID = "33" * 32
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
    manifest = {
        "manifest_version": 1,
        "manifest_digest": "00" * 32,
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
    manifest["manifest_digest"] = calculate_genesis_manifest_digest(manifest)
    return manifest


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
    """Structural checks only; fixtures do not authorize real issuance."""

    def test_valid_manifest_decodes_exact_founder_output(self):
        validated = _validate(_manifest())
        self.assertEqual(validated.coinbase, _coinbase())
        self.assertEqual(validated.founder_output_index, 1)
        self.assertEqual(validated.founder_amount_sats, 20_000_000 * COIN)
        self.assertEqual(validated.founder_script_pub_key, FOUNDER_SCRIPT)
        self.assertEqual(validated.founder_amount_sats + MINING_ALLOCATION, TOTAL_SUPPLY_CAP)

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
        malformed_hex["network_id"] = "AA" * 32
        malformed_hex["manifest_digest"] = calculate_genesis_manifest_digest(malformed_hex)
        with self.assertRaisesRegex(ValueError, "lowercase"):
            _validate(malformed_hex)

        boolean_amount = _manifest()
        boolean_amount["founder_amount_sats"] = True
        boolean_amount["manifest_digest"] = calculate_genesis_manifest_digest(boolean_amount)
        with self.assertRaisesRegex(ValueError, "safe integer"):
            _validate(boolean_amount)

    def test_network_genesis_and_schedule_must_match_frozen_values(self):
        for field in ("network_id", "genesis_block_hash", "mining_schedule_id"):
            with self.subTest(field=field):
                manifest = _manifest()
                manifest[field] = "99" * 32
                manifest["manifest_digest"] = calculate_genesis_manifest_digest(manifest)
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
        wrong_txid["manifest_digest"] = calculate_genesis_manifest_digest(wrong_txid)
        with self.assertRaisesRegex(ValueError, "txid"):
            _validate(wrong_txid)

        wrong_script = _manifest()
        wrong_script["founder_script_pub_key"] = "51"
        wrong_script["manifest_digest"] = calculate_genesis_manifest_digest(wrong_script)
        with self.assertRaisesRegex(ValueError, "locking script"):
            _validate(wrong_script)

        wrong_index = _manifest()
        wrong_index["founder_output_index"] = 9
        wrong_index["manifest_digest"] = calculate_genesis_manifest_digest(wrong_index)
        with self.assertRaisesRegex(ValueError, "outside"):
            _validate(wrong_index)

    def test_supply_cap_and_mining_budget_must_match(self):
        wrong_cap = _manifest()
        wrong_cap["total_supply_cap_sats"] -= 1
        wrong_cap["manifest_digest"] = calculate_genesis_manifest_digest(wrong_cap)
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
        malformed_tx["manifest_digest"] = calculate_genesis_manifest_digest(malformed_tx)
        with self.assertRaises(ValueError):
            _validate(malformed_tx)

        missing_approval = _manifest()
        missing_approval["approval_record"] = "   "
        missing_approval["manifest_digest"] = calculate_genesis_manifest_digest(missing_approval)
        with self.assertRaisesRegex(ValueError, "approval_record"):
            _validate(missing_approval)

    def test_digest_is_canonical_and_detects_any_field_change(self):
        manifest = _manifest()
        expected = calculate_genesis_manifest_digest(manifest)
        self.assertEqual(manifest["manifest_digest"], expected)
        self.assertEqual(expected, "9bb6346eff59ffa041f2d81ad640e0af04bde0feade6da4eef223c7744c86370")
        reordered = dict(reversed(list(manifest.items())))
        self.assertEqual(canonicalize_genesis_manifest(manifest), canonicalize_genesis_manifest(reordered))
        self.assertEqual(calculate_genesis_manifest_digest(reordered), expected)

        altered = dict(manifest)
        altered["approval_record"] = "different-record"
        with self.assertRaisesRegex(ValueError, "manifest_digest"):
            _validate(altered)

    def test_strict_json_parser_rejects_duplicate_keys_and_floats(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_genesis_manifest_json('{"manifest_version":1,"manifest_version":1}')
        with self.assertRaisesRegex(ValueError, "floating-point"):
            parse_genesis_manifest_json('{"amount":1.25}')
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            parse_genesis_manifest_json('{"amount":NaN}')

    def test_jcs_uses_utf16_key_order_and_safe_integer_range(self):
        from src.blackroot_genesis_manifest import _jcs_encode
        self.assertEqual(_jcs_encode({"b": 1, "a": 2}), '{"a":2,"b":1}')
        self.assertEqual(_jcs_encode({"😀": 1, "\ue000": 2}), '{"😀":1,"\ue000":2}')
        with self.assertRaisesRegex(ValueError, "safe range"):
            _jcs_encode(1 << 53)


if __name__ == "__main__":
    unittest.main()
