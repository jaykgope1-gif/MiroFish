"""
God View control channel (backend side).

Sends operator commands to a running simulation process through the files
described in ``backend/scripts/god_control.py`` and records every
intervention in ``<sim_dir>/god/audit.jsonl``.
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from .simulation_runner import RunnerStatus, SimulationRunner

logger = get_logger('mirofish.god_control')

PLATFORMS = ("twitter", "reddit")
_audit_lock = threading.Lock()


class GodUnavailable(RuntimeError):
    """The simulation process is not there to receive commands."""


def sim_dir(simulation_id: str) -> str:
    return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)


def god_dir(simulation_id: str) -> str:
    return os.path.join(sim_dir(simulation_id), "god")


def audit_path(simulation_id: str) -> str:
    return os.path.join(god_dir(simulation_id), "audit.jsonl")


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: str, data: dict) -> None:
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(tmp, path)


def process_alive(simulation_id: str) -> bool:
    """True while the simulation subprocess exists (running rounds or waiting)."""
    process = SimulationRunner._processes.get(simulation_id)
    if process is not None:
        return process.poll() is None
    # After a backend restart the process handle is gone; fall back to the
    # status the script itself maintains.
    return SimulationRunner.check_env_alive(simulation_id)


def get_state(simulation_id: str) -> dict:
    """Pause request plus what each platform loop reports about itself."""
    control = _read_json(os.path.join(god_dir(simulation_id), "control.json")) or {}
    state = _read_json(os.path.join(god_dir(simulation_id), "state.json")) or {}
    alive = process_alive(simulation_id)
    platforms = state.get("platforms", {}) if alive else {}
    active = [p for p in platforms.values() if not p.get("finished")]
    return {
        "available": alive and bool(platforms),
        "paused": bool(control.get("paused")) and alive,
        # Paused takes effect between rounds: true once every platform that
        # still has rounds to run is actually waiting.
        "holding": bool(active) and all(p.get("holding") for p in active),
        "platforms": platforms,
    }


def current_round(simulation_id: str) -> int:
    platforms = get_state(simulation_id)["platforms"]
    if platforms:
        return max(p.get("round", 0) for p in platforms.values())
    run_state = SimulationRunner.get_run_state(simulation_id)
    return run_state.current_round if run_state else 0


def _require_platforms(simulation_id: str, platform: Optional[str] = None) -> List[str]:
    state = get_state(simulation_id)
    if not state["available"]:
        raise GodUnavailable(
            "The simulation process is not running, so there is nothing to send this to. "
            "Start the simulation first."
        )
    names = [p for p in PLATFORMS if p in state["platforms"]]
    if platform:
        if platform not in names:
            raise ValueError(f"Platform '{platform}' is not part of this run (running: {', '.join(names)})")
        return [platform]
    return names


def set_paused(simulation_id: str, paused: bool) -> dict:
    _require_platforms(simulation_id)
    path = os.path.join(god_dir(simulation_id), "control.json")
    control = _read_json(path) or {"step_seq": 0}
    control["paused"] = paused
    _write_json(path, control)
    return get_state(simulation_id)


def step(simulation_id: str) -> dict:
    """Let each platform run exactly one more round, then hold again."""
    _require_platforms(simulation_id)
    path = os.path.join(god_dir(simulation_id), "control.json")
    control = _read_json(path) or {"step_seq": 0}
    control["paused"] = True
    control["step_seq"] = int(control.get("step_seq", 0)) + 1
    _write_json(path, control)
    return get_state(simulation_id)


def send(
    simulation_id: str,
    platform: str,
    command_type: str,
    args: Dict[str, Any],
    timeout: float = 180.0,
) -> dict:
    """
    Send one command to one platform loop and wait for its response.

    Commands run between rounds, so the wait can be as long as one round.
    Raises TimeoutError, GodUnavailable, or RuntimeError (command failed).
    """
    command_id = uuid.uuid4().hex
    base = god_dir(simulation_id)
    command_file = os.path.join(base, "commands", platform, f"{command_id}.json")
    response_file = os.path.join(base, "responses", platform, f"{command_id}.json")
    os.makedirs(os.path.dirname(command_file), exist_ok=True)
    _write_json(command_file, {
        "command_id": command_id,
        "command_type": command_type,
        "args": args,
        "timestamp": datetime.now().isoformat(),
    })

    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            response = _read_json(response_file)
            if response is not None:
                try:
                    os.remove(response_file)
                except OSError:
                    pass
                if response.get("status") != "completed":
                    raise RuntimeError(response.get("error") or "command failed")
                result = response.get("result") or {}
                result["round"] = response.get("round")
                return result
            if not process_alive(simulation_id):
                raise GodUnavailable("The simulation process exited before answering.")
            time.sleep(0.2)
        raise TimeoutError(
            f"No answer from the {platform} loop within {int(timeout)}s. "
            "Commands run between rounds; a long round delays them."
        )
    finally:
        try:
            os.remove(command_file)
        except OSError:
            pass


def send_all(
    simulation_id: str,
    command_type: str,
    args: Dict[str, Any],
    platform: Optional[str] = None,
    timeout: float = 180.0,
) -> Dict[str, dict]:
    """Send to every running platform (or one). Per-platform result or {'error': ...}."""
    names = _require_platforms(simulation_id, platform)
    results: Dict[str, dict] = {}

    def run(name: str) -> None:
        try:
            results[name] = send(simulation_id, name, command_type, args, timeout)
        except Exception as error:
            results[name] = {"error": str(error)}

    threads = [threading.Thread(target=run, args=(name,), daemon=True) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def record(
    simulation_id: str,
    command: str,
    args: Dict[str, Any],
    ok: bool,
    summary: str,
    result: Optional[dict] = None,
    round_num: Optional[int] = None,
) -> dict:
    """Append one intervention to the audit log and return the entry."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now().isoformat(),
        "round": current_round(simulation_id) if round_num is None else round_num,
        "command": command,
        "args": args,
        "ok": ok,
        "summary": summary,
        "result": result,
    }
    os.makedirs(god_dir(simulation_id), exist_ok=True)
    with _audit_lock:
        with open(audit_path(simulation_id), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("god %s on %s: %s", command, simulation_id, summary)
    return entry
