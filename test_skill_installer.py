#!/usr/bin/env python3
"""
Tests for skill_installer.py

Covers:
- URL parsing and strategy selection
- Command-line path extraction heuristics
- Project context detection
- Installation orchestration (with mocked subprocess)
- requirements.txt update logic
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import skill_installer as si


class TestParseUrl(unittest.TestCase):
    def test_github_https(self):
        strategy, id_ = si.parse_url("https://github.com/owner/repo")
        self.assertEqual(strategy, "git_clone")
        self.assertEqual(id_, "repo")

    def test_github_https_with_git_suffix(self):
        strategy, id_ = si.parse_url("https://github.com/owner/repo.git")
        self.assertEqual(strategy, "git_clone")
        self.assertEqual(id_, "repo")

    def test_github_https_trailing_slash(self):
        strategy, id_ = si.parse_url("https://github.com/owner/repo/")
        self.assertEqual(strategy, "git_clone")
        self.assertEqual(id_, "repo")

    def test_git_https_generic(self):
        strategy, id_ = si.parse_url("https://example.com/path/to/repo.git")
        self.assertEqual(strategy, "git_clone")
        self.assertEqual(id_, "repo")

    def test_git_http_generic(self):
        strategy, id_ = si.parse_url("http://example.com/path/to/repo.git")
        self.assertEqual(strategy, "git_clone")
        self.assertEqual(id_, "repo")

    def test_git_ssh_url(self):
        strategy, id_ = si.parse_url("git@github.com:owner/repo.git")
        self.assertEqual(strategy, "git_clone")
        self.assertEqual(id_, "repo")

    def test_npmjs_url(self):
        strategy, id_ = si.parse_url("https://www.npmjs.com/package/lodash")
        self.assertEqual(strategy, "npm_install")
        self.assertEqual(id_, "lodash")

    def test_npmjs_url_no_www(self):
        strategy, id_ = si.parse_url("https://npmjs.com/package/lodash")
        self.assertEqual(strategy, "npm_install")
        self.assertEqual(id_, "lodash")

    def test_npmjs_url_trailing_slash(self):
        strategy, id_ = si.parse_url("https://www.npmjs.com/package/lodash/")
        self.assertEqual(strategy, "npm_install")

    def test_npm_alias(self):
        strategy, id_ = si.parse_url("npm:lodash")
        self.assertEqual(strategy, "npm_install")
        self.assertEqual(id_, "lodash")

    def test_pypi_url(self):
        strategy, id_ = si.parse_url("https://pypi.org/project/requests")
        self.assertEqual(strategy, "pip_install")
        self.assertEqual(id_, "requests")

    def test_pypi_url_trailing_slash(self):
        strategy, id_ = si.parse_url("https://pypi.org/project/requests/")
        self.assertEqual(strategy, "pip_install")

    def test_pip_alias(self):
        strategy, id_ = si.parse_url("pip:requests")
        self.assertEqual(strategy, "pip_install")
        self.assertEqual(id_, "requests")

    def test_bare_package_name(self):
        strategy, id_ = si.parse_url("my-tool")
        self.assertEqual(strategy, "bare_package")
        self.assertEqual(id_, "my-tool")

    def test_bare_package_name_with_underscores(self):
        strategy, id_ = si.parse_url("my_tool")
        self.assertEqual(strategy, "bare_package")

    def test_bare_package_name_with_numbers(self):
        strategy, id_ = si.parse_url("tool123")
        self.assertEqual(strategy, "bare_package")

    def test_unknown_url(self):
        strategy, id_ = si.parse_url("https://example.com/something")
        self.assertEqual(strategy, "unknown")
        self.assertEqual(id_, "https://example.com/something")

    def test_empty_url(self):
        strategy, id_ = si.parse_url("")
        self.assertEqual(strategy, "unknown")

    def test_case_insensitive_github(self):
        strategy, id_ = si.parse_url("HTTPS://GITHUB.COM/Owner/Repo")
        self.assertEqual(strategy, "git_clone")

    def test_case_insensitive_npm(self):
        strategy, id_ = si.parse_url("HTTPS://WWW.NPMJS.COM/PACKAGE/LODASH")
        self.assertEqual(strategy, "npm_install")


class TestLooksLikeProjectPath(unittest.TestCase):
    def test_windows_absolute_path(self):
        self.assertTrue(si._looks_like_project_path("C:\\Users\\dev\\project"))
        self.assertTrue(si._looks_like_project_path("D:\\work\\repo"))

    def test_unc_path(self):
        self.assertTrue(si._looks_like_project_path("\\\\server\\share\\folder"))

    def test_empty_string(self):
        self.assertFalse(si._looks_like_project_path(""))

    def test_flag_prefix_dash(self):
        self.assertFalse(si._looks_like_project_path("-v"))
        self.assertFalse(si._looks_like_project_path("--version"))

    def test_plain_word(self):
        self.assertFalse(si._looks_like_project_path("hello"))
        self.assertFalse(si._looks_like_project_path("project"))

    def test_relative_path_with_backslash(self):
        # Relative paths are no longer considered project paths
        self.assertFalse(si._looks_like_project_path("relative\\path"))

    def test_relative_path_with_forward_slash(self):
        # Relative paths are no longer considered project paths
        self.assertFalse(si._looks_like_project_path("relative/path"))


class TestExtractPathsFromCmdline(unittest.TestCase):
    def test_quoted_windows_path(self):
        cmdline = '"C:\\Users\\dev\\my project" --some-flag'
        paths = si._extract_paths_from_cmdline(cmdline)
        self.assertIn("C:\\Users\\dev\\my project", paths)

    def test_unquoted_windows_path(self):
        cmdline = "C:\\Users\\dev\\myproject"
        paths = si._extract_paths_from_cmdline(cmdline)
        self.assertIn("C:\\Users\\dev\\myproject", paths)

    def test_unc_path_quoted(self):
        cmdline = '"\\\\server\\share\\repo"'
        paths = si._extract_paths_from_cmdline(cmdline)
        self.assertIn("\\\\server\\share\\repo", paths)

    def test_skips_vscode_flag_values(self):
        """Flag tokens and their values are skipped; user project paths are kept."""
        cmdline = "--extensionDevelopmentPath C:\\exts --folder-uri file:///c%3A/project C:\\Users\\dev\\other"
        paths = si._extract_paths_from_cmdline(cmdline)
        self.assertNotIn("--extensionDevelopmentPath", paths)
        self.assertNotIn("--folder-uri", paths)
        self.assertNotIn("C:\\exts", paths)
        self.assertNotIn("file:///c%3A/project", paths)
        self.assertIn("C:\\Users\\dev\\other", paths)

    def test_multiple_quoted_paths(self):
        cmdline = '"C:\\project1" "C:\\project2"'
        paths = si._extract_paths_from_cmdline(cmdline)
        self.assertIn("C:\\project1", paths)
        self.assertIn("C:\\project2", paths)

    def test_no_paths(self):
        cmdline = "--help --version"
        paths = si._extract_paths_from_cmdline(cmdline)
        self.assertEqual(paths, [])

    def test_mixed_flags_and_paths(self):
        cmdline = 'code.exe "C:\\my project" --new-window'
        paths = si._extract_paths_from_cmdline(cmdline)
        self.assertIn("C:\\my project", paths)

    def test_skip_code_exe_token(self):
        """Improved tokenization skips VS Code executable fragments."""
        cmdline = "C:\\Program Files\\Microsoft VS Code.exe C:\\work\\project"
        paths = si._extract_paths_from_cmdline(cmdline)
        self.assertFalse(any("Code.exe" in p for p in paths))
        self.assertIn("C:\\work\\project", paths)


class TestDetectProjectContext(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_path = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_no_files(self):
        ctx = si.detect_project_context(self.project_path)
        self.assertFalse(ctx["has_package_json"])
        self.assertFalse(ctx["has_requirements_txt"])
        self.assertFalse(ctx["has_pyproject_toml"])
        self.assertFalse(ctx["has_kilo_config"])
        self.assertFalse(ctx["is_git_repo"])

    def test_package_json(self):
        Path(self.project_path, "package.json").write_text("{}")
        ctx = si.detect_project_context(self.project_path)
        self.assertTrue(ctx["has_package_json"])

    def test_requirements_txt(self):
        Path(self.project_path, "requirements.txt").write_text("requests")
        ctx = si.detect_project_context(self.project_path)
        self.assertTrue(ctx["has_requirements_txt"])

    def test_pyproject_toml(self):
        Path(self.project_path, "pyproject.toml").write_text("[project]\nname='x'")
        ctx = si.detect_project_context(self.project_path)
        self.assertTrue(ctx["has_pyproject_toml"])

    def test_kilo_json(self):
        Path(self.project_path, "kilo.json").write_text("{}")
        ctx = si.detect_project_context(self.project_path)
        self.assertTrue(ctx["has_kilo_config"])

    def test_kilo_dir(self):
        (Path(self.project_path) / ".kilo").mkdir()
        ctx = si.detect_project_context(self.project_path)
        self.assertTrue(ctx["has_kilo_config"])

    def test_git_repo(self):
        (Path(self.project_path) / ".git").mkdir()
        ctx = si.detect_project_context(self.project_path)
        self.assertTrue(ctx["is_git_repo"])


class TestUpdateRequirementsTxt(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_path = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_creates_requirements_for_python_project(self):
        Path(self.project_path, "main.py").write_text("print('hello')")
        ctx = {"has_requirements_txt": False}
        si._update_requirements_txt(self.project_path, "requests", ctx)
        req_path = Path(self.project_path, "requirements.txt")
        self.assertTrue(req_path.exists())
        content = req_path.read_text()
        self.assertIn("requests", content)

    def test_appends_package_to_existing_requirements(self):
        req_path = Path(self.project_path, "requirements.txt")
        req_path.write_text("requests")
        ctx = {"has_requirements_txt": True}
        si._update_requirements_txt(self.project_path, "flask", ctx)
        content = req_path.read_text()
        self.assertIn("requests", content)
        self.assertIn("flask", content)

    def test_skips_duplicate_package(self):
        req_path = Path(self.project_path, "requirements.txt")
        req_path.write_text("requests\n")
        ctx = {"has_requirements_txt": True}
        si._update_requirements_txt(self.project_path, "requests", ctx)
        content = req_path.read_text()
        self.assertEqual(content.count("requests"), 1)

    def test_skips_non_python_project(self):
        Path(self.project_path, "index.js").write_text("console.log('hi')")
        ctx = {"has_requirements_txt": False}
        si._update_requirements_txt(self.project_path, "lodash", ctx)
        req_path = Path(self.project_path, "requirements.txt")
        self.assertFalse(req_path.exists())

    def test_strips_version_specifiers(self):
        Path(self.project_path, "main.py").write_text("print('hello')")
        ctx = {"has_requirements_txt": False}
        si._update_requirements_txt(
            self.project_path, "requests==2.31.0", ctx
        )
        req_path = Path(self.project_path, "requirements.txt")
        content = req_path.read_text()
        self.assertIn("requests", content)
        self.assertNotIn("==", content)

    def test_strips_greater_than(self):
        Path(self.project_path, "main.py").write_text("print('hello')")
        ctx = {"has_requirements_txt": False}
        si._update_requirements_txt(self.project_path, "numpy>=1.24", ctx)
        req_path = Path(self.project_path, "requirements.txt")
        content = req_path.read_text()
        self.assertIn("numpy", content)
        self.assertNotIn(">=", content)


class TestInstallGitClone(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_project = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clone_without_kilo_config(self):
        repo_name = "awesome-skill"
        url = f"https://github.com/owner/{repo_name}"
        dest = os.path.join(self.target_project, repo_name)
        context = {
            "has_kilo_config": False,
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = si.install_git_clone(url, self.target_project, context, scope="project")
            self.assertTrue(result)
            mock_run.assert_called_once_with(
                ["git", "clone", url, dest],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_clone_with_kilo_config(self):
        repo_name = "awesome-skill"
        url = f"https://github.com/owner/{repo_name}"
        kilo_dir = Path(self.target_project) / ".kilo" / "skills"
        kilo_dir.mkdir(parents=True)
        dest = os.path.join(self.target_project, si.KILO_SKILLS_DIR, repo_name)
        context = {
            "has_kilo_config": True,
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = si.install_git_clone(url, self.target_project, context, scope="project")
            self.assertTrue(result)
            mock_run.assert_called_once_with(
                ["git", "clone", url, dest],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_clone_global_scope(self):
        repo_name = "awesome-skill"
        url = f"https://github.com/owner/{repo_name}"
        context = {
            "has_kilo_config": False,
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "is_git_repo": False,
        }
        fake_global_dir = tempfile.mkdtemp()
        try:
            with patch.object(si, "GLOBAL_SKILLS_DIR", Path(fake_global_dir)):
                dest = os.path.join(fake_global_dir, repo_name)
                with patch("skill_installer.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    result = si.install_git_clone(url, self.target_project, context, scope="global")
                    self.assertTrue(result)
                    mock_run.assert_called_once_with(
                        ["git", "clone", url, dest],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
        finally:
            import shutil
            shutil.rmtree(fake_global_dir, ignore_errors=True)

    def test_existing_destination(self):
        repo_name = "awesome-skill"
        url = f"https://github.com/owner/{repo_name}"
        Path(self.target_project, repo_name).mkdir()
        context = {
            "has_kilo_config": False,
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "is_git_repo": False,
        }

        result = si.install_git_clone(url, self.target_project, context, scope="project")
        self.assertFalse(result)

    def test_git_clone_failure(self):
        repo_name = "awesome-skill"
        url = f"https://github.com/owner/{repo_name}"
        dest = os.path.join(self.target_project, repo_name)
        context = {
            "has_kilo_config": False,
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            result = si.install_git_clone(url, self.target_project, context, scope="project")
            self.assertFalse(result)


class TestInstallNpmPackage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_project = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_npm_install_with_package_json(self):
        Path(self.target_project, "package.json").write_text("{}")
        context = {
            "has_package_json": True,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = si.install_npm_package("lodash", self.target_project, context, scope="project")
            self.assertTrue(result)
            mock_run.assert_called_once_with(
                ["npm", "install", "--save-dev", "lodash"],
                cwd=self.target_project,
                check=True,
                capture_output=True,
                text=True,
            )

    def test_npm_install_global(self):
        context = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = si.install_npm_package("lodash", self.target_project, context, scope="global")
            self.assertTrue(result)
            mock_run.assert_called_once_with(
                ["npm", "install", "-g", "lodash"],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_npm_install_without_package_json(self):
        context = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }
        result = si.install_npm_package("lodash", self.target_project, context, scope="project")
        self.assertFalse(result)

    def test_npm_not_found(self):
        Path(self.target_project, "package.json").write_text("{}")
        context = {
            "has_package_json": True,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            result = si.install_npm_package("lodash", self.target_project, context, scope="project")
            self.assertFalse(result)


class TestInstallPipPackage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_project = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pip_install_success_creates_requirements(self):
        Path(self.target_project, "main.py").write_text("print('hello')")
        context = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = si.install_pip_package("requests", self.target_project, context, scope="project")
            self.assertTrue(result)
            mock_run.assert_called_once_with(
                [sys.executable, "-m", "pip", "install", "requests"],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_pip_install_updates_requirements_file(self):
        Path(self.target_project, "main.py").write_text("print('hello')")
        context = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run", return_value=MagicMock(returncode=0)):
            si.install_pip_package("requests", self.target_project, context, scope="project")

        req_path = Path(self.target_project, "requirements.txt")
        self.assertTrue(req_path.exists())
        self.assertIn("requests", req_path.read_text())

    def test_pip_install_global_skips_requirements_update(self):
        Path(self.target_project, "main.py").write_text("print('hello')")
        context = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run", return_value=MagicMock(returncode=0)):
            si.install_pip_package("requests", self.target_project, context, scope="global")

        req_path = Path(self.target_project, "requirements.txt")
        self.assertFalse(req_path.exists())

    def test_pip_not_found(self):
        context = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            result = si.install_pip_package("requests", self.target_project, context, scope="project")
            self.assertFalse(result)


class TestInstallBarePackage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_project = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prefers_npm_with_package_json(self):
        Path(self.target_project, "package.json").write_text("{}")
        context = {
            "has_package_json": True,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run", return_value=MagicMock(returncode=0)):
            result = si.install_bare_package("lodash", self.target_project, context, scope="project")
        self.assertTrue(result)

    def test_prefers_pip_with_requirements(self):
        Path(self.target_project, "requirements.txt").write_text("requests")
        context = {
            "has_package_json": False,
            "has_requirements_txt": True,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("skill_installer.subprocess.run", return_value=MagicMock(returncode=0)):
            result = si.install_bare_package("flask", self.target_project, context, scope="project")
        self.assertTrue(result)

    def test_unknown_context_defaults_to_npm(self):
        context = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("builtins.input", return_value="n"):
            with patch.object(si, "install_npm_package", return_value=True) as mock_npm:
                result = si.install_bare_package("some-package", self.target_project, context, scope="project")
        self.assertTrue(result)
        mock_npm.assert_called_once_with("some-package", self.target_project, context, scope="project")

    def test_unknown_context_chooses_pip(self):
        context = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }

        with patch("builtins.input", return_value="p"):
            with patch.object(si, "install_pip_package", return_value=True) as mock_pip:
                result = si.install_bare_package("some-package", self.target_project, context, scope="project")
        self.assertTrue(result)
        mock_pip.assert_called_once_with("some-package", self.target_project, context, scope="project")


class TestSelectInstallScope(unittest.TestCase):
    def test_global_input(self):
        with patch("builtins.input", side_effect=["g"]):
            result = si.select_install_scope()
        self.assertEqual(result, "global")

    def test_global_uppercase(self):
        with patch("builtins.input", side_effect=["G"]):
            result = si.select_install_scope()
        self.assertEqual(result, "global")

    def test_project_input(self):
        with patch("builtins.input", side_effect=["p"]):
            result = si.select_install_scope()
        self.assertEqual(result, "project")

    def test_project_uppercase(self):
        with patch("builtins.input", side_effect=["P"]):
            result = si.select_install_scope()
        self.assertEqual(result, "project")

    def test_empty_input_defaults_to_project(self):
        with patch("builtins.input", side_effect=[""]):
            result = si.select_install_scope()
        self.assertEqual(result, "project")

    def test_invalid_then_project(self):
        with patch("builtins.input", side_effect=["x", "p"]):
            result = si.select_install_scope()
        self.assertEqual(result, "project")

    def test_invalid_then_global(self):
        with patch("builtins.input", side_effect=["?", "g"]):
            result = si.select_install_scope()
        self.assertEqual(result, "global")


class TestRunInstaller(unittest.TestCase):
    def test_git_strategy_routed(self):
        ctx = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }
        with patch.object(si, "install_git_clone", return_value=True) as mock_git:
            result = si.run_installer("https://github.com/owner/repo", "/fake/project", ctx, scope="project")
        self.assertTrue(result)
        mock_git.assert_called_once_with("https://github.com/owner/repo", "/fake/project", ctx, scope="project")

    def test_npm_strategy_routed(self):
        ctx = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }
        with patch.object(si, "install_npm_package", return_value=True) as mock_npm:
            result = si.run_installer("https://www.npmjs.com/package/lodash", "/fake/project", ctx, scope="project")
        self.assertTrue(result)
        mock_npm.assert_called_once_with("lodash", "/fake/project", ctx, scope="project")

    def test_pip_strategy_routed(self):
        ctx = {
            "has_package_json": False,
            "has_requirements_txt": False,
            "has_pyproject_toml": False,
            "has_kilo_config": False,
            "is_git_repo": False,
        }
        with patch.object(si, "install_pip_package", return_value=True) as mock_pip:
            result = si.run_installer("https://pypi.org/project/requests", "/fake/project", ctx, scope="project")
        self.assertTrue(result)
        mock_pip.assert_called_once_with("requests", "/fake/project", ctx, scope="project")

    def test_unknown_strategy_returns_false(self):
        ctx = {}
        result = si.run_installer("ftp://example.com/file.zip", "/fake/project", ctx, scope="project")
        self.assertFalse(result)


class TestSelectProject(unittest.TestCase):
    def test_no_projects(self):
        result = si.select_project([])
        self.assertIsNone(result)

    def test_single_project_accepted(self):
        with patch("builtins.input", return_value="y"):
            result = si.select_project(["/fake/project"])
        self.assertEqual(result, "/fake/project")

    def test_single_project_rejected(self):
        with patch("builtins.input", return_value="n"):
            result = si.select_project(["/fake/project"])
        self.assertIsNone(result)

    def test_multiple_projects_valid_choice(self):
        with patch("builtins.input", side_effect=["2"]):
            result = si.select_project(["/p1", "/p2"])
        self.assertEqual(result, "/p2")

    def test_multiple_projects_cancel(self):
        with patch("builtins.input", side_effect=["c"]):
            result = si.select_project(["/p1", "/p2"])
        self.assertIsNone(result)

    def test_multiple_projects_invalid_then_valid(self):
        with patch("builtins.input", side_effect=["0", "3", "1"]):
            result = si.select_project(["/p1", "/p2"])
        self.assertEqual(result, "/p1")


class TestPromptForUrl(unittest.TestCase):
    def test_valid_url(self):
        with patch("builtins.input", return_value="https://github.com/owner/repo"):
            result = si.prompt_for_url()
        self.assertEqual(result, "https://github.com/owner/repo")

    def test_empty_url(self):
        with patch("builtins.input", return_value=""):
            result = si.prompt_for_url()
        self.assertIsNone(result)

    def test_whitespace_only(self):
        with patch("builtins.input", return_value="   "):
            result = si.prompt_for_url()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
