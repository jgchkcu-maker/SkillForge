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

import skill_installer as legacy
from agent_registry import AGENTS_BY_ID, AgentDefinition


LogCallback = Callable[[str, str], None]


def _log(callback: Optional[LogCallback], message: str, level: str = "info") -> None:
    if callback:
        callback(message, level)


def _skill_root(source: Path) -> Optional[Path]:
    if (source / "SKILL.md").is_file():
        return source
    candidates = [child for child in source.iterdir() if child.is_dir() and (child / "SKILL.md").is_file()]
    return candidates[0] if len(candidates) == 1 else None


def _materialize_source(source: str):
    local = Path(os.path.expandvars(os.path.expanduser(source))).resolve()
    if local.is_dir():
        yield local, None
        return

    normalized = legacy.normalize_github_url(source.strip())
    strategy, _ = legacy.parse_url(normalized)
    if strategy != "git_clone":
        raise ValueError("A Skill source must be a local directory or a Git repository URL")

    with tempfile.TemporaryDirectory(prefix="skillforge-") as temp_dir:
        destination = Path(temp_dir) / "source"
        _log(None, f"Cloning source into {destination}")
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", normalized, str(destination)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "git clone failed").strip())
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
            local = Path(os.path.expandvars(os.path.expanduser(source))).resolve()
            if local.is_dir():
                prepared_root = local
            else:
                normalized = legacy.normalize_github_url(source.strip())
                strategy, _ = legacy.parse_url(normalized)
                if strategy != "git_clone":
                    raise ValueError("Skill source must be a local directory or Git repository URL")
                destination = Path(workspace) / "source"
                _log(log_callback, f"Cloning skill source: {normalized}")
                proc = subprocess.run(["git", "clone", "--depth", "1", normalized, str(destination)], capture_output=True, text=True, check=False)
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or proc.stdout or "git clone failed").strip())
                prepared_root = destination

            skill_root = _skill_root(prepared_root)
            if not skill_root:
                raise ValueError("Source does not contain exactly one discoverable SKILL.md")
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
                    _log(log_callback, f"Installed {skill_name} for {agent.name}: {target}", "success")
                    results.append({"agent_id": agent.id, "status": "installed", "destination": str(target), "message": "Installed successfully"})
                except Exception as exc:  # noqa: BLE001
                    _log(log_callback, f"{agent.name}: {exc}", "error")
                    results.append({"agent_id": agent.id, "status": "failed", "destination": str(target), "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
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
