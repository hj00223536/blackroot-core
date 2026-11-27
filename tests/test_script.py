import unittest

from src.blackroot_script import (
    G, N, _mul, _hash160, _push, legacy_sighash_all, p2pkh_script,
    verify_p2pkh_input, validate_transaction_scripts,
)
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput


def der_integer(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big") or b"\x00"
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return b"\x02" + bytes([len(raw)]) + raw


def der_signature(r, s):
    body = der_integer(r) + der_integer(s)
    return b"\x30" + bytes([len(body)]) + body


def sign_for_test(digest, private_key, nonce):
    z = int.from_bytes(digest, "big")
    point = _mul(nonce)
    r = point[0] % N
    s = (pow(nonce, N - 2, N) * (z + r * private_key)) % N
    if s > N // 2:
        s = N - s
    return der_signature(r, s)


class P2PKHScriptTests(unittest.TestCase):
    def setUp(self):
        self.private_key = 1
        point = _mul(self.private_key)
        self.pubkey = bytes([2 | (point[1] & 1)]) + point[0].to_bytes(32, "big")
        self.previous = OutPoint(bytes.fromhex("12" * 32), 0)
        self.previous_output = TxOutput(100_000, p2pkh_script(_hash160(self.pubkey)))

    def signed_tx(self):
        unsigned = Transaction(
            1, (TxInput(self.previous),),
            (TxOutput(90_000, b"\x51"),),
        )
        digest = legacy_sighash_all(unsigned, 0, self.previous_output.script_pubkey)
        signature = sign_for_test(digest, self.private_key, 2) + b"\x01"
        script_sig = _push(signature) + _push(self.pubkey)
        return Transaction(
            1, (TxInput(self.previous, script_sig),),
            unsigned.outputs,
        )

    def test_verifies_valid_compressed_key_p2pkh_signature(self):
        tx = self.signed_tx()
        self.assertTrue(verify_p2pkh_input(tx, 0, self.previous_output))
        validate_transaction_scripts(tx, {self.previous: self.previous_output})

    def test_rejects_signature_for_modified_transaction(self):
        tx = self.signed_tx()
        changed = Transaction(
            1, tx.inputs, (TxOutput(89_999, b"\x51"),)
        )
        self.assertFalse(verify_p2pkh_input(changed, 0, self.previous_output))

    def test_rejects_wrong_key_and_malformed_scripts(self):
        tx = self.signed_tx()
        wrong_previous = TxOutput(100_000, p2pkh_script(b"\x99" * 20))
        self.assertFalse(verify_p2pkh_input(tx, 0, wrong_previous))
        malformed = Transaction(
            1, (TxInput(self.previous, b"\x4c\x01"),), tx.outputs
        )
        self.assertFalse(verify_p2pkh_input(malformed, 0, self.previous_output))

    def test_rejects_curve_invalid_pubkey_even_when_hash_matches(self):
        tx = self.signed_tx()
        invalid_pubkey = b"\x02" + b"\xff" * 32
        signature = tx.inputs[0].script_sig
        signature_length = signature[0]
        signature_push = signature[1:1 + signature_length]
        malformed_sig = _push(signature_push) + _push(invalid_pubkey)
        malformed_tx = Transaction(
            1, (TxInput(self.previous, malformed_sig),), tx.outputs
        )
        previous = TxOutput(
            100_000, p2pkh_script(_hash160(invalid_pubkey))
        )
        self.assertFalse(verify_p2pkh_input(malformed_tx, 0, previous))

    def test_rejects_unsupported_sighash_and_high_s(self):
        tx = self.signed_tx()
        bad_input = TxInput(self.previous, tx.inputs[0].script_sig[:-1] + b"\x02")
        bad = Transaction(1, (bad_input,), tx.outputs)
        self.assertFalse(verify_p2pkh_input(bad, 0, self.previous_output))

    def test_script_validation_fails_closed_for_unknown_script_type(self):
        tx = self.signed_tx()
        unknown = {self.previous: TxOutput(100_000, b"unknown-script")}
        with self.assertRaisesRegex(ValueError, "script verification failed"):
            validate_transaction_scripts(tx, unknown)


if __name__ == "__main__":
    unittest.main()
