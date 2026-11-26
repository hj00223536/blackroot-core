import unittest

from src.blackroot_blocks import (
    Block, COINBASE_INDEX, ZERO_TXID, validate_block_transactions,
)
from src.blackroot_chain import BlockHeader
from src.blackroot_consensus import block_subsidy
from src.blackroot_script import (
    N, _mul, _hash160, _push, legacy_sighash_all, p2pkh_script,
)
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_maturity import UTXOProvenance


def der_integer(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big") or b"\x00"
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return b"\x02" + bytes([len(raw)]) + raw


def der_signature(r, s):
    body = der_integer(r) + der_integer(s)
    return b"\x30" + bytes([len(body)]) + body


def signed_spend(previous, previous_output, private_key=1, output_script=b'pay', lock_time=0, sequence=0xFFFFFFFE, version=1):
    point = _mul(private_key)
    pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
    unsigned = Transaction(
        version, (TxInput(previous, sequence=sequence),), (TxOutput(9_000, output_script),), lock_time
    )
    digest = legacy_sighash_all(unsigned, 0, previous_output.script_pubkey)
    nonce = 2
    nonce_point = _mul(nonce)
    r = nonce_point[0] % N
    s = (pow(nonce, N - 2, N) *
         (int.from_bytes(digest, "big") + r * private_key)) % N
    if s > N // 2:
        s = N - s
    signature = der_signature(r, s) + b"\x01"
    script_sig = _push(signature) + _push(pubkey)
    return Transaction(version, (TxInput(previous, script_sig, sequence),), unsigned.outputs, lock_time)


def make_coinbase(value, script=b"\x01\x01"):
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), script_sig=script),),
        (TxOutput(value, b"miner"),),
    )


def make_block(txs):
    return Block(
        BlockHeader(1, bytes(32), merkle_root([tx.txid for tx in txs]), 1, 0x207fffff, 0),
        tuple(txs),
    )


class BlockValidationTests(unittest.TestCase):
    def setUp(self):
        self.funding = OutPoint(bytes.fromhex("11" * 32), 0)
        point = _mul(1)
        pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        self.previous_output = TxOutput(10_000, p2pkh_script(_hash160(pubkey)))
        self.parent = {self.funding: self.previous_output}

    def test_block_serialization_round_trip(self):
        coinbase = make_coinbase(12345)
        block = make_block([coinbase])
        decoded = Block.deserialize(block.serialize())
        self.assertEqual(decoded, block)
        self.assertEqual(decoded.header.hash, block.header.hash)

    def test_block_header_uint32_version_round_trips_high_bit(self):
        coinbase = make_coinbase(1)
        header = BlockHeader(
            0x80000000, bytes(32), merkle_root([coinbase.txid]),
            1, 0x207fffff, 0,
        )
        block = Block(header, (coinbase,))
        decoded = Block.deserialize(block.serialize())
        self.assertEqual(decoded.header.version, 0x80000000)
        self.assertEqual(decoded.serialize(), block.serialize())

    def test_block_deserializer_rejects_truncation_and_trailing_bytes(self):
        block = make_block([make_coinbase(1)])
        raw = block.serialize()
        with self.assertRaisesRegex(ValueError, "truncated"):
            Block.deserialize(raw[:-1])
        with self.assertRaisesRegex(ValueError, "trailing bytes"):
            Block.deserialize(raw + b"\x00")

    def test_block_deserializer_rejects_noncanonical_transaction_count(self):
        block = make_block([make_coinbase(1)])
        raw = block.serialize()
        malformed = raw[:80] + b"\xfd\x01\x00" + raw[81:]
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            Block.deserialize(malformed)

    def test_valid_signed_block_accounts_fees_and_subsidy(self):
        spend = signed_spend(self.funding, self.previous_output)
        coinbase = make_coinbase(block_subsidy(1) + 1_000)
        result, fees = validate_block_transactions(make_block([coinbase, spend]), self.parent, 1)
        self.assertEqual(fees, 1_000)
        self.assertNotIn(self.funding, result)
        self.assertIn(OutPoint(spend.txid, 0), result)
        self.assertIn(OutPoint(coinbase.txid, 0), result)
        self.assertIn(self.funding, self.parent)

    def test_absolute_height_locktime_requires_finality_at_candidate_height(self):
        locked = signed_spend(self.funding, self.previous_output, lock_time=10)
        with self.assertRaisesRegex(ValueError, "non-final"):
            validate_block_transactions(make_block([make_coinbase(1), locked]), self.parent, 10)
        result, _fees = validate_block_transactions(
            make_block([make_coinbase(1), locked]), self.parent, 11
        )
        self.assertNotIn(self.funding, result)

    def test_final_sequence_overrides_unmet_absolute_locktime(self):
        locked = signed_spend(self.funding, self.previous_output, lock_time=500, sequence=0xFFFFFFFF)
        result, _fees = validate_block_transactions(make_block([make_coinbase(1), locked]), self.parent, 1)
        self.assertNotIn(self.funding, result)

    def test_timestamp_locktime_uses_parent_median_time_past(self):
        locked = signed_spend(self.funding, self.previous_output, lock_time=1_700_000_000)
        with self.assertRaisesRegex(ValueError, "median-time-past is required"):
            validate_block_transactions(make_block([make_coinbase(1), locked]), self.parent, 1)
        with self.assertRaisesRegex(ValueError, "non-final"):
            validate_block_transactions(
                make_block([make_coinbase(1), locked]), self.parent, 1,
                median_time_past=1_699_999_999,
            )
        result, _fees = validate_block_transactions(
            make_block([make_coinbase(1), locked]), self.parent, 1,
            median_time_past=1_700_000_001,
        )
        self.assertNotIn(self.funding, result)

    def test_bip68_height_relative_lock_enforces_creation_height(self):
        spend = signed_spend(
            self.funding, self.previous_output, version=2, sequence=2
        )
        provenance = {self.funding: UTXOProvenance(5, False)}
        with self.assertRaisesRegex(ValueError, "relative height sequence lock"):
            validate_block_transactions(
                make_block([make_coinbase(1), spend]), self.parent, 6, provenance
            )
        result, _fees = validate_block_transactions(
            make_block([make_coinbase(1), spend]), self.parent, 7, provenance
        )
        self.assertNotIn(self.funding, result)

    def test_bip68_does_not_apply_to_transaction_version_one(self):
        spend = signed_spend(
            self.funding, self.previous_output, version=1, sequence=100
        )
        provenance = {self.funding: UTXOProvenance(0, False)}
        result, _fees = validate_block_transactions(
            make_block([make_coinbase(1), spend]), self.parent, 1, provenance
        )
        self.assertNotIn(self.funding, result)

    def test_bip68_zero_height_lock_can_spend_prior_same_block_output(self):
        first = signed_spend(
            self.funding, self.previous_output,
            output_script=self.previous_output.script_pubkey,
        )
        intermediate = TxOutput(9_000, self.previous_output.script_pubkey)
        second = signed_spend(
            OutPoint(first.txid, 0), intermediate, version=2,
            sequence=0, output_script=b"pay",
        )
        provenance = {self.funding: UTXOProvenance(0, False)}
        result, _fees = validate_block_transactions(
            make_block([make_coinbase(1), first, second]),
            self.parent, 1, provenance,
        )
        self.assertNotIn(OutPoint(first.txid, 0), result)
        self.assertIn(OutPoint(second.txid, 0), result)

    def test_bip68_disable_flag_skips_relative_height_lock(self):
        spend = signed_spend(
            self.funding, self.previous_output, version=2,
            sequence=(1 << 31) | 100,
        )
        result, _fees = validate_block_transactions(
            make_block([make_coinbase(1), spend]), self.parent, 1
        )
        self.assertNotIn(self.funding, result)

    def test_bip68_time_relative_lock_enforces_512_second_boundary(self):
        spend = signed_spend(
            self.funding, self.previous_output, version=2,
            sequence=(1 << 22) | 1,
        )
        provenance = {self.funding: UTXOProvenance(0, False, 1_000)}
        block = make_block([make_coinbase(1), spend])
        with self.assertRaisesRegex(ValueError, "relative time sequence lock"):
            validate_block_transactions(
                block, self.parent, 1, provenance, median_time_past=1_511
            )
        result, _fees = validate_block_transactions(
            block, self.parent, 1, provenance, median_time_past=1_512
        )
        self.assertNotIn(self.funding, result)

    def test_bip68_time_relative_lock_requires_authenticated_parent_mtp(self):
        spend = signed_spend(
            self.funding, self.previous_output, version=2,
            sequence=(1 << 22) | 1,
        )
        provenance = {self.funding: UTXOProvenance(0, False, 1_000)}
        with self.assertRaisesRegex(ValueError, "parent median-time-past is required"):
            validate_block_transactions(
                make_block([make_coinbase(1), spend]), self.parent, 1, provenance
            )

    def test_bip68_time_relative_lock_requires_creation_mtp_provenance(self):
        spend = signed_spend(
            self.funding, self.previous_output, version=2,
            sequence=(1 << 22) | 1,
        )
        provenance = {self.funding: UTXOProvenance(0, False)}
        with self.assertRaisesRegex(ValueError, "creation median-time-past is required"):
            validate_block_transactions(
                make_block([make_coinbase(1), spend]), self.parent, 1,
                provenance, median_time_past=2_000,
            )

    def test_bip68_requires_authenticated_provenance_for_enabled_sequence(self):
        spend = signed_spend(
            self.funding, self.previous_output, version=2, sequence=1
        )
        with self.assertRaisesRegex(ValueError, "authenticated UTXO provenance"):
            validate_block_transactions(
                make_block([make_coinbase(1), spend]), self.parent, 1
            )

    def test_rejects_unsigned_spend_inside_block(self):
        unsigned = Transaction(
            1, (TxInput(self.funding),), (TxOutput(9_000, b"pay"),)
        )
        coinbase = make_coinbase(1)
        with self.assertRaisesRegex(ValueError, "script verification failed"):
            validate_block_transactions(make_block([coinbase, unsigned]), self.parent, 1)

    def test_rejects_cross_transaction_double_spend_without_mutating_parent(self):
        first_spend = signed_spend(self.funding, self.previous_output)
        second_spend = signed_spend(
            self.funding, self.previous_output, output_script=b'other'
        )
        block = make_block([make_coinbase(1), first_spend, second_spend])
        original_parent = dict(self.parent)

        with self.assertRaisesRegex(ValueError, "referenced UTXO does not exist"):
            validate_block_transactions(block, self.parent, 1)

        self.assertEqual(self.parent, original_parent)

    def test_rejects_invalid_later_transaction_without_mutating_parent(self):
        valid_spend = signed_spend(self.funding, self.previous_output)
        missing = OutPoint(bytes.fromhex("22" * 32), 0)
        invalid_spend = Transaction(
            1, (TxInput(missing),), (TxOutput(1, b"pay"),)
        )
        block = make_block([make_coinbase(1), valid_spend, invalid_spend])
        original_parent = dict(self.parent)

        with self.assertRaisesRegex(ValueError, "referenced UTXO does not exist"):
            validate_block_transactions(block, self.parent, 1)

        self.assertEqual(self.parent, original_parent)

    def test_rejects_missing_coinbase_first(self):
        spend = Transaction(1, (TxInput(self.funding),), (TxOutput(9_000, b"pay"),))
        with self.assertRaisesRegex(ValueError, "first transaction"):
            validate_block_transactions(make_block([spend]), self.parent, 1)

    def test_rejects_coinbase_overpayment(self):
        coinbase = make_coinbase(block_subsidy(1) + 1)
        with self.assertRaisesRegex(ValueError, "exceeds subsidy"):
            validate_block_transactions(make_block([coinbase]), self.parent, 1)

    def test_coinbase_outpoint_collision_does_not_mutate_parent_utxos(self):
        coinbase = make_coinbase(1)
        collision = OutPoint(coinbase.txid, 0)
        parent = {collision: TxOutput(7, b"existing")}
        original_parent = dict(parent)

        with self.assertRaisesRegex(ValueError, "coinbase would overwrite"):
            validate_block_transactions(make_block([coinbase]), parent, 1)

        self.assertEqual(parent, original_parent)

    def test_rejects_second_coinbase(self):
        with self.assertRaisesRegex(ValueError, "more than one"):
            validate_block_transactions(make_block([make_coinbase(1), make_coinbase(1)]), self.parent, 1)

    def test_rejects_wrong_merkle_root(self):
        coinbase = make_coinbase(1)
        wrong_header = BlockHeader(1, bytes(32), bytes(32), 1, 0x207fffff, 0)
        block = Block(wrong_header, (coinbase,))
        with self.assertRaisesRegex(ValueError, "merkle root"):
            validate_block_transactions(block, self.parent, 1)

    def test_rejects_coinbase_script_outside_bounds(self):
        coinbase = make_coinbase(1, b"x")
        with self.assertRaisesRegex(ValueError, "script_sig length"):
            validate_block_transactions(make_block([coinbase]), self.parent, 1)

    def test_rejects_block_over_provisional_serialized_size_limit(self):
        transactions = [make_coinbase(1)]
        for index in range(1, 110):
            previous = OutPoint(bytes([index]) * 32, 0)
            transactions.append(Transaction(
                index,
                (TxInput(previous),),
                (TxOutput(1, b"x" * 9_990),),
            ))
        with self.assertRaisesRegex(ValueError, "serialized block exceeds"):
            Block(
                BlockHeader(1, bytes(32), bytes(32), 1, 0x207fffff, 0),
                tuple(transactions),
            )

    def test_rejects_invalid_height(self):
        coinbase = make_coinbase(1)
        with self.assertRaisesRegex(ValueError, "height"):
            validate_block_transactions(make_block([coinbase]), self.parent, -1)


    def test_rejects_immature_coinbase_spend_when_provenance_is_supplied(self):
        spend = signed_spend(self.funding, self.previous_output)
        coinbase = make_coinbase(1)
        provenance = {self.funding: UTXOProvenance(0, True)}
        with self.assertRaisesRegex(ValueError, "premature coinbase"):
            validate_block_transactions(
                make_block([coinbase, spend]), self.parent, 99, provenance
            )

    def test_accepts_mature_coinbase_spend_at_exact_boundary(self):
        spend = signed_spend(self.funding, self.previous_output)
        coinbase = make_coinbase(block_subsidy(100) + 1_000)
        provenance = {self.funding: UTXOProvenance(0, True)}
        result, fees = validate_block_transactions(
            make_block([coinbase, spend]), self.parent, 100, provenance
        )
        self.assertEqual(fees, 1_000)
        self.assertNotIn(self.funding, result)

    def test_provenance_must_cover_entire_parent_utxo_set(self):
        coinbase = make_coinbase(1)
        with self.assertRaisesRegex(ValueError, "complete authenticated"):
            validate_block_transactions(
                make_block([coinbase]), self.parent, 1, {}
            )

if __name__ == "__main__":
    unittest.main()
