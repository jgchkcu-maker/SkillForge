import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import detector
from artifact_installer import install_mcp, install_skill, preview_mcp

APP_DIRECTORY = Path(__file__).with_name("skill-forge")
if str(APP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(APP_DIRECTORY))
try:
    import app as skillforge_app
except ModuleNotFoundError:  # Flask is optional in the lightweight test runtime.
    skillforge_app = None


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

    def test_selects_named_skill_from_a_multi_skill_repository(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            project = Path(root) / "project"
            (source / "skills" / "first").mkdir(parents=True)
            (source / "skills" / "second").mkdir(parents=True)
            project.mkdir()
            (source / "skills" / "first" / "SKILL.md").write_text("# First", encoding="utf-8")
            (source / "skills" / "second" / "SKILL.md").write_text("# Second", encoding="utf-8")
            results = install_skill(f"{source}#skill=second", ["kilo"], "project", str(project))
            self.assertEqual(results[0]["status"], "installed")
            self.assertTrue((project / ".kilo/skills/second/SKILL.md").exists())
        self.assertFalse((project / ".kilo/skills/first").exists())

    def test_normalizes_skill_manifest_line_endings(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            project = Path(root) / "project"
            source.mkdir()
            project.mkdir()
            (source / "SKILL.md").write_bytes(
                b"---\r\nname: demo-skill\r\ndescription: Demo\r\n---\r\n"
            )
            results = install_skill(str(source), ["kilo"], "project", str(project))
            self.assertEqual(results[0]["status"], "installed")
            installed = (project / ".kilo/skills/source/SKILL.md").read_bytes()
            self.assertNotIn(b"\r", installed)
            self.assertTrue(installed.startswith(b"---\n"))

    def test_clone_failure_is_reported_to_the_operation_log(self):
        messages = []
        with tempfile.TemporaryDirectory() as root:
            with patch("artifact_installer.subprocess.run") as run:
                run.return_value.returncode = 128
                run.return_value.stderr = "fatal: repository not found"
                run.return_value.stdout = ""
                results = install_skill("https://github.com/example/missing", ["kilo"], "project", root, log_callback=lambda message, level: messages.append((message, level)))
        self.assertEqual(results[0]["status"], "failed")
        self.assertTrue(any("repository not found" in message and level == "error" for message, level in messages))

    def test_multi_skill_source_explains_how_to_select_one(self):
        messages = []
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            project = Path(root) / "project"
            (source / "alpha").mkdir(parents=True)
            (source / "beta").mkdir(parents=True)
            project.mkdir()
            (source / "alpha" / "SKILL.md").write_text("# Alpha", encoding="utf-8")
            (source / "beta" / "SKILL.md").write_text("# Beta", encoding="utf-8")
            results = install_skill(str(source), ["kilo"], "project", str(project), log_callback=lambda message, level: messages.append((message, level)))
        self.assertEqual(results[0]["status"], "failed")
        self.assertTrue(any("#skill=NAME" in message and level == "error" for message, level in messages))

    @unittest.skipUnless(skillforge_app is not None, "Flask is not installed in this test runtime")
    def test_api_reuses_an_active_identical_install_job(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            source = Path(root) / "demo-skill"
            project.mkdir()
            source.mkdir()
            (source / "SKILL.md").write_text("# Demo", encoding="utf-8")
            payload = {"source": str(source), "project": str(project), "scope": "project", "artifact_type": "skill", "agents": ["kilo"]}
            started, release = threading.Event(), threading.Event()
            original_run = skillforge_app._run_install

            def blocked_run(job_id, job_payload):
                started.set()
                release.wait(timeout=2)
                original_run(job_id, job_payload)

            with patch.object(skillforge_app, "_run_install", side_effect=blocked_run):
                client = skillforge_app.app.test_client()
                first = client.post("/api/install", json=payload)
                self.assertTrue(started.wait(timeout=1))
                second = client.post("/api/install", json=payload)
                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 200)
                self.assertEqual(first.json["jobId"], second.json["jobId"])
                self.assertTrue(second.json["deduplicated"])
                release.set()
                deadline = time.time() + 2
                while time.time() < deadline:
                    with skillforge_app.lock:
                        if first.json["jobId"] not in skillforge_app.active_install_keys.values():
                            break
                    time.sleep(0.01)
                with skillforge_app.lock:
                    self.assertNotIn(first.json["jobId"], skillforge_app.active_install_keys.values())

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
