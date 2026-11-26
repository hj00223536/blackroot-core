import hashlib
import json
import unittest

from src.blackroot_genesis_trust import (
    calculate_trust_configuration_digest,
    parse_trust_configuration_json,
    validate_trust_configuration,
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

    def test_valid_config_and_key_material(self):
        config = make_config()
        validated = self.validate(config)
        self.assertEqual(validated.config_digest, config["config_digest"])
        self.assertEqual(validated.keys[_KEY_ID].public_key, _PUBLIC)
        self.assertEqual(validated.keys[_KEY_ID].status, "active")

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


if __name__ == "__main__":
    unittest.main()
