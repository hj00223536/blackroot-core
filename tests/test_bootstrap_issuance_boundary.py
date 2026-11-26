import ast
import unittest
from pathlib import Path


BOOTSTRAP_ISSUER = "add_genesis_output"


def static_string_value(node):
    """Return a statically known string for simple literal expressions."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = static_string_value(node.left)
        right = static_string_value(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr) and all(
        isinstance(part, ast.Constant) and isinstance(part.value, str)
        for part in node.values
    ):
        return "".join(part.value for part in node.values)
    return None


def find_bootstrap_issuer_references(source: str, source_name: str = "<source>"):
    """Find common static references to the trusted bootstrap storage primitive."""
    tree = ast.parse(source, filename=source_name)
    references = []
    definitions = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == BOOTSTRAP_ISSUER:
                definitions.append((source_name, node.lineno))

        if isinstance(node, ast.Attribute) and node.attr == BOOTSTRAP_ISSUER:
            references.append((source_name, node.lineno))
        elif isinstance(node, ast.Name) and node.id == BOOTSTRAP_ISSUER:
            references.append((source_name, node.lineno))
        elif static_string_value(node) == BOOTSTRAP_ISSUER:
            # Catch literal and constant-foldable string lookup through vars(),
            # __dict__, globals(), getattr(), or other reflective APIs.
            references.append((source_name, node.lineno))

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for imported in node.names:
                if imported.name == BOOTSTRAP_ISSUER:
                    references.append((source_name, node.lineno))

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "setattr", "hasattr"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == BOOTSTRAP_ISSUER
        ):
            references.append((source_name, node.lineno))

    return definitions, references


class BootstrapIssuanceBoundaryTests(unittest.TestCase):
    """Keep the trusted bootstrap primitive out of node and P2P call paths."""

    def test_scanner_detects_common_static_reference_forms(self):
        samples = (
            "store.add_genesis_output(outpoint, output)",
            "from src.blackroot_utxo_db import add_genesis_output as issue",
            'issuer = getattr(store, "add_genesis_output")',
            'hasattr(store, "add_genesis_output")',
            'setattr(store, "add_genesis_output", replacement)',
            'store.__dict__["add_genesis_output"](outpoint, output)',
            'globals()["add_genesis_output"]',
            'getattr(store, "add_" + "genesis_output")',
            'getattr(store, f"add_genesis_output")',
        )
        for source in samples:
            with self.subTest(source=source):
                _definitions, references = find_bootstrap_issuer_references(source)
                self.assertTrue(references)

    def test_scanner_does_not_claim_to_resolve_dynamic_name_construction(self):
        # Dynamic expressions require runtime analysis; this regression guard
        # intentionally reports only statically knowable references.
        source = 'getattr(store, "".join(["add_", "genesis_output"]))'
        _definitions, references = find_bootstrap_issuer_references(source)
        self.assertEqual(references, [])

    def test_no_production_source_references_bootstrap_issuer(self):
        source_root = Path(__file__).resolve().parents[1] / "src"
        definitions = []
        references = []

        for source_path in sorted(source_root.glob("*.py")):
            found_definitions, found_references = find_bootstrap_issuer_references(
                source_path.read_text(encoding="utf-8"),
                source_path.name,
            )
            definitions.extend(found_definitions)
            references.extend(found_references)

        self.assertEqual(
            [name for name, _line in definitions],
            ["blackroot_utxo_db.py"],
        )
        self.assertEqual(
            references,
            [],
            "production source must not reference the trusted bootstrap issuer",
        )


if __name__ == "__main__":
    unittest.main()
