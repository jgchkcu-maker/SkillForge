import json
import tempfile
import unittest
from pathlib import Path

import detector
from artifact_installer import install_mcp, install_skill, preview_mcp


class SkillForgeAgentTests(unittest.TestCase):
    def test_detection_is_cached(self):
        first = detector.detect_agents(force=True)
        second = detector.detect_agents()
        self.assertIs(first, second)
        self.assertEqual({"kilo", "codex", "claude", "cline", "gemini", "copilot", "roo", "antigravity", "cursor", "windsurf"}, {item["id"] for item in first["agents"]})

    def test_skill_installs_to_multiple_project_targets(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as source_root:
            project = Path(root) / "project"
            skill = Path(source_root) / "demo-skill"
            project.mkdir()
            skill.mkdir()
            (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Demo\n---\n", encoding="utf-8")
            results = install_skill(str(skill), ["kilo", "codex", "windsurf"], "project", str(project))
            self.assertEqual([item["status"] for item in results], ["installed", "installed", "unsupported"])
            self.assertTrue((project / ".kilo/skills/demo-skill/SKILL.md").exists())
            self.assertTrue((project / ".agents/skills/demo-skill/SKILL.md").exists())

    def test_mcp_preview_requires_confirmation_and_merges_config(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            options = {"name": "demo", "command": "npx", "args": ["-y", "demo-mcp"], "transport": "stdio"}
            preview = preview_mcp(["kilo"], "project", str(project), options)
            self.assertTrue(preview["requires_confirmation"])
            results = install_mcp(["kilo"], "project", str(project), options)
            self.assertEqual(results[0]["status"], "installed")
            data = json.loads((project / ".kilo/kilo.json").read_text(encoding="utf-8"))
            self.assertEqual(data["mcp"]["demo"]["command"], "npx")


if __name__ == "__main__":
    unittest.main()
