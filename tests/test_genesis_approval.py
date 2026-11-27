import hashlib
import unittest
from collections.abc import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from src.blackroot_genesis_approval import (approval_message, parse_genesis_approval_record_json, verify_genesis_approval_record, verify_validated_genesis_manifest_approval)
from src.blackroot_genesis_manifest import ValidatedGenesisManifest


# RFC 8032 test vector seed/public key; public test material only.
_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
_NETWORK = "11" * 32
_DIGEST = "22" * 32


class ValidatedManifestApprovalBindingTests(unittest.TestCase):
    def test_detached_record_is_bound_to_validated_manifest(self):
        private = Ed25519PrivateKey.from_private_bytes(_SEED)
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        key_id = hashlib.sha256(public).hexdigest()
        validated = ValidatedGenesisManifest(
            manifest_digest=_DIGEST,
            network_id=_NETWORK,
            genesis_block_hash="33" * 32,
            coinbase=None,
            founder_output_index=1,
            founder_amount_sats=2_000_000_000_000_000,
            founder_script_pub_key=b"\x51",
            total_supply_cap_sats=4_000_000_000_000_000,
            mining_schedule_id="44" * 32,
            approval_record="detached-record-reference",
        )
        record = {
            "record_version": 1,
            "network_id": _NETWORK,
            "manifest_digest": _DIGEST,
            "approval_scope": "genesis-founder-allocation",
            "signing_key_id": key_id,
            "signature_algorithm": "Ed25519",
            "signature": private.sign(approval_message(_NETWORK, _DIGEST)).hex(),
        }
        import json
        encoded = json.dumps(record, separators=(",", ":"))
        self.assertEqual(
            verify_validated_genesis_manifest_approval(
                validated, encoded, trusted_public_keys={key_id: public}
            ),
            key_id,
        )

        altered = dict(record, manifest_digest="55" * 32)
        with self.assertRaisesRegex(ValueError, "manifest_digest"):
            verify_validated_genesis_manifest_approval(
                validated, json.dumps(altered), trusted_public_keys={key_id: public}
            )

    def test_binding_rejects_unvalidated_object_and_bad_json(self):
        with self.assertRaises(TypeError):
            verify_validated_genesis_manifest_approval(
                object(), "{}", trusted_public_keys={}
            )
        validated = ValidatedGenesisManifest(
            manifest_digest=_DIGEST, network_id=_NETWORK,
            genesis_block_hash="33" * 32, coinbase=None,
            founder_output_index=1, founder_amount_sats=1,
            founder_script_pub_key=b"\x51", total_supply_cap_sats=2,
            mining_schedule_id="44" * 32, approval_record="reference",
        )
        with self.assertRaisesRegex(ValueError, "approval JSON is invalid"):
            verify_validated_genesis_manifest_approval(
                validated, "{", trusted_public_keys={}
            )


class Ed25519PublishedVectorTests(unittest.TestCase):
    def test_rfc8032_empty_message_vector(self):
        public = bytes.fromhex(
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
        )
        signature = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        from cryptography.exceptions import InvalidSignature
        key = Ed25519PublicKey.from_public_bytes(public)
        key.verify(signature, b"")
        with self.assertRaises(InvalidSignature):
            key.verify(signature, b"changed")


class MutatingTrustedKeys(Mapping):
    def __init__(self, key_id, public_key):
        self.key_id = key_id
        self.public_key = public_key
        self.reads = 0

    def __iter__(self):
        return iter((self.key_id,))

    def __len__(self):
        return 1

    def __getitem__(self, key):
        self.reads += 1
        if key != self.key_id:
            raise KeyError(key)
        return self.public_key if self.reads == 1 else bytes(32)


class MutatingApprovalRecord(Mapping):
    def __init__(self, values):
        self.values = dict(values)
        self.reads = {}

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)

    def __getitem__(self, key):
        count = self.reads.get(key, 0) + 1
        self.reads[key] = count
        value = self.values[key]
        if key == "manifest_digest" and count > 1:
            return "ff" * 32
        return value


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

    def test_verification_uses_one_snapshot_of_trusted_key_mapping(self):
        supplied = MutatingTrustedKeys(self.key_id, self.public)
        self.assertEqual(
            verify_genesis_approval_record(
                self.record,
                expected_network_id=_NETWORK,
                expected_manifest_digest=_DIGEST,
                trusted_public_keys=supplied,
            ),
            self.key_id,
        )
        self.assertEqual(supplied.reads, 1)


    def test_verification_uses_one_snapshot_of_mutable_record(self):
        supplied = MutatingApprovalRecord(self.record)
        self.assertEqual(self.verify(supplied), self.key_id)
        self.assertEqual(supplied.reads.get("manifest_digest"), 1)


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

    def test_malformed_unused_trust_entries_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "identifier mismatch"):
            verify_genesis_approval_record(
                self.record,
                expected_network_id=_NETWORK,
                expected_manifest_digest=_DIGEST,
                trusted_public_keys={
                    **self.trust,
                    hashlib.sha256(b"unrelated").hexdigest(): bytes(32),
                },
            )
        with self.assertRaisesRegex(ValueError, "revoked key identifier"):
            self.verify(revoked_key_ids=frozenset({"not-a-key-id"}))


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
