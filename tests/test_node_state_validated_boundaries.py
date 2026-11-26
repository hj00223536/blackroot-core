import ast
import unittest
from pathlib import Path


class NodeStateValidatedBoundaryTests(unittest.TestCase):
    """Keep node-facing state transitions on header-validated UTXO APIs."""

    @classmethod
    def setUpClass(cls):
        source_path = Path(__file__).resolve().parents[1] / "src" / "blackroot_node_state.py"
        cls.tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        cls.node_state = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PersistentNodeState"
        )

    def _method_calls(self, method_name):
        method = next(
            node for node in self.node_state.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == method_name
        )
        return {
            node.func.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_connect_best_block_uses_only_validated_block_entrypoint(self):
        calls = self._method_calls("connect_best_block")
        self.assertIn("connect_validated_block", calls)
        self.assertNotIn("connect_block", calls)

    def test_reorganize_best_uses_only_validated_reorganization_entrypoint(self):
        calls = self._method_calls("reorganize_best")
        self.assertIn("reorganize_to_best", calls)
        self.assertNotIn("reorganize", calls)


if __name__ == "__main__":
    unittest.main()
