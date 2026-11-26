import hashlib
import json
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from src.blackroot_genesis_approval import approval_message
from src.blackroot_genesis_manifest import ValidatedGenesisManifest

from src.blackroot_genesis_trust import (
    calculate_trust_configuration_digest,
    parse_trust_configuration_json,
    validate_trust_configuration,
    verify_approval_with_validated_trust,
)

_NETWORK = "11" * 32
_PUBLIC = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
_KEY_ID = hashlib.sha256(_PUBLIC).hexdigest()


def make_config(sequence=1, previous=None):
    config = {
        "config_version": 1,
        "network_id": _NETWORK,
        "sequence": sequence,
        "previous_config_digest": previous,
        "keys": [{
            "key_id": _KEY_ID,
            "public_key": _PUBLIC.hex(),
            "scopes": ["genesis-founder-allocation"],
            "status": "active",
        }],
    }
    config["config_digest"] = calculate_trust_configuration_digest(config)
    return config


class TrustConfigurationTests(unittest.TestCase):
    def validate(self, config, **overrides):
        args = {
            "expected_network_id": _NETWORK,
            "pinned_config_digest": config["config_digest"],
            "expected_sequence": config["sequence"],
            "expected_previous_config_digest": config["previous_config_digest"],
        }
        args.update(overrides)
        return validate_trust_configuration(config, **args)

    def test_published_trust_configuration_digest_vector(self):
        self.assertEqual(
            make_config()["config_digest"],
            "157f3c321befaaaf8f9180c90fdb0ed3164ff9e71c070a664e14a7fbad1456ab",
        )

    def test_valid_config_and_key_material(self):
        config = make_config()
        validated = self.validate(config)
        self.assertEqual(validated.config_digest, config["config_digest"])
        self.assertEqual(validated.keys[_KEY_ID].public_key, _PUBLIC)
        self.assertEqual(validated.keys[_KEY_ID].status, "active")
        with self.assertRaises(TypeError):
            validated.keys[_KEY_ID] = validated.keys[_KEY_ID]

    def test_external_digest_pin_and_network_are_required(self):
        config = make_config()
        with self.assertRaisesRegex(ValueError, "external pin"):
            self.validate(config, pinned_config_digest="22" * 32)
        with self.assertRaisesRegex(ValueError, "network mismatch"):
            self.validate(config, expected_network_id="33" * 32)

    def test_sequence_downgrade_and_predecessor_substitution_rejected(self):
        config = make_config(sequence=2, previous="44" * 32)
        with self.assertRaisesRegex(ValueError, "pinned sequence"):
            self.validate(config, expected_sequence=1)
        with self.assertRaisesRegex(ValueError, "predecessor mismatch"):
            self.validate(config, expected_previous_config_digest="55" * 32)

    def test_initial_configuration_cannot_claim_predecessor(self):
        config = make_config()
        config["previous_config_digest"] = "44" * 32
        config["config_digest"] = calculate_trust_configuration_digest(config)
        with self.assertRaisesRegex(ValueError, "must not name a predecessor"):
            self.validate(config)

    def test_duplicate_key_ids_or_public_keys_rejected(self):
        config = make_config()
        config["keys"].append(dict(config["keys"][0]))
        config["config_digest"] = calculate_trust_configuration_digest(config)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.validate(config)

    def test_bad_key_id_and_scope_escalation_rejected(self):
        config = make_config()
        config["keys"][0]["key_id"] = "22" * 32
        config["config_digest"] = calculate_trust_configuration_digest(config)
        with self.assertRaisesRegex(ValueError, "identifier mismatch"):
            self.validate(config)
        config = make_config()
        config["keys"][0]["scopes"] = ["*"]
        config["config_digest"] = calculate_trust_configuration_digest(config)
        with self.assertRaisesRegex(ValueError, "scope"):
            self.validate(config)

    def test_revoked_key_is_parsed_but_not_active(self):
        config = make_config()
        config["keys"][0]["status"] = "revoked"
        config["config_digest"] = calculate_trust_configuration_digest(config)
        validated = self.validate(config)
        self.assertEqual(validated.keys[_KEY_ID].status, "revoked")

    def test_unknown_fields_and_bad_digest_rejected(self):
        config = make_config()
        config["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            self.validate(config)
        config = make_config()
        config["config_digest"] = "00" * 32
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.validate(config)

    def test_strict_json_parser(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_trust_configuration_json('{"config_version":1,"config_version":1}')
        with self.assertRaisesRegex(ValueError, "floating-point"):
            parse_trust_configuration_json('{"config_version":1.0}')
        with self.assertRaisesRegex(ValueError, "root must be an object"):
            parse_trust_configuration_json("[]")


class TrustBoundApprovalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
        ))
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.key_id = hashlib.sha256(self.public).hexdigest()
        self.digest = "22" * 32
        self.manifest = ValidatedGenesisManifest(
            manifest_digest=self.digest,
            network_id=_NETWORK,
            genesis_block_hash="33" * 32,
            coinbase=None,
            founder_output_index=0,
            founder_amount_sats=1,
            founder_script_pub_key=b"\x51",
            total_supply_cap_sats=2,
            mining_schedule_id="44" * 32,
            approval_record="detached",
        )
        self.approval = {
            "record_version": 1,
            "network_id": _NETWORK,
            "manifest_digest": self.digest,
            "approval_scope": "genesis-founder-allocation",
            "signing_key_id": self.key_id,
            "signature_algorithm": "Ed25519",
            "signature": self.private.sign(
                approval_message(_NETWORK, self.digest)
            ).hex(),
        }

    def make_validated_trust(self, status="active", network=_NETWORK):
        config = {
            "config_version": 1,
            "network_id": network,
            "sequence": 1,
            "previous_config_digest": None,
            "keys": [{
                "key_id": self.key_id,
                "public_key": self.public.hex(),
                "scopes": ["genesis-founder-allocation"],
                "status": status,
            }],
        }
        config["config_digest"] = calculate_trust_configuration_digest(config)
        return validate_trust_configuration(
            config,
            expected_network_id=network,
            pinned_config_digest=config["config_digest"],
            expected_sequence=1,
            expected_previous_config_digest=None,
        )

    def test_approval_uses_only_active_key_from_validated_trust(self):
        self.assertEqual(
            verify_approval_with_validated_trust(
                self.manifest, json.dumps(self.approval),
                self.make_validated_trust(),
            ),
            self.key_id,
        )

    def test_revoked_key_cannot_approve(self):
        with self.assertRaisesRegex(ValueError, "revoked"):
            verify_approval_with_validated_trust(
                self.manifest, json.dumps(self.approval),
                self.make_validated_trust(status="revoked"),
            )

    def test_cross_network_trust_configuration_rejected(self):
        with self.assertRaisesRegex(ValueError, "network does not match"):
            verify_approval_with_validated_trust(
                self.manifest, json.dumps(self.approval),
                self.make_validated_trust(network="55" * 32),
            )


if __name__ == "__main__":
    unittest.main()
