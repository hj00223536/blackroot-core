import hashlib
import unittest

from src.blackroot_genesis_package_audit import audit_genesis_package_inventory


_REQUIRED = (
    "manifest.json", "approval.json", "trust-anchors.json",
    "verification-report.md", "release-approval.md",
)


def package():
    return {name: (name + "\\n").encode() for name in _REQUIRED}


def pins(files):
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


class GenesisPackageInventoryTests(unittest.TestCase):
    def test_valid_inventory_returns_immutable_digest_map(self):
        files = package()
        result = audit_genesis_package_inventory(files, expected_sha256=pins(files))
        self.assertEqual(set(result), set(_REQUIRED))
        with self.assertRaises(TypeError):
            result["manifest.json"] = "00" * 32

    def test_missing_and_unexpected_files_rejected(self):
        files = package()
        del files["approval.json"]
        with self.assertRaisesRegex(ValueError, "missing required"):
            audit_genesis_package_inventory(files, expected_sha256=pins(files))
        files = package()
        files["unexpected.json"] = b"x"
        with self.assertRaisesRegex(ValueError, "unexpected"):
            audit_genesis_package_inventory(files, expected_sha256=pins(files))

    def test_external_pin_must_cover_exact_inventory(self):
        files = package()
        expected = pins(files)
        expected.pop("manifest.json")
        with self.assertRaisesRegex(ValueError, "exactly"):
            audit_genesis_package_inventory(files, expected_sha256=expected)

    def test_substitution_and_malformed_pin_rejected(self):
        files = package()
        expected = pins(files)
        files["manifest.json"] = b"substituted"
        with self.assertRaisesRegex(ValueError, "external SHA-256 pin"):
            audit_genesis_package_inventory(files, expected_sha256=expected)
        files = package()
        expected = pins(files)
        expected["manifest.json"] = "G" * 64
        with self.assertRaisesRegex(ValueError, "malformed"):
            audit_genesis_package_inventory(files, expected_sha256=expected)

    def test_optional_checksum_file_is_allowed(self):
        files = package()
        files["checksums.txt"] = b"transport checksum list"
        result = audit_genesis_package_inventory(files, expected_sha256=pins(files))
        self.assertIn("checksums.txt", result)

    def test_empty_required_artifact_rejected(self):
        files = package()
        files["approval.json"] = b""
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            audit_genesis_package_inventory(files, expected_sha256=pins(files))

    def test_nested_names_and_non_bytes_rejected(self):
        files = package()
        files["../manifest.json"] = b"x"
        with self.assertRaisesRegex(ValueError, "unexpected"):
            audit_genesis_package_inventory(files, expected_sha256=pins(files))
        files = package()
        files["manifest.json"] = "not bytes"
        with self.assertRaisesRegex(TypeError, "must be supplied as bytes"):
            audit_genesis_package_inventory(files, expected_sha256=pins(files))


if __name__ == "__main__":
    unittest.main()
