"""Agent definitions and capability metadata for SkillForge.

The registry is deliberately data-driven: detection and installation code use
these definitions instead of hard-coding agent-specific paths in Flask.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


ARTIFACT_TYPES = ("skill", "agent", "mcp", "plugin")


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    surfaces: List[str]
    commands: List[str] = field(default_factory=list)
    process_names: List[str] = field(default_factory=list)
    extension_ids: List[str] = field(default_factory=list)
    project_paths: Dict[str, Optional[str]] = field(default_factory=dict)
    global_paths: Dict[str, Optional[str]] = field(default_factory=dict)
    supported_artifacts: Dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def project_destination(self, artifact_type: str, project: str) -> Optional[Path]:
        relative = self.project_paths.get(artifact_type)
        if not relative or not project:
            return None
        return Path(project) / relative

    def global_destination(self, artifact_type: str) -> Optional[Path]:
        configured = self.global_paths.get(artifact_type)
        if not configured:
            return None
        if configured == "${CODEX_HOME:-~/.codex}/skills":
            configured = os.environ.get("CODEX_HOME", "~/.codex") + "/skills"
        value = os.path.expandvars(os.path.expanduser(configured))
        return Path(value)


AGENTS: List[AgentDefinition] = [
    AgentDefinition(
        id="kilo",
        name="Kilo Code",
        surfaces=["cli", "vscode"],
        commands=["kilo"],
        process_names=["kilo.exe"],
        extension_ids=["kilo", "kilocode"],
        project_paths={"skill": ".kilo/skills", "agent": ".kilo/agents", "mcp": ".kilo/kilo.json"},
        global_paths={"skill": "~/.kilo/skills", "agent": "~/.config/kilo/agents", "mcp": "~/.config/kilo/kilo.json"},
        supported_artifacts={"skill": "ready", "agent": "ready", "mcp": "ready", "plugin": "unsupported"},
        notes="Supports project and global skills, agents and MCP configuration.",
    ),
    AgentDefinition(
        id="codex",
        name="OpenAI Codex",
        surfaces=["cli", "desktop"],
        commands=["codex"],
        process_names=["codex.exe", "codexapp.exe"],
        project_paths={"skill": ".agents/skills"},
        global_paths={"skill": "${CODEX_HOME:-~/.codex}/skills"},
        supported_artifacts={"skill": "ready", "agent": "needs_setup", "mcp": "needs_setup", "plugin": "unsupported"},
        notes="Project skills use the interoperable .agents/skills path; global skills use CODEX_HOME/skills.",
    ),
    AgentDefinition(
        id="claude",
        name="Claude Code",
        surfaces=["cli", "desktop"],
        commands=["claude"],
        process_names=["claude.exe", "claude code.exe"],
        project_paths={"skill": ".claude/skills"},
        global_paths={"skill": "~/.claude/skills"},
        supported_artifacts={"skill": "ready", "agent": "needs_setup", "mcp": "needs_setup", "plugin": "ready"},
        notes="Claude Code Desktop shares the local Claude Code configuration surface.",
    ),
    AgentDefinition(
        id="cline",
        name="Cline",
        surfaces=["vscode"],
        commands=[],
        process_names=[],
        extension_ids=["cline", "claude-dev"],
        project_paths={"skill": ".cline/skills"},
        global_paths={"skill": "~/.cline/skills"},
        supported_artifacts={"skill": "ready", "agent": "unsupported", "mcp": "needs_setup", "plugin": "unsupported"},
        notes="Cline is detected through its VS Code installation and local skill paths.",
    ),
    AgentDefinition(
        id="gemini",
        name="Gemini CLI",
        surfaces=["cli"],
        commands=["gemini"],
        process_names=["gemini.exe", "node.exe"],
        project_paths={"skill": ".gemini/skills", "mcp": ".gemini/settings.json"},
        global_paths={"skill": "~/.gemini/skills", "mcp": "~/.gemini/settings.json"},
        supported_artifacts={"skill": "ready", "agent": "needs_setup", "mcp": "ready", "plugin": "needs_setup"},
        notes="Gemini CLI extensions are not copied as generic plugins; use its native extension flow.",
    ),
    AgentDefinition(
        id="copilot",
        name="GitHub Copilot CLI",
        surfaces=["cli", "vscode", "jetbrains"],
        commands=["copilot"],
        process_names=["copilot.exe"],
        project_paths={"skill": ".github/skills"},
        global_paths={"skill": "~/.copilot/skills"},
        supported_artifacts={"skill": "ready", "agent": "unsupported", "mcp": "needs_setup", "plugin": "unsupported"},
        notes="Also supports the interoperable .agents/skills location.",
    ),
    AgentDefinition(
        id="roo",
        name="Roo Code",
        surfaces=["vscode"],
        commands=[],
        process_names=[],
        extension_ids=["roo-cline", "roo"],
        project_paths={"skill": ".roo/skills"},
        global_paths={"skill": "~/.roo/skills"},
        supported_artifacts={"skill": "ready", "agent": "needs_setup", "mcp": "needs_setup", "plugin": "unsupported"},
        notes="Roo Code also supports .agents/skills for cross-agent sharing.",
    ),
    AgentDefinition(
        id="antigravity",
        name="Google Antigravity",
        surfaces=["desktop", "cli"],
        commands=["antigravity"],
        process_names=["antigravity.exe"],
        project_paths={"skill": ".agents/skills"},
        global_paths={"skill": "~/.agents/skills"},
        supported_artifacts={"skill": "ready", "agent": "needs_setup", "mcp": "needs_setup", "plugin": "needs_setup"},
        notes="Uses the interoperable .agents/skills path; plugins are native bundles.",
    ),
    AgentDefinition(
        id="cursor",
        name="Cursor",
        surfaces=["desktop"],
        commands=["cursor"],
        process_names=["cursor.exe"],
        project_paths={"skill": ".cursor/skills"},
        global_paths={},
        supported_artifacts={"skill": "needs_setup", "agent": "unsupported", "mcp": "needs_setup", "plugin": "unsupported"},
        notes="Detected for visibility; installation is conservative until the local path is confirmed.",
    ),
    AgentDefinition(
        id="windsurf",
        name="Windsurf",
        surfaces=["desktop"],
        commands=["windsurf"],
        process_names=["windsurf.exe"],
        project_paths={},
        global_paths={},
        supported_artifacts={"skill": "unsupported", "agent": "unsupported", "mcp": "needs_setup", "plugin": "unsupported"},
        notes="Detected for visibility; no stable generic Agent Skills destination is assumed.",
    ),
]


AGENTS_BY_ID = {agent.id: agent for agent in AGENTS}
