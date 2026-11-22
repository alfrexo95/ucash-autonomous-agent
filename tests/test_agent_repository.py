# -*- coding: utf-8 -*-
import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def handler_keys(path):
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "HANDLERS":
                    if isinstance(node.value, ast.Dict):
                        return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


class AgentRepositoryTests(unittest.TestCase):
    def test_agent_scripts_compile(self):
        for rel in ("agent.py", "multimodal/agent.py", "core_logic.py"):
            with self.subTest(rel=rel):
                compile((ROOT / rel).read_text(), rel, "exec")

    def test_registered_paid_resources_match_handlers(self):
        main_state = json.loads((ROOT / "ucash_state.json").read_text())
        multimodal_state = json.loads((ROOT / "multimodal/ucash_state.json").read_text())
        main_handlers = handler_keys(ROOT / "agent.py")
        multimodal_handlers = handler_keys(ROOT / "multimodal/agent.py")
        self.assertEqual(set(main_state["resources"]), main_handlers)
        self.assertEqual(set(multimodal_state["resources"]), multimodal_handlers)
        self.assertEqual(len(main_handlers), 3)
        self.assertEqual(len(multimodal_handlers), 8)

    def test_scheduled_workflows_register_agents_before_polling(self):
        main = (ROOT / ".github/workflows/agent.yml").read_text()
        multi = (ROOT / ".github/workflows/multimodal.yml").read_text()
        self.assertIn("cron: '*/30 * * * *'", main)
        self.assertIn("cron: '0 * * * *'", multi)
        self.assertLess(main.index("Register U.CASH agent with Predator Hub before processing"), main.index("Run Agent"))
        self.assertLess(multi.index("Register U.CASH multimodal agent with Predator Hub before processing"), multi.index("Run Multimodal Agent"))

    def test_direct_x402_manifest_is_not_published(self):
        self.assertFalse((ROOT / ".well-known/x402").exists())


if __name__ == "__main__":
    unittest.main()
