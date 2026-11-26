import ast
import unittest
from pathlib import Path


class BootstrapIssuanceBoundaryTests(unittest.TestCase):
    """Keep the trusted bootstrap primitive out of node and P2P call paths."""

    def test_no_production_source_calls_or_aliases_bootstrap_issuer(self):
        source_root = Path(__file__).resolve().parents[1] / "src"
        definitions = []
        references = []
        call_sites = []

        for source_path in sorted(source_root.glob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == "add_genesis_output":
                        definitions.append(source_path.name)
                if isinstance(node, ast.Attribute) and node.attr == "add_genesis_output":
                    references.append((source_path.name, node.lineno))
                    if isinstance(node.ctx, ast.Load):
                        call_sites.append((source_path.name, node.lineno))
                elif isinstance(node, ast.Name) and node.id == "add_genesis_output":
                    references.append((source_path.name, node.lineno))
                    if isinstance(node.ctx, ast.Load):
                        call_sites.append((source_path.name, node.lineno))
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for imported in node.names:
                        if imported.name == "add_genesis_output":
                            references.append((source_path.name, node.lineno))
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"getattr", "setattr", "hasattr"}
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "add_genesis_output"
                ):
                    references.append((source_path.name, node.lineno))
                    call_sites.append((source_path.name, node.lineno))

        self.assertEqual(definitions, ["blackroot_utxo_db.py"])
        self.assertEqual(
            references,
            [],
            "production source must not reference the trusted bootstrap issuer",
        )
        self.assertEqual(call_sites, [])


if __name__ == "__main__":
    unittest.main()
