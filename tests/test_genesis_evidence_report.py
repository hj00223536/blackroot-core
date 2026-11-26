import hashlib
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.blackroot_genesis_approval import approval_message
from src.blackroot_genesis_evidence_report import (
    build_genesis_evidence_report,
    serialize_genesis_evidence_report,
)
from src.blackroot_genesis_manifest import ValidatedGenesisManifest
from src.blackroot_genesis_trust import calculate_trust_configuration_digest, validate_trust_configuration


class GenesisEvidenceReportTests(unittest.TestCase):
    def setUp(self):
        self.network = "11" * 32
        self.digest = "22" * 32
        self.private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
        ))
        public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.key_id = hashlib.sha256(public).hexdigest()
        self.manifest = ValidatedGenesisManifest(
            manifest_digest=self.digest, network_id=self.network,
            genesis_block_hash="33" * 32, coinbase=None,
            founder_output_index=0, founder_amount_sats=1,
            founder_script_pub_key=b"\\x51", total_supply_cap_sats=2,
            mining_schedule_id="44" * 32, approval_record="detached",
        )
        self.approval = {
            "record_version": 1, "network_id": self.network,
            "manifest_digest": self.digest,
            "approval_scope": "genesis-founder-allocation",
            "signing_key_id": self.key_id, "signature_algorithm": "Ed25519",
            "signature": self.private.sign(approval_message(self.network, self.digest)).hex(),
        }
        config = {
            "config_version": 1, "network_id": self.network, "sequence": 1,
            "previous_config_digest": None,
            "keys": [{
                "key_id": self.key_id, "public_key": public.hex(),
                "scopes": ["genesis-founder-allocation"], "status": "active",
            }],
        }
        config["config_digest"] = calculate_trust_configuration_digest(config)
        self.trust = validate_trust_configuration(
            config, expected_network_id=self.network,
            pinned_config_digest=config["config_digest"], expected_sequence=1,
            expected_previous_config_digest=None,
        )

    def test_report_passes_evidence_but_never_authorizes_release(self):
        report = build_genesis_evidence_report(
            self.manifest, json.dumps(self.approval), self.trust
        )
        self.assertEqual(report["verification_result"], "passed")
        self.assertEqual(report["authorization_result"], "not-authorized")
        self.assertFalse(report["consensus_validation_performed"])
        self.assertFalse(report["database_initialization_performed"])
        self.assertFalse(report["issuance_performed"])
        self.assertFalse(report["public_release_authorized"])
        self.assertEqual(report["approval_key_id"], self.key_id)

    def test_serialization_is_deterministic(self):
        report = build_genesis_evidence_report(
            self.manifest, json.dumps(self.approval), self.trust
        )
        self.assertEqual(
            serialize_genesis_evidence_report(report),
            serialize_genesis_evidence_report(dict(reversed(list(report.items())))),
        )

    def test_invalid_signature_prevents_report(self):
        bad = dict(self.approval)
        bad["signature"] = "00" * 64
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            build_genesis_evidence_report(self.manifest, json.dumps(bad), self.trust)


if __name__ == "__main__":
    unittest.main()
