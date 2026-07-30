"""Safe artifact preparation and installation helpers.

Skills are copied as complete directories. Agents and MCP are only handled by
explicit adapters; unsupported targets return a result instead of guessing a
configuration format.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

import skill_installer as legacy
from agent_registry import AGENTS_BY_ID, AgentDefinition


LogCallback = Callable[[str, str], None]


def _log(callback: Optional[LogCallback], message: str, level: str = "info") -> None:
    if callback:
        callback(message, level)


def _skill_roots(source: Path) -> List[Path]:
    """Return every skill directory in a source, excluding Git metadata."""
    candidates = []
    for manifest in source.rglob("SKILL.md"):
        if ".git" not in manifest.parts:
            candidates.append(manifest.parent)
    return sorted(candidates, key=lambda item: str(item).lower())


def _split_skill_selector(source: str) -> tuple[str, Optional[str]]:
    """Allow selecting a skill inside a multi-skill repository with #skill=NAME."""
    cleaned = source.strip()
    local_source, marker, fragment = cleaned.partition("#")
    if marker and fragment.startswith("skill="):
        return local_source, unquote(fragment[len("skill="):]).strip() or None
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https", "git"}:
        return cleaned, None
    selector = parse_qs(parsed.fragment).get("skill", [None])[0]
    clone_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    return clone_url, unquote(selector).strip() if selector else None


def _select_skill_root(candidates: List[Path], selector: Optional[str], default_name: Optional[str]) -> Path:
    if not candidates:
        raise ValueError("Source does not contain a SKILL.md file")
    if selector:
        selected = [item for item in candidates if item.name == selector]
        if len(selected) == 1:
            return selected[0]
        available = ", ".join(item.name for item in candidates)
        raise ValueError(f"Skill '{selector}' was not found. Available skills: {available}")
    if len(candidates) == 1:
        return candidates[0]
    default = [item for item in candidates if item.name == default_name]
    if len(default) == 1:
        return default[0]
    available = ", ".join(item.name for item in candidates)
    raise ValueError(
        "Source contains multiple skills. Select one with a URL fragment, for example "
        f"#skill=NAME. Available skills: {available}"
    )


def _repository_name(url: str) -> Optional[str]:
    path = urlsplit(url).path.rstrip("/")
    name = Path(path).name
    return name[:-4] if name.endswith(".git") else name or None


def _clone_source(source: str, destination: Path, log_callback: Optional[LogCallback]) -> None:
    _log(log_callback, f"Cloning skill source: {source}")
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", source, str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return
    detail = (proc.stderr or proc.stdout or "git clone failed").strip()
    _log(log_callback, f"git clone failed (exit {proc.returncode}): {detail}", "error")
    raise RuntimeError(f"git clone failed (exit {proc.returncode}): {detail}")


def _materialize_source(source: str):
    local = Path(os.path.expandvars(os.path.expanduser(source))).resolve()
    if local.is_dir():
        yield local, None
        return

    clone_source, _ = _split_skill_selector(source)
    normalized = legacy.normalize_github_url(clone_source)
    strategy, _ = legacy.parse_url(normalized)
    if strategy != "git_clone":
        raise ValueError("A Skill source must be a local directory or a Git repository URL")

    with tempfile.TemporaryDirectory(prefix="skillforge-") as temp_dir:
        destination = Path(temp_dir) / "source"
        _clone_source(normalized, destination, None)
        yield destination, None


def _copy_directory(source: Path, destination: Path, force: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not force:
            raise FileExistsError(f"Destination already exists: {destination}")
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git"))


def _normalize_skill_manifest(destination: Path) -> None:
    """Store SKILL.md as UTF-8 without BOM and with Unix line endings.

    Git on Windows may check out text files with CRLF. Some skill validators
    use LF-only frontmatter expressions, so normalize the manifest after the
    directory copy while leaving all other skill files byte-for-byte intact.
    """
    manifest = destination / "SKILL.md"
    raw = manifest.read_bytes()
    content = raw.decode("utf-8-sig")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    manifest.write_text(normalized, encoding="utf-8", newline="\n")


def install_skill(
    source: str,
    agent_ids: Iterable[str],
    scope: str,
    project: str,
    force: bool = False,
    log_callback: Optional[LogCallback] = None,
) -> List[dict]:
    results: List[dict] = []
    selected = [AGENTS_BY_ID[agent_id] for agent_id in agent_ids if agent_id in AGENTS_BY_ID]
    with tempfile.TemporaryDirectory(prefix="skillforge-work-") as workspace:
        prepared_root: Optional[Path] = None
        try:
            clone_source, selector = _split_skill_selector(source)
            local = Path(os.path.expandvars(os.path.expanduser(clone_source))).resolve()
            default_name: Optional[str] = None
            if local.is_dir():
                prepared_root = local
            else:
                normalized = legacy.normalize_github_url(clone_source)
                strategy, _ = legacy.parse_url(normalized)
                if strategy != "git_clone":
                    raise ValueError("Skill source must be a local directory or Git repository URL")
                destination = Path(workspace) / "source"
                _clone_source(normalized, destination, log_callback)
                prepared_root = destination
                default_name = _repository_name(normalized)

            skill_root = _select_skill_root(_skill_roots(prepared_root), selector, default_name)
            skill_name = skill_root.name

            for agent in selected:
                capability = agent.supported_artifacts.get("skill", "unsupported")
                destination = agent.project_destination("skill", project) if scope == "project" else agent.global_destination("skill")
                if capability != "ready" or not destination:
                    results.append({"agent_id": agent.id, "status": "unsupported", "destination": str(destination or ""), "message": "Skill installation is not available for this target"})
                    continue
                target = destination / skill_name
                try:
                    _copy_directory(skill_root, target, force)
                    _normalize_skill_manifest(target)
                    _log(log_callback, f"Installed {skill_name} for {agent.name}: {target}", "success")
                    results.append({"agent_id": agent.id, "status": "installed", "destination": str(target), "message": "Installed successfully"})
                except Exception as exc:  # noqa: BLE001
                    _log(log_callback, f"{agent.name}: {exc}", "error")
                    results.append({"agent_id": agent.id, "status": "failed", "destination": str(target), "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            _log(log_callback, f"Installation failed: {exc}", "error")
            for agent in selected:
                results.append({"agent_id": agent.id, "status": "failed", "destination": "", "message": str(exc)})
    return results


def preview_mcp(agent_ids: Iterable[str], scope: str, project: str, options: dict) -> dict:
    name = str(options.get("name") or "").strip()
    command = str(options.get("command") or "").strip()
    transport = str(options.get("transport") or "stdio").strip().lower()
    if not name or not command:
        raise ValueError("MCP options require name and command")
    results = []
    for agent_id in agent_ids:
        agent = AGENTS_BY_ID.get(agent_id)
        if not agent:
            continue
        destination = agent.project_destination("mcp", project) if scope == "project" else agent.global_destination("mcp")
        supported = agent.supported_artifacts.get("mcp", "unsupported") == "ready" and destination is not None
        results.append({
            "agent_id": agent.id,
            "status": "ready" if supported else agent.supported_artifacts.get("mcp", "unsupported"),
            "destination": str(destination or ""),
            "message": "Will merge MCP configuration" if supported else "MCP adapter is not available for this target",
        })
    return {
        "requires_confirmation": True,
        "commands_to_run": [command],
        "files_to_modify": sorted({item["destination"] for item in results if item["destination"]}),
        "external_connections": options.get("external_connections", []),
        "transport": transport,
        "results": results,
    }


def install_mcp(agent_ids: Iterable[str], scope: str, project: str, options: dict, log_callback: Optional[LogCallback] = None) -> List[dict]:
    preview = preview_mcp(agent_ids, scope, project, options)
    name = str(options["name"]).strip()
    spec = {
        "command": str(options["command"]).strip(),
        "args": options.get("args", []),
        "env": options.get("env", {}),
    }
    results = []
    for item in preview["results"]:
        if item["status"] != "ready":
            results.append(item)
            continue
        destination = Path(item["destination"])
        agent = AGENTS_BY_ID[item["agent_id"]]
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if destination.exists():
                data = json.loads(destination.read_text(encoding="utf-8"))
            key = "mcp" if agent.id == "kilo" else "mcpServers"
            data.setdefault(key, {})[name] = spec
            destination.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _log(log_callback, f"Configured MCP {name} for {agent.name}: {destination}", "success")
            results.append({**item, "status": "installed", "message": "MCP configured successfully"})
        except Exception as exc:  # noqa: BLE001
            _log(log_callback, f"{agent.name}: {exc}", "error")
            results.append({**item, "status": "failed", "message": str(exc)})
    return results


def install_agent(agent_ids: Iterable[str], scope: str, project: str, source: str, force: bool = False) -> List[dict]:
    """Install only explicitly supported Kilo agent files for now."""
    source_path = Path(os.path.expandvars(os.path.expanduser(source))).resolve()
    if not source_path.is_file():
        raise ValueError("Agent source must be a local Markdown or JSON file")
    if source_path.suffix.lower() not in {".md", ".json", ".yaml", ".yml"}:
        raise ValueError("Unsupported Agent file format")
    results = []
    for agent_id in agent_ids:
        agent = AGENTS_BY_ID.get(agent_id)
        destination_root = agent.project_destination("agent", project) if agent and scope == "project" else (agent.global_destination("agent") if agent else None)
        if not agent or agent.supported_artifacts.get("agent") != "ready" or not destination_root:
            results.append({"agent_id": agent_id, "status": "unsupported", "destination": "", "message": "Agent adapter is not available"})
            continue
        destination = destination_root / source_path.name
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and not force:
                raise FileExistsError(f"Destination already exists: {destination}")
            shutil.copy2(source_path, destination)
            results.append({"agent_id": agent.id, "status": "installed", "destination": str(destination), "message": "Agent installed successfully"})
        except Exception as exc:  # noqa: BLE001
            results.append({"agent_id": agent.id, "status": "failed", "destination": str(destination), "message": str(exc)})
    return results
