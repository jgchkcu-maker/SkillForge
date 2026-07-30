#!/usr/bin/env python3
"""
Skill/Tool Auto-Installer for VS Code Projects
==============================================

Automates installation of technical skills or tools into active VS Code projects.

Features:
1. Detects active VS Code windows and their opened project folders
2. Prompts user for a skill/tool URL
3. Installs into the detected project context using appropriate package managers
   or git clone, depending on the URL type and project configuration.

Supported URL types:
- GitHub repositories (git clone into .kilo/skills/ or project root)
- npm packages (npm install --save-dev)
- pip packages (pip install)
- Generic git URLs (git clone)
"""

import os
import sys
import subprocess
import re
import json
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Color helpers (raw ANSI escape codes)
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_GRAY = "\033[90m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}"


def _dim(text: str) -> str:
    return _c(text, _DIM)


def _bold(text: str) -> str:
    return _c(text, _BOLD)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Where Kilo skills are typically installed inside a project
KILO_SKILLS_DIR = ".kilo/skills"

# Global Kilo skills directory (user-wide)
GLOBAL_SKILLS_DIR = Path.home() / ".kilo" / "skills"

# Mapping of recognizable URL patterns to installation strategies
URL_PATTERNS = [
    # GitHub repository: https://github.com/owner/repo or https://github.com/owner/repo.git
    (r"^https?://github\.com/([^/]+)/([^/]+?)/blob/.*", "git_clone"),
    (r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", "git_clone"),
    # Generic git HTTPS URL - captures the repo name before .git
    (r"^(?:git\+)?https?://(?:.*/)?([^/]+)\.git$", "git_clone"),
    # Generic git SSH URL - captures the repo name before .git
    (r"^git@[^/]+:[^/]+/([^/]+)\.git$", "git_clone"),
    # npm package: https://www.npmjs.com/package/package-name or npm:package-name
    (r"^https?://(www\.)?npmjs\.com/package/([^/]+)/?$", "npm_install"),
    (r"^npm:([^/]+)$", "npm_install"),
    # PyPI package: https://pypi.org/project/package-name or pip:package-name
    (r"^https?://pypi\.org/project/([^/]+)/?$", "pip_install"),
    (r"^pip:([^/]+)$", "pip_install"),
]

# ---------------------------------------------------------------------------
# 1. VS Code Active Project Detection
# ---------------------------------------------------------------------------

def get_vscode_projects_windows() -> List[str]:
    """
    Detects active VS Code projects on Windows by inspecting the command line
    of running Code.exe processes.

    VS Code on Windows launches as 'Code.exe' (or 'Code - Insiders.exe').
    Each window typically opens a folder, which appears in the process command
    line as a path argument. We use WMIC to query process command lines because
    the standard tasklist does not expose them.

    Returns:
        List of absolute paths to folders currently open in VS Code windows.
        Returns an empty list if VS Code is not running or no folders are found.
    """
    projects = []
    raw_candidates = []
    process_count = 0

    try:
        cmd = [
            "wmic",
            "process",
            "where",
            "name like '%Code.exe%' or name like '%Code - Insiders.exe%'",
            "get",
            "CommandLine",
            "/format:list",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.startswith("CommandLine="):
                continue
            process_count += 1
            cmdline = line[len("CommandLine="):]
            print(_dim(f"[DEBUG] Raw command line: {cmdline}"))
            candidates = _extract_paths_from_cmdline(cmdline)
            for path in candidates:
                normalized = os.path.abspath(path)
                if _is_vscode_install_path(normalized):
                    continue
                raw_candidates.append(normalized)
                if os.path.isdir(normalized) and normalized not in projects:
                    projects.append(normalized)

    except FileNotFoundError:
        print(_c("[WARN] wmic not found. Falling back to PowerShell process scan.", _YELLOW))
        projects = get_vscode_projects_powershell()
    except subprocess.TimeoutExpired:
        print(_c("[WARN] WMIC query timed out.", _YELLOW))
    except subprocess.CalledProcessError as e:
        print(_c(f"[WARN] WMIC query failed: {e.stderr or e.stdout}", _YELLOW))

    if process_count == 0:
        print(_c("[WARN] No VS Code processes were found by WMIC.", _YELLOW))
        print(_dim("        Ensure VS Code is running and check Task Manager for 'Code.exe' or 'Code - Insiders.exe'."))
    elif not projects and raw_candidates:
        print(_c(f"[WARN] Found {len(raw_candidates)} candidate path(s) from {process_count} VS Code process(es), "
              "but none resolved to existing directories.", _YELLOW))
        print(_dim("        This usually means VS Code was scanned before a folder was opened,"))
        print(_dim("        or the folder path is passed via --vscode-window-config / --folder-uri and was not decoded."))
    elif not projects and not raw_candidates:
        print(_c("[WARN] VS Code processes were found, but no path-like arguments were detected.", _YELLOW))
        print(_dim("        This can happen with new VS Code versions that communicate workspace data via IPC."))

    return projects


def get_vscode_projects_powershell() -> List[str]:
    """
    Fallback method using PowerShell to inspect VS Code process command lines.

    Uses Get-CimInstance (available on PowerShell 5.1+) to retrieve process
    command lines, then parses them for folder paths.
    """
    projects = []
    raw_candidates = []
    process_count = 0
    try:
        ps_cmd = (
            "Get-CimInstance Win32_Process "
            "-Filter \"Name like '%Code.exe%' or Name like '%Code - Insiders.exe%'\" "
            "| Select-Object -ExpandProperty CommandLine"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            process_count += 1
            print(_dim(f"[DEBUG] Raw command line: {line}"))
            candidates = _extract_paths_from_cmdline(line)
            for path in candidates:
                normalized = os.path.abspath(path)
                if _is_vscode_install_path(normalized):
                    continue
                raw_candidates.append(normalized)
                if os.path.isdir(normalized) and normalized not in projects:
                    projects.append(normalized)
    except Exception as e:
        print(_c(f"[WARN] PowerShell fallback failed: {e}", _YELLOW))

    if process_count == 0:
        print(_c("[WARN] No VS Code processes were found by PowerShell.", _YELLOW))
    elif not projects and raw_candidates:
        print(_c(f"[WARN] Found {len(raw_candidates)} candidate path(s) from {process_count} VS Code process(es), "
              "but none resolved to existing directories.", _YELLOW))
    elif not projects and not raw_candidates:
        print(_c("[WARN] VS Code processes were found, but no path-like arguments were detected.", _YELLOW))

    return projects


def get_vscode_projects_from_storage() -> List[str]:
    """
    Fallback: read recently opened folders from VS Code/Cursor/Windsurf storage.

    VS Code stores recently opened workspace folders in:
        %APPDATA%/Code/User/globalStorage/storage.json
        %APPDATA%/Code - Insiders/User/globalStorage/storage.json
        %USERPROFILE%/.vscode/data/user-data/globalStorage/storage.json
        %APPDATA%/Cursor/User/globalStorage/storage.json
        %APPDATA%/Cursor/User/globalStorage/state.vscdb
        %APPDATA%/Windsurf/User/globalStorage/storage.json
        %APPDATA%/Windsurf/User/globalStorage/state.vscdb
    """
    appdata = os.environ.get("APPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(appdata, "Code", "User", "globalStorage", "storage.json"),
        os.path.join(appdata, "Code - Insiders", "User", "globalStorage", "storage.json"),
        os.path.join(userprofile, ".vscode", "data", "user-data", "globalStorage", "storage.json"),
        os.path.join(appdata, "Cursor", "User", "globalStorage", "storage.json"),
        os.path.join(appdata, "Cursor", "User", "globalStorage", "state.vscdb"),
        os.path.join(appdata, "Windsurf", "User", "globalStorage", "storage.json"),
        os.path.join(appdata, "Windsurf", "User", "globalStorage", "state.vscdb"),
        # Newer VS Code versions sometimes store workspace state here
        os.path.join(localappdata, "Programs", "Microsoft VS Code", "Code.exe"),
    ]

    paths: List[str] = []
    for storage_path in candidates:
        if not os.path.exists(storage_path):
            continue
        try:
            if storage_path.endswith(".json"):
                with open(storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry in data.get("openedPathsList", {}).get("workspaces3", []):
                    if isinstance(entry, dict):
                        p = entry.get("workspace", {}).get("configPath") or entry.get("path")
                    else:
                        p = entry
                    if p and os.path.isdir(p):
                        paths.append(p)
                for entry in data.get("openedPathsList", {}).get("folders2", []):
                    p = entry if isinstance(entry, str) else entry.get("path")
                    if p and os.path.isdir(p):
                        paths.append(p)
            elif storage_path.endswith(".vscdb"):
                try:
                    import sqlite3
                    conn = sqlite3.connect(storage_path)
                    cur = conn.cursor()
                    cur.execute("SELECT value FROM ItemTable WHERE key = 'history.entries'")
                    row = cur.fetchone()
                    if row:
                        raw = row[0]
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="ignore")
                        data = json.loads(raw)
                        for entry in data:
                            folder = entry.get("folder")
                            if folder and os.path.isdir(folder):
                                paths.append(folder)
                except Exception:
                    pass
        except Exception as e:
            print(_c(f"[WARN] Could not read {storage_path}: {e}", _YELLOW))

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _extract_paths_from_cmdline(cmdline: str) -> List[str]:
    """
    Extracts filesystem paths from a process command line string.

    Handles:
    - Quoted paths with spaces
    - Flag-value pairs (e.g., --flag value)
    - Known VS Code executable paths and installation folders
    - URI-encoded paths (e.g., --folder-uri file:///c%3A/Users/...)
    """
    paths = []

    # First, extract quoted strings (VS Code typically quotes folder paths with spaces)
    quoted = re.findall(r'"([^"]+)"', cmdline)
    for q in quoted:
        if _looks_like_project_path(q):
            paths.append(q)

    # Then process unquoted tokens with flag-value awareness
    tokens = re.split(r"\s+", cmdline)
    skip_next = False
    for i, token in enumerate(tokens):
        if not token:
            continue
        if skip_next:
            skip_next = False
            continue

        # Handle URI-encoded paths (e.g., --folder-uri file:///c%3A/Users/...)
        if token.startswith("file:///"):
            decoded = token[8:].replace("/", "\\")
            decoded = re.sub(r"^([a-zA-Z]):", r"\1:", decoded)  # Fix drive letter
            if _looks_like_project_path(decoded):
                paths.append(decoded)
                continue

        # Skip known flags and their associated values
        if token.startswith("-") or token.startswith("/"):
            # Look ahead: if the next token is a plain value (not another flag),
            # skip it as well to avoid treating flag arguments as paths.
            if i + 1 < len(tokens):
                next_tok = tokens[i + 1]
                if next_tok and not next_tok.startswith("-") and not next_tok.startswith("/"):
                    skip_next = True
            continue

        # Skip the VS Code executable itself or its fragments
        if re.match(r"^(?:code(?:-insiders)?|Code(?:-Insiders)?)(?:\.exe)?$", token):
            continue

        # Skip known installation/system directories that can leak through
        # when an unquoted executable path is split on spaces.
        if any(token.startswith(p) for p in ("C:\\Program", "C:\\Windows", "C:\\$")):
            continue

        if _looks_like_project_path(token):
            paths.append(token)

    return paths


def _looks_like_project_path(s: str) -> bool:
    """
    Heuristic check: does the string look like a project directory path?

    Requires an absolute Windows path (drive letter or UNC) so that
    unquoted fragments from split executable paths are not treated as paths.
    """
    if not s:
        return False
    # Must start with a drive letter (Windows) or be a UNC path
    if re.match(r"^[A-Za-z]:\\", s) or s.startswith("\\\\"):
        return True
    return False


def _is_vscode_install_path(path: str) -> bool:
    """Exclude VS Code's own folders accidentally exposed in process arguments."""
    normalized = os.path.normcase(os.path.normpath(path))
    markers = (
        os.path.normcase(os.path.normpath(os.path.join("AppData", "Roaming", "Code"))),
    )
    is_code_app = "microsoft vs code" in normalized and normalized.endswith(os.path.normcase("resources\\app"))
    is_insiders_app = "code - insiders" in normalized and normalized.endswith(os.path.normcase("resources\\app"))
    return any(marker in normalized for marker in markers) or is_code_app or is_insiders_app


# ---------------------------------------------------------------------------
# 2. URL Parsing & Strategy Selection
# ---------------------------------------------------------------------------

def parse_url(url: str) -> Tuple[str, Optional[str]]:
    """
    Determines the installation strategy for a given URL.

    Args:
        url: User-provided URL or package identifier

    Returns:
        Tuple of (strategy, identifier)
        - strategy: 'git_clone', 'npm_install', 'pip_install', or 'unknown'
        - identifier: extracted package/repo name/path, or None
    """
    url = url.strip()

    for pattern, strategy in URL_PATTERNS:
        match = re.match(pattern, url, re.IGNORECASE)
        if match:
            identifier = match.group(match.lastindex)
            return strategy, identifier

    # If no pattern matched, check if it looks like a bare package name
    if re.match(r"^[a-zA-Z0-9_-]+$", url):
        return "bare_package", url

    return "unknown", url


def normalize_github_url(url: str) -> str:
    """Best-effort convert a GitHub blob/tree/raw URL into a repo clone URL."""
    if not isinstance(url, str):
        return url
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)/(?:blob|tree)/.*$", url, re.IGNORECASE)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}.git"
    return url


# ---------------------------------------------------------------------------
# 3. Project Context Detection
# ---------------------------------------------------------------------------

def detect_project_context(project_path: str) -> dict:
    """
    Inspects the project folder to determine which package managers and
    configuration files are present. This influences how bare package names
    are installed and where skills are placed.

    Args:
        project_path: Absolute path to the project folder

    Returns:
        Dictionary with boolean flags like:
        {
            'has_package_json': bool,
            'has_requirements_txt': bool,
            'has_pyproject_toml': bool,
            'has_kilo_config': bool,
            'is_git_repo': bool,
        }
    """
    context = {
        "has_package_json": os.path.isfile(os.path.join(project_path, "package.json")),
        "has_requirements_txt": os.path.isfile(os.path.join(project_path, "requirements.txt")),
        "has_pyproject_toml": os.path.isfile(os.path.join(project_path, "pyproject.toml")),
        "has_kilo_config": os.path.isfile(os.path.join(project_path, "kilo.json"))
                            or os.path.isdir(os.path.join(project_path, ".kilo")),
        "is_git_repo": os.path.isdir(os.path.join(project_path, ".git")),
    }
    return context


# ---------------------------------------------------------------------------
# 4. Installation Logic
# ---------------------------------------------------------------------------

def _stream_process(stdout, stderr, log_callback=None):
    """Stream process output line by line."""
    seen = set()
    while True:
        line = stdout.readline()
        if line:
            msg = line.rstrip("\n").rstrip("\r")
            if msg and msg not in seen:
                seen.add(msg)
                print(msg)
                if log_callback:
                    log_callback(msg, "info")
        err = stderr.readline()
        if err:
            msg = err.rstrip("\n").rstrip("\r")
            if msg and msg not in seen:
                seen.add(msg)
                print(_c(msg, _YELLOW))
                if log_callback:
                    log_callback(msg, "warn")
        if not line and not err:
            break


def install_git_clone(
    repo_url: str,
    target_project: str,
    context: dict,
    scope: str = "project",
    log_callback=None,
    force: bool = False,
) -> bool:
    """
    Clones a git repository into the target project.

    If the project is a Kilo project (has .kilo/config), the repo is cloned
    into .kilo/skills/<repo-name> by default. Otherwise, it clones into
    <target_project>/<repo-name>.

    When scope is 'global', the repo is cloned into ~/.kilo/skills/<repo-name>
    regardless of project configuration.

    Args:
        repo_url: Git clone URL
        target_project: Path to the project folder
        context: Project context dict from detect_project_context()
        scope: 'project' or 'global'
        log_callback: optional callable(message, level) for live log streaming
        force: if True, delete destination before cloning

    Returns:
        True if installation succeeded, False otherwise
    """
    # Extract repo name from URL (identifier from parse_url is already the repo name)
    repo_name = repo_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    if scope == "global":
        global_dir = str(GLOBAL_SKILLS_DIR)
        GLOBAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        dest = os.path.join(global_dir, repo_name)
    elif context.get("has_kilo_config"):
        dest = os.path.join(target_project, KILO_SKILLS_DIR, repo_name)
    else:
        dest = os.path.join(target_project, repo_name)

    if os.path.exists(dest):
        if not force:
            msg = f"[ERROR] Destination already exists: {dest}"
            print(_c(msg, _RED))
            if log_callback:
                log_callback(msg, "error")
            return False
        msg = f"[INFO] Force mode: removing existing destination {dest}"
        print(_c(msg, _BLUE))
        if log_callback:
            log_callback(msg, "warn")
        try:
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            else:
                os.remove(dest)
        except Exception as e:  # noqa: BLE001
            msg = f"[ERROR] Failed to remove existing destination: {e}"
            print(_c(msg, _RED))
            if log_callback:
                log_callback(msg, "error")
            return False

    scope_label = "global" if scope == "global" else "project"
    msg = f"[INFO] Cloning {repo_url} into {dest} ({scope_label}) ..."
    print(_c(msg, _BLUE))
    if log_callback:
        log_callback(msg, "info")
    try:
        proc = subprocess.Popen(
            ["git", "clone", repo_url, dest],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
        _stream_process(proc.stdout, proc.stdout, log_callback)
        proc.wait()
        if proc.returncode == 0:
            msg = f"[OK] Successfully cloned to {dest}"
            print(_c(msg, _GREEN))
            if log_callback:
                log_callback(msg, "success")
            return True
        raise subprocess.CalledProcessError(proc.returncode, proc.args)
    except FileNotFoundError:
        msg = "[ERROR] git is not installed or not in PATH."
        print(_c(msg, _RED))
        if log_callback:
            log_callback(msg, "error")
    except subprocess.CalledProcessError as e:
        msg = f"[ERROR] git clone failed: {e}"
        print(_c(msg, _RED))
        if log_callback:
            log_callback(msg, "error")
    return False


def install_npm_package(
    package_name: str,
    target_project: str,
    context: dict,
    scope: str = "project",
    log_callback=None,
) -> bool:
    """
    Installs an npm package into the target project.

    Requires package.json to exist in the project. Installs as a devDependency
    by default for tooling/skills.

    When scope is 'global', runs `npm install -g` instead of `npm install --save-dev`.

    Args:
        package_name: npm package name (without version specifier)
        target_project: Path to the project folder
        context: Project context dict
        scope: 'project' or 'global'

    Returns:
        True if installation succeeded, False otherwise
    """
    if scope == "global":
        msg = f"[INFO] Installing npm package '{package_name}' globally ..."
        print(_c(msg, _BLUE))
        if log_callback:
            log_callback(msg, "info")
        try:
            proc = subprocess.Popen(
                ["npm", "install", "-g", package_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            _stream_process(proc.stdout, proc.stdout, log_callback)
            proc.wait()
            if proc.returncode == 0:
                msg = f"[OK] Successfully installed {package_name} globally"
                print(_c(msg, _GREEN))
                if log_callback:
                    log_callback(msg, "success")
                return True
            raise subprocess.CalledProcessError(proc.returncode, proc.args)
        except FileNotFoundError:
            msg = "[ERROR] npm is not installed or not in PATH."
            print(_c(msg, _RED))
            if log_callback:
                log_callback(msg, "error")
        except subprocess.CalledProcessError as e:
            msg = f"[ERROR] npm install -g failed: {e}"
            print(_c(msg, _RED))
            if log_callback:
                log_callback(msg, "error")
        return False

    if not context.get("has_package_json"):
        print(_c("[ERROR] No package.json found in the project. Cannot run npm install.", _RED))
        print(_dim("        Hint: Navigate to a Node.js project or create package.json first."))
        return False

    msg = f"[INFO] Installing npm package '{package_name}' as devDependency ..."
    print(_c(msg, _BLUE))
    if log_callback:
        log_callback(msg, "info")
    try:
        proc = subprocess.Popen(
            ["npm", "install", "--save-dev", package_name],
            cwd=target_project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
        _stream_process(proc.stdout, proc.stdout, log_callback)
        proc.wait()
        if proc.returncode == 0:
            msg = f"[OK] Successfully installed {package_name}"
            print(_c(msg, _GREEN))
            if log_callback:
                log_callback(msg, "success")
            return True
        raise subprocess.CalledProcessError(proc.returncode, proc.args)
    except FileNotFoundError:
        msg = "[ERROR] npm is not installed or not in PATH."
        print(_c(msg, _RED))
        if log_callback:
            log_callback(msg, "error")
    except subprocess.CalledProcessError as e:
        msg = f"[ERROR] npm install failed: {e}"
        print(_c(msg, _RED))
        if log_callback:
            log_callback(msg, "error")
    return False


def install_pip_package(
    package_name: str,
    target_project: str,
    context: dict,
    scope: str = "project",
    log_callback=None,
) -> bool:
    """
    Installs a pip package into the active Python environment.

    Optionally adds the package to requirements.txt if it exists, or creates
    one if the project appears to be Python-based.

    When scope is 'global', skips requirements.txt update.

    Args:
        package_name: pip package name
        target_project: Path to the project folder
        context: Project context dict
        scope: 'project' or 'global'

    Returns:
        True if installation succeeded, False otherwise
    """
    msg = f"[INFO] Installing pip package '{package_name}' ..."
    print(_c(msg, _BLUE))
    if log_callback:
        log_callback(msg, "info")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
        _stream_process(proc.stdout, proc.stdout, log_callback)
        proc.wait()
        if proc.returncode == 0:
            msg = f"[OK] Successfully installed {package_name}"
            print(_c(msg, _GREEN))
            if log_callback:
                log_callback(msg, "success")
            if scope == "project":
                _update_requirements_txt(target_project, package_name, context)
            return True
        raise subprocess.CalledProcessError(proc.returncode, proc.args)
    except FileNotFoundError:
        msg = "[ERROR] pip is not installed or not in PATH."
        print(_c(msg, _RED))
        if log_callback:
            log_callback(msg, "error")
    except subprocess.CalledProcessError as e:
        msg = f"[ERROR] pip install failed: {e}"
        print(_c(msg, _RED))
        if log_callback:
            log_callback(msg, "error")
    return False


def _update_requirements_txt(
    project_path: str,
    package_name: str,
    context: dict,
) -> None:
    """
    Appends the installed package to requirements.txt if the project is Python-based.
    Creates requirements.txt if it does not exist but the project has Python files.
    """
    req_file = os.path.join(project_path, "requirements.txt")
    has_python_files = any(
        f.endswith(".py")
        for f in os.listdir(project_path)
        if os.path.isfile(os.path.join(project_path, f))
    )

    if not has_python_files and not context.get("has_requirements_txt"):
        return

    # Extract base package name (ignore version specifiers if any)
    base_name = re.split(r"[=<>!~]", package_name)[0].strip()

    # Check if already present
    if os.path.exists(req_file):
        with open(req_file, "r", encoding="utf-8") as f:
            existing = f.read()
        if base_name.lower() in existing.lower():
            return  # Already recorded

    with open(req_file, "a", encoding="utf-8") as f:
        f.write(f"\n{base_name}\n")
    print(_c(f"[INFO] Added '{base_name}' to requirements.txt", _BLUE))


def install_bare_package(
    package_name: str,
    target_project: str,
    context: dict,
    scope: str = "project",
    log_callback=None,
) -> bool:
    """
    Installs a bare package name by inferring the package manager from
    the project context.

    - If package.json exists -> npm install --save-dev
    - If requirements.txt or pyproject.toml exists -> pip install
    - Otherwise, prompt the user or default to pip
    """
    if context.get("has_package_json"):
        return install_npm_package(package_name, target_project, context, scope=scope, log_callback=log_callback)
    elif context.get("has_requirements_txt") or context.get("has_pyproject_toml"):
        return install_pip_package(package_name, target_project, context, scope=scope, log_callback=log_callback)
    else:
        print(_c(f"[INFO] Cannot auto-detect package manager for '{package_name}'.", _BLUE))
        if log_callback:
            log_callback(f"Cannot auto-detect package manager for '{package_name}'.", "info")
        choice = input(_bold("Install with (n)pm or (p)ip? [n/p]: ")).strip().lower()
        if choice == "p":
            return install_pip_package(package_name, target_project, context, scope=scope, log_callback=log_callback)
        else:
            return install_npm_package(package_name, target_project, context, scope=scope, log_callback=log_callback)


# ---------------------------------------------------------------------------
# 5. User Interaction & Orchestration
# ---------------------------------------------------------------------------

def select_project(projects: List[str]) -> Optional[str]:
    """
    Prompts the user to select one of the detected VS Code projects.

    Args:
        projects: List of detected project folder paths

    Returns:
        Selected project path, or None if the user cancels
    """
    if not projects:
        print(_c("[INFO] No active VS Code projects detected.", _BLUE))
        return None

    print("\nDetected active VS Code projects:")
    for idx, path in enumerate(projects, start=1):
        print(f"  {idx}. {path}")

    if len(projects) == 1:
        choice = input(_bold("Install into this project? [Y/n]: ")).strip().lower()
        if choice in ("", "y", "yes"):
            return projects[0]
        return None

    while True:
        try:
            choice = input(_bold(f"Select project [1-{len(projects)}] or 'c' to cancel: ")).strip()
            if choice.lower() in ("c", "cancel", "q", "quit"):
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(projects):
                return projects[idx]
            print(_c(f"Please enter a number between 1 and {len(projects)}.", _YELLOW))
        except ValueError:
            print(_c("Invalid input. Please enter a number or 'c' to cancel.", _YELLOW))


def select_install_scope() -> str:
    """
    Prompts the user to choose between global and project scope.

    Returns:
        'global' or 'project' (defaults to 'project' on empty input)
    """
    print(_bold("\nSelect installation scope:"))
    print(f"  {_c('[G]', _GREEN)} Global  — install to {_c(str(GLOBAL_SKILLS_DIR), _CYAN)}")
    print(f"  {_c('[P]', _GREEN)} Project — install into the active VS Code project")
    while True:
        choice = input(_bold("? Scope [P]: ")).strip().lower()
        if choice in ("g", "global"):
            return "global"
        if choice in ("", "p", "project"):
            return "project"
        print(_c("Invalid choice. Please enter G or P.", _YELLOW))


def prompt_for_url() -> Optional[str]:
    """
    Prompts the user to input a skill/tool URL.

    Returns:
        The URL string, or None if the user cancels
    """
    url = input(_bold("\nEnter skill/tool URL to install: ")).strip()
    if not url:
        print(_c("[INFO] No URL provided. Exiting.", _BLUE))
        return None
    return url


def prompt_for_project_path() -> Optional[str]:
    """
    Prompts the user to enter a project path manually.

    Returns:
        The project path, or None if the user cancels
    """
    while True:
        path = input(_bold("\nEnter the project folder path manually: ")).strip()
        if not path:
            return None
        normalized = os.path.abspath(path)
        if os.path.isdir(normalized):
            return normalized
        print(_c("[ERROR] The specified path does not exist or is not a directory.", _RED))


def run_installer(
    url: str,
    target_project: str,
    context: dict,
    scope: str = "project",
    log_callback=None,
    force: bool = False,
) -> bool:
    """
    Routes the installation request to the appropriate handler based on
    URL strategy.

    Args:
        url: The raw URL/package identifier
        target_project: Path to install into
        context: Project context dict
        scope: 'project' or 'global'
        log_callback: optional callable(message, level) for live log streaming
        force: if True, overwrite existing destination when supported

    Returns:
        True if installation succeeded, False otherwise
    """
    raw_url = url
    url = normalize_github_url(url)
    if url != raw_url and log_callback:
        log_callback(f"Normalized URL -> {url}", "debug")

    strategy, identifier = parse_url(url)

    print(_dim(f"[DEBUG] Parsed URL strategy: {strategy}, identifier: {identifier}"))
    if log_callback:
        log_callback(f"Parsed URL strategy: {strategy}", "debug")

    if strategy == "git_clone":
        # Pass the original URL (not just the identifier) for git clone
        return install_git_clone(url, target_project, context, scope=scope, log_callback=log_callback, force=force)
    elif strategy == "npm_install":
        return install_npm_package(identifier, target_project, context, scope=scope, log_callback=log_callback)
    elif strategy == "pip_install":
        return install_pip_package(identifier, target_project, context, scope=scope, log_callback=log_callback)
    elif strategy == "bare_package":
        return install_bare_package(identifier, target_project, context, scope=scope, log_callback=log_callback)
    else:
        print(_c(f"[ERROR] Unsupported URL type: {url}", _RED))
        if log_callback:
            log_callback(f"Unsupported URL type: {url}", "error")
        print("        Supported formats:")
        print("          - GitHub repo: https://github.com/owner/repo")
        print("          - npm package: https://www.npmjs.com/package/name")
        print("          - pip package: https://pypi.org/project/name")
        print("          - Generic git: https://... .git")
        return False


def main() -> None:
    """
    Main entry point for the skill/tool installer.

    Workflow:
    1. Enable ANSI colors on Windows
    2. Prompt for install scope (global or project)
    3. If global: install to ~/.kilo/skills/
    4. If project: scan for active VS Code projects, let user select, install
    5. Prompt for skill/tool URL
    6. Detect project context (package managers, configs)
    7. Execute installation based on URL type and project context
    """
    # Enable VT100 ANSI processing on Windows consoles (Windows 10+)
    os.system("")

    header = "Skill/Tool Auto-Installer for VS Code Projects"
    print(_c("=" * 60, _CYAN))
    print(_c(f"  {_bold(header)}", _CYAN))
    print(_c("=" * 60, _CYAN))

    scope = select_install_scope()
    scope_color = _GREEN if scope == "global" else _BLUE
    print(_c(f"\nScope: {scope.upper()}", scope_color))

    if scope == "global":
        global_dir = str(GLOBAL_SKILLS_DIR)
        GLOBAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        print(_c(f"[OK] Global skills directory: {global_dir}", _GREEN))
        target = global_dir
        context = detect_project_context(target)
        print(_dim(f"[DEBUG] Global context: {context}"))
        url = prompt_for_url()
        if not url:
            sys.exit(0)
        success = run_installer(url, target, context, scope=scope)
        if success:
            print(_c("\n[SUCCESS] Installation complete!", _GREEN))
        else:
            print(_c("\n[FAILED] Installation did not complete successfully.", _RED))
            sys.exit(1)
        return

    print("\n[SCAN] Looking for active VS Code projects ...")
    projects = get_vscode_projects_windows()

    if not projects:
        print(_c("[INFO] Process scan did not find any active project folders.", _BLUE))
        storage_projects = get_vscode_projects_from_storage()
        if storage_projects:
            print(_c(f"[OK] Found {len(storage_projects)} recently opened folder(s) from VS Code storage.", _GREEN))
            projects = storage_projects
        else:
            print(_c("[INFO] No recent folders found in VS Code storage either.", _BLUE))
            cwd = os.getcwd()
            cwd_context = detect_project_context(cwd)
            if any(cwd_context.values()):
                print(_c(f"[AUTO] Using current working directory as project: {cwd}", _CYAN))
                projects = [cwd]
            else:
                print(_c("[INFO] Current directory does not look like a project.", _BLUE))
                manual = input(_bold("Enter the project folder path manually? [Y/n]: ")).strip().lower()
                if manual in ("", "y", "yes"):
                    manual_path = prompt_for_project_path()
                    if manual_path:
                        projects = [manual_path]
                    else:
                        print(_c("[INFO] Installation cancelled.", _BLUE))
                        sys.exit(0)
                else:
                    print(_c("[INFO] Installation cancelled.", _BLUE))
                    sys.exit(0)

    print(_c(f"[OK] Found {len(projects)} active project(s).", _GREEN))

    target = select_project(projects)
    if not target:
        print(_c("[INFO] Installation cancelled.", _BLUE))
        sys.exit(0)

    print(_c(f"[OK] Target project: {target}", _GREEN))

    context = detect_project_context(target)
    print(_dim(f"[DEBUG] Project context: {context}"))

    url = prompt_for_url()
    if not url:
        sys.exit(0)

    success = run_installer(url, target, context, scope=scope)

    if success:
        print(_c("\n[SUCCESS] Installation complete!", _GREEN))
    else:
        print(_c("\n[FAILED] Installation did not complete successfully.", _RED))
        sys.exit(1)


if __name__ == "__main__":
    main()
