import hashlib
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from src.blackroot_genesis_approval import (approval_message, parse_genesis_approval_record_json, verify_genesis_approval_record)


# RFC 8032 test vector seed/public key; public test material only.
_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
_NETWORK = "11" * 32
_DIGEST = "22" * 32


class GenesisApprovalTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.from_private_bytes(_SEED)
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.key_id = hashlib.sha256(self.public).hexdigest()
        self.record = {
            "record_version": 1,
            "network_id": _NETWORK,
            "manifest_digest": _DIGEST,
            "approval_scope": "genesis-founder-allocation",
            "signing_key_id": self.key_id,
            "signature_algorithm": "Ed25519",
            "signature": self.private.sign(approval_message(_NETWORK, _DIGEST)).hex(),
        }
        self.trust = {self.key_id: self.public}

    def verify(self, record=None, **kwargs):
        return verify_genesis_approval_record(
            self.record if record is None else record,
            expected_network_id=_NETWORK,
            expected_manifest_digest=_DIGEST,
            trusted_public_keys=self.trust,
            **kwargs,
        )

    def test_valid_detached_signature(self):
        self.assertEqual(self.verify(), self.key_id)

    def test_signature_cannot_be_replayed_for_other_manifest(self):
        changed = dict(self.record, manifest_digest="33" * 32)
        with self.assertRaisesRegex(ValueError, "manifest_digest"):
            self.verify(changed)

    def test_network_scope_algorithm_and_fields_are_bound(self):
        cases = [
            (dict(self.record, network_id="44" * 32), "network_id"),
            (dict(self.record, approval_scope="other"), "scope"),
            (dict(self.record, signature_algorithm="none"), "algorithm"),
            ({**self.record, "extra": "field"}, "fields"),
        ]
        for record, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.verify(record)

    def test_unknown_or_revoked_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "trusted public-key"):
            verify_genesis_approval_record(
                self.record, expected_network_id=_NETWORK,
                expected_manifest_digest=_DIGEST, trusted_public_keys={},
            )
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.verify(revoked_key_ids=frozenset({self.key_id}))

    def test_bad_signature_and_noncanonical_encoding_are_rejected(self):
        changed = dict(self.record, signature=("00" * 64))
        with self.assertRaisesRegex(ValueError, "signature verification"):
            self.verify(changed)
        changed = dict(self.record, signature=self.record["signature"].upper())
        with self.assertRaisesRegex(ValueError, "canonical lowercase"):
            self.verify(changed)

    def test_strict_approval_json_rejects_duplicate_keys_floats_and_non_objects(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_genesis_approval_record_json('{"record_version":1,"record_version":1}')
        with self.assertRaisesRegex(ValueError, "floating-point"):
            parse_genesis_approval_record_json('{"record_version":1.0}')
        with self.assertRaisesRegex(ValueError, "root must be an object"):
            parse_genesis_approval_record_json('[]')

    def test_public_key_trust_anchor_must_match_identifier(self):
        wrong = {self.key_id: bytes(32)}
        with self.assertRaisesRegex(ValueError, "identifier mismatch"):
            verify_genesis_approval_record(
                self.record, expected_network_id=_NETWORK,
                expected_manifest_digest=_DIGEST, trusted_public_keys=wrong,
            )


if __name__ == "__main__":
    unittest.main()
