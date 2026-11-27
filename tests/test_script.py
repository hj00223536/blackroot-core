import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from src.blackroot_script import (
    N, _der_signature, _hash160, _push, legacy_sighash_all, p2pkh_script,
    verify_p2pkh_input, validate_transaction_scripts,
)
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput


def sign_for_test(digest, private_key):
    signature = private_key.sign(
        digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))
    )
    r, s = utils.decode_dss_signature(signature)
    if s > N // 2:
        s = N - s
    return utils.encode_dss_signature(r, s)


class P2PKHScriptTests(unittest.TestCase):
    def setUp(self):
        self.private_key = ec.derive_private_key(1, ec.SECP256K1())
        self.pubkey = self.private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        )
        self.previous = OutPoint(bytes.fromhex("12" * 32), 0)
        self.previous_output = TxOutput(100_000, p2pkh_script(_hash160(self.pubkey)))

    def signed_tx(self):
        unsigned = Transaction(
            1, (TxInput(self.previous),),
            (TxOutput(90_000, b"\x51"),),
        )
        digest = legacy_sighash_all(unsigned, 0, self.previous_output.script_pubkey)
        signature = sign_for_test(digest, self.private_key) + b"\x01"
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

    def test_der_parser_rejects_noncanonical_and_trailing_encodings(self):
        tx = self.signed_tx()
        signature = tx.inputs[0].script_sig
        signature_length = signature[0]
        der = signature[1:1 + signature_length - 1]
        self.assertIsNotNone(_der_signature(der))
        self.assertIsNone(_der_signature(der + b"\x00"))
        self.assertIsNone(_der_signature(b"\x30\x00"))
        # A positive DER INTEGER may not contain an unnecessary leading zero.
        self.assertIsNone(_der_signature(
            b"\x30\x07\x02\x02\x00\x01\x02\x01\x01"
        ))

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
