"""
God View branches: fork a running simulation and compare timelines.

A branch is an ordinary simulation directory named ``<root>__<name>`` with a
``branch.json`` describing where it came from. Forking asks the parent's
simulation process for a snapshot (database, action log, agent memories,
clock) and starts a new process that resumes from it, so both timelines
share everything up to the forked round and run independently after.
"""

import json
import os
import re
import shutil
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from . import god_control
from .simulation_runner import SimulationRunner

logger = get_logger('mirofish.god_branches')

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
BASE_NAME = "base"
STANCES = ("supportive", "opposing", "neutral", "observer")
AUTHORED = {"CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"}


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def branch_info(simulation_id: str) -> Optional[dict]:
    return _read_json(os.path.join(god_control.sim_dir(simulation_id), "branch.json"))


def root_of(simulation_id: str) -> str:
    info = branch_info(simulation_id)
    return info["root"] if info else simulation_id


def list_branches(simulation_id: str) -> List[dict]:
    """The whole family this simulation belongs to: the base run first, then forks by creation time."""
    root = root_of(simulation_id)
    family = [{"simulation_id": root, "name": BASE_NAME, "parent": None, "fork_round": None, "created_at": ""}]
    base_dir = Config.OASIS_SIMULATION_DATA_DIR
    for entry in sorted(os.listdir(base_dir)) if os.path.isdir(base_dir) else []:
        info = branch_info(entry)
        if info and info.get("root") == root:
            family.append({
                "simulation_id": entry, "name": info["name"], "parent": info["parent"],
                "fork_round": info["fork_round"], "created_at": info.get("created_at", ""),
            })
    family[1:] = sorted(family[1:], key=lambda b: b["created_at"])
    for branch in family:
        run_state = SimulationRunner.get_run_state(branch["simulation_id"])
        branch["runner_status"] = run_state.runner_status.value if run_state else "idle"
        branch["current_round"] = run_state.current_round if run_state else 0
    return family


def resolve(simulation_id: str, name_or_id: str) -> str:
    """Turn 'base', a branch name or a full id into a simulation id within this family."""
    wanted = (name_or_id or "").strip()
    for branch in list_branches(simulation_id):
        if wanted in (branch["name"], branch["simulation_id"]):
            return branch["simulation_id"]
    raise ValueError(f"No branch named '{wanted}' in this simulation's family")


def fork(simulation_id: str, name: str) -> dict:
    """
    Branch the world at the current round and start the branch running.

    Each running platform is snapshotted between rounds. If the clock is
    paused both platforms fork at the same round and the branch starts
    paused too; otherwise each forks at whatever round it is about to run.
    """
    if not NAME_PATTERN.match(name or ""):
        raise ValueError("Branch name must be 1-32 letters, digits, '-' or '_' and start with a letter or digit")
    if name == BASE_NAME:
        raise ValueError(f"'{BASE_NAME}' is reserved for the original run")
    root = root_of(simulation_id)
    branch_id = f"{root}__{name}"
    parent_dir = god_control.sim_dir(simulation_id)
    dest = god_control.sim_dir(branch_id)
    if os.path.exists(dest):
        raise ValueError(f"A branch named '{name}' already exists")

    platforms = god_control._require_platforms(simulation_id)
    os.makedirs(os.path.join(dest, "god"))
    try:
        for filename in ("reddit_profiles.json", "twitter_profiles.csv"):
            shutil.copyfile(os.path.join(parent_dir, filename), os.path.join(dest, filename))
        for filename in ("simulation_config.json", "state.json"):
            data = _read_json(os.path.join(parent_dir, filename)) or {}
            data["simulation_id"] = branch_id
            if filename == "state.json":
                data["status"] = "ready"
            with open(os.path.join(dest, filename), "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)

        snapshots = god_control.send_all(
            simulation_id, "snapshot", {"dest_dir": os.path.abspath(dest)}
        )
        failed = {p: r["error"] for p, r in snapshots.items() if "error" in r}
        if failed:
            raise RuntimeError("Snapshot failed: " + "; ".join(f"{p}: {e}" for p, e in failed.items()))

        fork_rounds = {p: r["round"] for p, r in snapshots.items()}
        info = {
            "simulation_id": branch_id, "name": name, "root": root, "parent": simulation_id,
            "fork_rounds": fork_rounds, "fork_round": min(fork_rounds.values()),
            "created_at": datetime.now().isoformat(),
        }
        with open(os.path.join(dest, "branch.json"), "w", encoding="utf-8") as handle:
            json.dump(info, handle, ensure_ascii=False, indent=2)
        with open(os.path.join(dest, "god", "resume.json"), "w", encoding="utf-8") as handle:
            json.dump({"parent": simulation_id, "created_at": info["created_at"]}, handle)
        # The branch inherits the interventions made before the fork.
        parent_audit = god_control.audit_path(simulation_id)
        if os.path.exists(parent_audit):
            shutil.copyfile(parent_audit, god_control.audit_path(branch_id))

        parent_state = SimulationRunner.get_run_state(simulation_id)
        SimulationRunner.start_simulation(
            simulation_id=branch_id,
            platform="parallel" if len(platforms) > 1 else platforms[0],
            max_rounds=parent_state.total_rounds if parent_state else None,
        )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    god_control.record(
        branch_id, "fork", {"name": name}, True,
        f"Forked from {branch_name(simulation_id)} at round {info['fork_round']}",
        info, info["fork_round"],
    )
    return info


def branch_name(simulation_id: str) -> str:
    info = branch_info(simulation_id)
    return info["name"] if info else BASE_NAME


# ---------- diff ----------

def _lineage(simulation_id: str) -> List[dict]:
    """[this, parent, ..., base] with the round each was forked at (None for base)."""
    chain = []
    current = simulation_id
    while current:
        info = branch_info(current)
        chain.append({"id": current, "fork_round": info["fork_round"] if info else None})
        current = info["parent"] if info else None
    return chain


def divergence_round(a: str, b: str) -> int:
    """First round at which the two timelines can differ."""
    chain_a, chain_b = _lineage(a), _lineage(b)
    ids_b = {node["id"] for node in chain_b}
    common = next((node["id"] for node in chain_a if node["id"] in ids_b), None)
    if common is None:
        raise ValueError("These simulations do not share a history")
    rounds = []
    for chain in (chain_a, chain_b):
        # The fork that left the common ancestor on this side, if any.
        for index, node in enumerate(chain):
            if node["id"] == common:
                if index > 0:
                    rounds.append(chain[index - 1]["fork_round"])
                break
    if not rounds:
        raise ValueError("Pick two different branches")
    return min(rounds)


def _load_side(simulation_id: str, start_round: int) -> dict:
    directory = god_control.sim_dir(simulation_id)
    config = _read_json(os.path.join(directory, "simulation_config.json")) or {}
    agents = {c["agent_id"]: c for c in config.get("agent_configs", [])}
    topics = [t for t in (config.get("event_config") or {}).get("hot_topics", []) if t]
    rounds: Dict[int, dict] = {}
    by_agent: Counter = Counter()
    by_type: Counter = Counter()
    by_topic: Counter = Counter()
    last_round = 0
    for platform in god_control.PLATFORMS:
        path = os.path.join(directory, platform, "actions.jsonl")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                round_num = record.get("round", 0)
                if record.get("event_type") == "round_end":
                    last_round = max(last_round, round_num)
                if "event_type" in record or "agent_id" not in record or round_num < start_round:
                    continue
                row = rounds.setdefault(round_num, {"total": 0, "stance": Counter()})
                row["total"] += 1
                stance = (agents.get(record["agent_id"]) or {}).get("stance")
                row["stance"][stance if stance in STANCES else "unknown"] += 1
                by_agent[record["agent_id"]] += 1
                by_type[record.get("action_type", "")] += 1
                if record.get("action_type") in AUTHORED:
                    text = ((record.get("action_args") or {}).get("content")
                            or (record.get("action_args") or {}).get("quote_content") or "").lower()
                    for topic in topics:
                        if topic.lower() in text:
                            by_topic[topic] += 1
    audit = []
    audit_file = god_control.audit_path(simulation_id)
    if os.path.exists(audit_file):
        with open(audit_file, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("ok") and entry.get("round", 0) >= start_round and entry.get("command") not in ("interview", "poll"):
                    audit.append({k: entry.get(k) for k in ("round", "command", "summary")})
    return {
        "simulation_id": simulation_id, "name": branch_name(simulation_id), "last_round": last_round,
        "rounds": rounds, "by_agent": by_agent, "by_type": by_type, "by_topic": by_topic,
        "topics": topics, "agents": agents, "interventions": audit,
    }


def diff(a: str, b: str) -> dict:
    """
    How two branches diverged, counted from the first round they can differ
    through the last round both have completed.
    """
    start = divergence_round(a, b)
    side_a, side_b = _load_side(a, start), _load_side(b, start)
    through = min(side_a["last_round"], side_b["last_round"])

    def totals(side: dict) -> dict:
        rows = [row for r, row in side["rounds"].items() if r <= through]
        stance: Counter = Counter()
        for row in rows:
            stance.update(row["stance"])
        return {
            "actions": sum(row["total"] for row in rows),
            "stance": {s: stance.get(s, 0) for s in STANCES},
        }

    def summary(side: dict) -> dict:
        return {
            "simulation_id": side["simulation_id"], "name": side["name"], "last_round": side["last_round"],
            "totals": totals(side), "by_type": dict(side["by_type"]), "by_topic": dict(side["by_topic"]),
            "interventions": side["interventions"],
        }

    rounds = []
    for round_num in range(start, through + 1):
        row = {"round": round_num}
        for key, side in (("a", side_a), ("b", side_b)):
            data = side["rounds"].get(round_num, {"total": 0, "stance": Counter()})
            row[key] = {"total": data["total"], "stance": {s: data["stance"].get(s, 0) for s in STANCES}}
        rounds.append(row)

    agent_ids = set(side_a["by_agent"]) | set(side_b["by_agent"])
    agents = sorted(
        (
            {
                "agent_id": agent_id,
                "name": (side_a["agents"].get(agent_id) or {}).get("entity_name", f"Agent_{agent_id}"),
                "a": side_a["by_agent"].get(agent_id, 0), "b": side_b["by_agent"].get(agent_id, 0),
            }
            for agent_id in agent_ids
        ),
        key=lambda row: (-abs(row["b"] - row["a"]), row["agent_id"]),
    )[:12]

    return {
        "diverged_at": start, "compared_through": through,
        "a": summary(side_a), "b": summary(side_b),
        "topics": side_a["topics"], "rounds": rounds, "agents": agents,
        # by_type / by_topic / agents count every round from the divergence on,
        # including rounds only one side has reached.
        "note": None if side_a["last_round"] == side_b["last_round"] else
                f"{side_a['name']} is at round {side_a['last_round']}, {side_b['name']} at {side_b['last_round']}",
    }
