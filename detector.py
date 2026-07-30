"""Lightweight, on-demand detection of installed AI agents on Windows."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from agent_registry import AGENTS, AgentDefinition, ARTIFACT_TYPES


_CACHE: Optional[dict] = None
_CACHE_TTL_SECONDS = 45


def _running_processes() -> set[str]:
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return set()
    names = set()
    for line in result.stdout.splitlines():
        if line.startswith('"'):
            name = line.split('"', 2)[1].lower()
            names.add(name)
    return names


def _command_path(commands: Iterable[str]) -> Optional[str]:
    for command in commands:
        path = shutil.which(command)
        if path:
            return path
    return None


def _registry_matches(needles: Iterable[str]) -> List[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    needle_values = [item.lower() for item in needles]
    matches: List[str] = []
    for root, path in roots:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        try:
            for index in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub_name = winreg.EnumKey(key, index)
                    with winreg.OpenKey(key, sub_name) as sub_key:
                        display = str(winreg.QueryValueEx(sub_key, "DisplayName")[0]).lower()
                    if any(needle in display for needle in needle_values):
                        matches.append(display)
                except OSError:
                    continue
        finally:
            winreg.CloseKey(key)
    return matches


def _extension_found(agent: AgentDefinition) -> bool:
    if not agent.extension_ids:
        return False
    roots = [
        Path(os.environ.get("USERPROFILE", "")) / ".vscode" / "extensions",
        Path(os.environ.get("USERPROFILE", "")) / ".cursor" / "extensions",
    ]
    for root in roots:
        try:
            if any(any(token in child.name.lower() for token in agent.extension_ids) for child in root.iterdir() if child.is_dir()):
                return True
        except (OSError, PermissionError):
            continue
    return False


def _candidate_config_paths(agent: AgentDefinition, artifact_type: str, project: str = "") -> List[Path]:
    paths: List[Path] = []
    destination = agent.project_destination(artifact_type, project)
    if destination:
        paths.append(destination)
    destination = agent.global_destination(artifact_type)
    if destination:
        paths.append(destination)
    return paths


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except (OSError, PermissionError):
        return False


def _status_for(agent: AgentDefinition, artifact_type: str, installed: bool, command: Optional[str], project: str) -> dict:
    capability = agent.supported_artifacts.get(artifact_type, "unsupported")
    destinations = _candidate_config_paths(agent, artifact_type, project)
    existing_destination = next((_path for _path in destinations if _path_exists(_path)), None)
    if capability == "ready" and (installed or existing_destination is not None or artifact_type == "skill"):
        status = "ready"
    elif capability == "ready":
        status = "needs_setup"
    else:
        status = capability
    if not installed and command is None and existing_destination is None and status == "ready":
        status = "not_found"
    reason = agent.notes
    if installed:
        reason = f"Detected executable: {command}" if command else "Detected installed application"
    elif existing_destination:
        reason = f"Configuration path found: {existing_destination}"
    elif status == "not_found":
        reason = "Agent executable and known configuration path were not found"
    return {
        "agent_id": agent.id,
        "name": agent.name,
        "surface": ",".join(agent.surfaces),
        "artifact_type": artifact_type,
        "installed": installed,
        "supported": capability in ("ready", "needs_setup"),
        "status": status,
        "command": command,
        "destination": str(existing_destination or (destinations[0] if destinations else "")),
        "reason": reason,
        "capability": capability,
    }


def detect_agents(project: str = "", force: bool = False) -> dict:
    global _CACHE
    now = time.time()
    if not force and _CACHE and now - _CACHE["ts"] < _CACHE_TTL_SECONDS and _CACHE.get("project") == project:
        return _CACHE["data"]

    processes = _running_processes()
    result = []
    for agent in AGENTS:
        command = _command_path(agent.commands)
        process_found = any(name.lower() in processes for name in agent.process_names)
        extension_found = _extension_found(agent)
        registry_found = bool(_registry_matches([agent.name]))
        installed = bool(command or process_found or extension_found or registry_found)
        capabilities = {
            artifact_type: _status_for(agent, artifact_type, installed, command, project)
            for artifact_type in ARTIFACT_TYPES
        }
        result.append({
            "id": agent.id,
            "name": agent.name,
            "surfaces": agent.surfaces,
            "installed": installed,
            "command": command,
            "capabilities": capabilities,
            "notes": agent.notes,
        })

    data = {"agents": result, "cached_for_seconds": _CACHE_TTL_SECONDS, "scanned_at": now}
    _CACHE = {"ts": now, "project": project, "data": data}
    return data
