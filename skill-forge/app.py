from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

# The installer modules live one directory above the Vite app.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import artifact_installer as installer
import detector
import skill_installer as si


app = Flask(__name__, static_folder="dist", static_url_path="")
CORS(app)

log_queues: dict[str, queue.Queue] = {}
jobs: dict[str, dict[str, Any]] = {}
lock = threading.Lock()

VALID_SCOPES = {"project", "global"}
VALID_ARTIFACTS = {"skill", "agent", "mcp", "plugin"}


def _enqueue(job_id: str, message: str, level: str = "info", **extra: Any) -> None:
    item = {"jobId": job_id, "level": level, "message": message, "ts": time.time(), **extra}
    with lock:
        q = log_queues.get(job_id)
        if q is not None:
            q.put(item)


def _final_status(results: list[dict]) -> str:
    statuses = [item.get("status") for item in results]
    installed = sum(status == "installed" for status in statuses)
    if installed == len(statuses) and installed > 0:
        return "installed"
    if installed > 0:
        return "partial"
    return "failed"


def _run_install(job_id: str, payload: dict[str, Any]) -> None:
    scope = payload["scope"]
    artifact_type = payload["artifact_type"]
    project = payload.get("project", "")
    agent_ids = payload.get("agents", [])
    force = bool(payload.get("force"))
    try:
        if scope == "project":
            if not project:
                projects = si.get_vscode_projects_windows() or si.get_vscode_projects_from_storage()
                if not projects:
                    cwd = os.getcwd()
                    if any(si.detect_project_context(cwd).values()):
                        projects = [cwd]
                project = projects[0] if projects else ""
            if not project or not Path(project).is_dir():
                _enqueue(job_id, "Project directory was not found", "failed")
                _enqueue(job_id, "Installation failed", "failed", status="failed", results=[])
                return

        _enqueue(job_id, f"Preparing {artifact_type} installation", "info", status="running")
        _enqueue(job_id, f"Targets: {', '.join(agent_ids)}", "info")

        def log_callback(message: str, level: str = "info") -> None:
            _enqueue(job_id, message, level)

        if artifact_type == "skill":
            results = installer.install_skill(payload["source"], agent_ids, scope, project, force=force, log_callback=log_callback)
        elif artifact_type == "agent":
            results = installer.install_agent(agent_ids, scope, project, payload["source"], force=force)
        elif artifact_type == "mcp":
            results = installer.install_mcp(agent_ids, scope, project, payload.get("options", {}), log_callback=log_callback)
        else:
            results = [{"agent_id": agent_id, "status": "unsupported", "destination": "", "message": "Plugins require a native agent marketplace and are not handled by the generic installer"} for agent_id in agent_ids]

        status = _final_status(results)
        final_level = "completed" if status in {"installed", "partial"} else "failed"
        _enqueue(job_id, f"Installation {status}", final_level, status=status, results=results)
    except Exception as exc:  # noqa: BLE001
        _enqueue(job_id, f"Installation failed: {exc}", "failed", status="failed", results=[])
    finally:
        with lock:
            jobs.setdefault(job_id, {})["finished_at"] = time.time()


@app.get("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/projects")
def get_projects():
    try:
        projects = si.get_vscode_projects_windows()
        if not projects:
            projects = si.get_vscode_projects_from_storage()
        if not projects:
            cwd = os.getcwd()
            if any(si.detect_project_context(cwd).values()):
                projects = [cwd]
        return jsonify({"projects": projects})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"projects": [], "error": str(exc)}), 500


@app.get("/api/agents")
def get_agents():
    project = request.args.get("project", "")
    force = request.args.get("refresh", "false").lower() == "true"
    return jsonify(detector.detect_agents(project=project, force=force))


@app.get("/api/agents/<agent_id>/capabilities")
def get_agent_capabilities(agent_id: str):
    data = detector.detect_agents(project=request.args.get("project", ""))
    agent = next((item for item in data["agents"] if item["id"] == agent_id), None)
    if agent is None:
        return jsonify({"error": "Unknown agent"}), 404
    return jsonify(agent)


def _validate_install_payload(data: Any) -> tuple[dict | None, tuple[Response, int] | None]:
    if not isinstance(data, dict):
        return None, (jsonify({"error": "JSON object is required"}), 400)
    scope = data.get("scope", "project")
    artifact_type = data.get("artifact_type", "skill")
    agents = data.get("agents") or []
    if scope not in VALID_SCOPES:
        return None, (jsonify({"error": "scope must be project or global"}), 400)
    if artifact_type not in VALID_ARTIFACTS:
        return None, (jsonify({"error": "Unsupported artifact_type"}), 400)
    if not isinstance(agents, list) or not agents or any(not isinstance(item, str) for item in agents):
        return None, (jsonify({"error": "agents must be a non-empty list"}), 400)
    known = detector.detect_agents(project=data.get("project", ""))["agents"]
    known_ids = {item["id"] for item in known}
    unknown = [agent_id for agent_id in agents if agent_id not in known_ids]
    if unknown:
        return None, (jsonify({"error": f"Unknown agents: {', '.join(unknown)}"}), 400)
    payload = dict(data)
    payload["scope"] = scope
    payload["artifact_type"] = artifact_type
    payload["agents"] = list(dict.fromkeys(agents))
    if artifact_type in {"skill", "agent"} and not str(data.get("source", "")).strip():
        return None, (jsonify({"error": "source is required"}), 400)
    if artifact_type == "mcp":
        options = data.get("options") or {}
        if not options.get("name") or not options.get("command"):
            return None, (jsonify({"error": "MCP options require name and command"}), 400)
        payload["options"] = options
    return payload, None


@app.post("/api/install/preview")
def preview_install():
    payload, error = _validate_install_payload(request.get_json(silent=True))
    if error:
        return error
    if payload["artifact_type"] == "mcp":
        return jsonify(installer.preview_mcp(payload["agents"], payload["scope"], payload.get("project", ""), payload["options"]))
    return jsonify({"requires_confirmation": False, "results": []})


@app.post("/api/install")
def start_install():
    payload, error = _validate_install_payload(request.get_json(silent=True))
    if error:
        return error
    if payload["artifact_type"] == "mcp" and not payload.get("confirm", False):
        return jsonify({"error": "MCP installation requires confirmation", "preview": installer.preview_mcp(payload["agents"], payload["scope"], payload.get("project", ""), payload["options"])}), 409

    job_id = f"job_{int(time.time() * 1000)}"
    with lock:
        log_queues[job_id] = queue.Queue()
        jobs[job_id] = {"created_at": time.time(), "payload": payload}
    thread = threading.Thread(target=_run_install, args=(job_id, payload), daemon=True)
    thread.start()
    return jsonify({"jobId": job_id})


@app.get("/api/logs/<job_id>")
def stream_logs(job_id: str):
    def event_stream():
        with lock:
            q = log_queues.get(job_id)
        if q is None:
            yield f"data: {json.dumps({'jobId': job_id, 'level': 'failed', 'message': 'Job not found', 'ts': time.time()})}\n\n"
            return
        try:
            while True:
                try:
                    item = q.get(timeout=20)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                    if item["level"] in ("completed", "failed"):
                        break
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            with lock:
                log_queues.pop(job_id, None)

    return Response(event_stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=True)
