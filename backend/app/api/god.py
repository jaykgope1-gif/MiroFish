"""
God View Terminal API

Live stream of a simulation for the operator console, plus the operator's
interventions (pause, inject, whisper, interview, poll, report).

The simulation subprocess appends every agent action to
``<sim_dir>/twitter/actions.jsonl`` and ``<sim_dir>/reddit/actions.jsonl``.
This module tails those files and pushes new lines to the browser over
Server-Sent Events, so the console never has to re-fetch the whole state.

Resuming: every ``actions`` and ``audit`` event carries an SSE id of the
form ``<twitter_offset>:<reddit_offset>:<audit_offset>`` (byte offsets). A
client that reconnects passes it back (``?cursor=`` or the ``Last-Event-ID``
header) and receives only what it has not seen.

Interventions go through ``services/god_control.py`` to the simulation
process, which executes them between rounds. Each one is appended to the
audit log, whether it succeeded or not.
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple

from flask import Response, current_app, jsonify, request, stream_with_context

from . import god_bp
from ..config import Config
from ..services import god_branches, god_control
from ..services.god_control import GodUnavailable
from ..services.simulation_runner import SimulationRunner
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.god')

PLATFORMS = ("twitter", "reddit")
# Files the stream tails, in cursor order.
SOURCES = PLATFORMS + ("audit",)

# Seconds between file checks while the stream is idle.
POLL_INTERVAL = 0.4
# A named ping is sent this often so the client can detect a dead stream.
PING_INTERVAL = 10.0
# Upper bound on lines per SSE event; a large backlog is sent as several events.
MAX_BATCH_LINES = 500
# Upper bound on bytes read from one file per poll.
MAX_READ_BYTES = 1024 * 1024


def _sim_dir(simulation_id: str) -> str:
    return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)


def _parse_cursor(raw: Optional[str]) -> Dict[str, int]:
    """
    Parse ``"<twitter_offset>:<reddit_offset>[:<audit_offset>]"``.

    Anything invalid means "start from the beginning".
    """
    offsets = {source: 0 for source in SOURCES}
    if not raw:
        return offsets
    parts = raw.split(":")
    if len(parts) not in (len(PLATFORMS), len(SOURCES)):
        return offsets
    try:
        values = [max(0, int(part)) for part in parts]
    except ValueError:
        return offsets
    offsets.update(zip(SOURCES, values))
    return offsets


def _format_cursor(offsets: Dict[str, int]) -> str:
    return ":".join(str(offsets[source]) for source in SOURCES)


def _sse(event: str, data: dict, event_id: Optional[str] = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def read_new_lines(
    path: str,
    offset: int,
    platform: str,
    max_lines: int = MAX_BATCH_LINES,
) -> Tuple[List[dict], int, bool]:
    """
    Read complete JSON lines appended to ``path`` after byte ``offset``.

    Returns ``(items, new_offset, was_reset)``. ``was_reset`` is True when the
    file is shorter than ``offset`` (the simulation was restarted and its logs
    cleaned), in which case reading starts again from the beginning.

    Each item is the logged record plus ``platform`` and ``seq`` (the byte
    offset of the line, unique and increasing within a platform).
    A trailing line without a newline is left for the next call, because the
    simulation process may still be writing it.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        # Missing file: nothing yet, or logs were cleaned for a restart.
        return [], 0, offset > 0

    was_reset = size < offset
    if was_reset:
        offset = 0
    if size == offset:
        return [], offset, was_reset

    items: List[dict] = []
    with open(path, "rb") as handle:
        handle.seek(offset)
        chunk = handle.read(MAX_READ_BYTES)

    position = offset
    start = 0
    while len(items) < max_lines:
        end = chunk.find(b"\n", start)
        if end == -1:
            break
        raw_line = chunk[start:end]
        line_offset = position
        position += end - start + 1
        start = end + 1
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        record["platform"] = platform
        record["seq"] = line_offset
        items.append(record)

    return items, position, was_reset


def _status_snapshot(simulation_id: str) -> dict:
    """Runner state, whether the env is open, and the operator's clock control."""
    run_state = SimulationRunner.get_run_state(simulation_id)
    if run_state is None:
        status = {"simulation_id": simulation_id, "runner_status": "idle"}
    else:
        status = run_state.to_dict()
    status["env_alive"] = SimulationRunner.check_env_alive(simulation_id)
    status["god"] = god_control.get_state(simulation_id)
    return status


def _stream(simulation_id: str, offsets: Dict[str, int]) -> Iterator[str]:
    sim_dir = _sim_dir(simulation_id)
    paths = {
        platform: os.path.join(sim_dir, platform, "actions.jsonl")
        for platform in PLATFORMS
    }
    paths["audit"] = god_control.audit_path(simulation_id)

    yield _sse("hello", {
        "simulation_id": simulation_id,
        "server_time": datetime.now().isoformat(),
        "cursor": _format_cursor(offsets),
    })

    last_status_key = None
    last_send = time.monotonic()

    while True:
        sent = False

        status = _status_snapshot(simulation_id)
        # updated_at changes on every monitor tick; ignore it when deciding
        # whether the status is worth re-sending.
        status_key = json.dumps(
            {k: v for k, v in status.items() if k != "updated_at"},
            sort_keys=True,
            default=str,
        )
        if status_key != last_status_key:
            last_status_key = status_key
            yield _sse("status", status)
            sent = True

        for source in SOURCES:
            items, new_offset, was_reset = read_new_lines(
                paths[source], offsets[source], source
            )
            if was_reset:
                offsets[source] = 0
                yield _sse("reset", {"platform": source})
                sent = True
            if new_offset != offsets[source]:
                offsets[source] = new_offset
                if items:
                    yield _sse(
                        "audit" if source == "audit" else "actions",
                        {"platform": source, "items": items},
                        event_id=_format_cursor(offsets),
                    )
                    sent = True

        now = time.monotonic()
        if sent:
            last_send = now
            # More backlog may be waiting; go straight round again.
            continue
        if now - last_send >= PING_INTERVAL:
            last_send = now
            yield _sse("ping", {"server_time": datetime.now().isoformat()})
        time.sleep(POLL_INTERVAL)


@god_bp.route('/<simulation_id>/stream', methods=['GET'])
def stream_simulation(simulation_id: str):
    """
    Live event stream for one simulation (Server-Sent Events).

    Query:
        cursor: "<twitter_offset>:<reddit_offset>:<audit_offset>" to resume (optional).
                The Last-Event-ID header is honoured the same way.

    Events:
        hello    {simulation_id, server_time, cursor}
        status   runner state (same fields as /api/simulation/<id>/run-status)
                 plus env_alive and god {available, paused, holding, platforms};
                 sent on connect and whenever it changes
        actions  {platform, items: [...]} new lines of actions.jsonl, oldest
                 first; items are agent actions or round/simulation markers
                 (those have event_type). SSE id is the resume cursor.
        audit    {items: [...]} new entries of the intervention audit log
        reset    {platform} that log was truncated (simulation restarted);
                 platform is twitter, reddit or audit
        ping     {server_time} sent when nothing else was for 10 seconds
    """
    # Other endpoints create an empty directory for any id they are asked
    # about, so the directory alone does not prove the simulation exists.
    if not os.path.isfile(os.path.join(_sim_dir(simulation_id), "state.json")):
        return jsonify({
            "success": False,
            "error": f"Simulation not found: {simulation_id}",
        }), 404

    cursor = request.args.get("cursor") or request.headers.get("Last-Event-ID")
    offsets = _parse_cursor(cursor)

    response = Response(
        stream_with_context(_stream(simulation_id, offsets)),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    # Stop reverse proxies from buffering the stream.
    response.headers["X-Accel-Buffering"] = "no"
    return response


# ============== interventions ==============

POLL_DEFAULT_OPTIONS = ["yes", "no", "unsure"]


def _exists(simulation_id: str) -> bool:
    return os.path.isfile(os.path.join(_sim_dir(simulation_id), "state.json"))


def _agent_configs(simulation_id: str) -> List[dict]:
    path = os.path.join(_sim_dir(simulation_id), "simulation_config.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle).get("agent_configs", [])
    except (OSError, json.JSONDecodeError):
        return []


def _agent_name(configs: List[dict], agent_id: int) -> str:
    for config in configs:
        if config.get("agent_id") == agent_id:
            return config.get("entity_name") or f"Agent_{agent_id}"
    return f"Agent_{agent_id}"


def _interview_prompt(question: str) -> str:
    # Same prefix the existing interview endpoints use to stop tool calls.
    from .simulation import optimize_interview_prompt
    return optimize_interview_prompt(question)


def _platform_errors(results: Dict[str, dict]) -> str:
    return "; ".join(f"{name}: {r['error']}" for name, r in results.items() if "error" in r)


def _intervention(simulation_id: str, command: str, args: dict, action):
    """
    Run one intervention and write it to the audit log, success or failure.

    ``action`` returns (ok, summary, result, round_num). The HTTP response
    carries the audit entry so the console can show it immediately.
    """
    if not _exists(simulation_id):
        return jsonify({"success": False, "error": f"Simulation not found: {simulation_id}"}), 404
    status = 200
    try:
        ok, summary, result, round_num = action()
        if not ok:
            status = 502
    except GodUnavailable as error:
        ok, summary, result, round_num, status = False, str(error), None, None, 409
    except ValueError as error:
        ok, summary, result, round_num, status = False, str(error), None, None, 400
    except TimeoutError as error:
        ok, summary, result, round_num, status = False, str(error), None, None, 504
    except Exception as error:
        logger.error(f"god {command} failed: {error}")
        ok, summary, result, round_num, status = False, str(error), None, None, 500
    entry = god_control.record(simulation_id, command, args, ok, summary, result, round_num)
    body = {"success": ok, "data": entry}
    if not ok:
        body["error"] = summary
    return jsonify(body), status


def _round_of(results: Dict[str, dict]) -> Optional[int]:
    rounds = [r["round"] for r in results.values() if r.get("round") is not None]
    return max(rounds) if rounds else None


def _require_int(data: dict, key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _require_text(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text")
    return value.strip()


@god_bp.route('/<simulation_id>/pause', methods=['POST'])
def pause_simulation(simulation_id: str):
    """Hold the simulation clock. Takes effect when the current round ends."""
    def action():
        state = god_control.set_paused(simulation_id, True)
        return True, "Pause requested; each platform holds before its next round", state, None
    return _intervention(simulation_id, "pause", {}, action)


@god_bp.route('/<simulation_id>/resume', methods=['POST'])
def resume_simulation(simulation_id: str):
    """Release the simulation clock."""
    def action():
        state = god_control.set_paused(simulation_id, False)
        return True, "Resumed", state, None
    return _intervention(simulation_id, "resume", {}, action)


@god_bp.route('/<simulation_id>/step', methods=['POST'])
def step_simulation(simulation_id: str):
    """Run exactly one more round on each platform, then hold."""
    def action():
        state = god_control.step(simulation_id)
        return True, "Stepping one round on each platform, then holding", state, None
    return _intervention(simulation_id, "step", {}, action)


@god_bp.route('/<simulation_id>/inject', methods=['POST'])
def inject_event(simulation_id: str):
    """
    Introduce an event into the world as a post.

    OASIS has no author-less posts, so the event is posted by an agent:
    ``agent_id`` if given, otherwise the agent with the highest
    influence_weight in the simulation config.

    JSON: {"text": "...", "agent_id": 3 (optional), "platform": "twitter"|"reddit" (optional)}
    """
    data = request.get_json(silent=True) or {}

    def action():
        text = _require_text(data, "text")
        configs = _agent_configs(simulation_id)
        if data.get("agent_id") is not None:
            agent_id = _require_int(data, "agent_id")
        elif configs:
            agent_id = max(configs, key=lambda c: c.get("influence_weight") or 0)["agent_id"]
        else:
            raise ValueError("This simulation has no agents to post the event")
        name = _agent_name(configs, agent_id)
        results = god_control.send_all(
            simulation_id, "inject", {"agent_id": agent_id, "content": text}, data.get("platform")
        )
        posted = [p for p, r in results.items() if "error" not in r]
        ok = bool(posted)
        summary = (
            f"Posted as {name} on {', '.join(posted)}" if ok else f"Not posted: {_platform_errors(results)}"
        )
        if ok and len(posted) < len(results):
            summary += f" (failed: {_platform_errors(results)})"
        result = {"agent_id": agent_id, "agent_name": name, "content": text, "platforms": results}
        return ok, summary, result, _round_of(results)

    return _intervention(simulation_id, "inject", {k: data.get(k) for k in ("text", "agent_id", "platform")}, action)


@god_bp.route('/<simulation_id>/whisper', methods=['POST'])
def whisper_agent(simulation_id: str):
    """
    Give one agent private information: written to that agent's memory on
    each running platform, visible to no other agent.

    JSON: {"agent_id": 3, "text": "...", "platform": optional}
    """
    data = request.get_json(silent=True) or {}

    def action():
        agent_id = _require_int(data, "agent_id")
        text = _require_text(data, "text")
        name = _agent_name(_agent_configs(simulation_id), agent_id)
        results = god_control.send_all(
            simulation_id, "whisper", {"agent_id": agent_id, "text": text}, data.get("platform")
        )
        told = [p for p, r in results.items() if "error" not in r]
        ok = bool(told)
        summary = (
            f"Whispered to {name} on {', '.join(told)}" if ok else f"Not delivered: {_platform_errors(results)}"
        )
        result = {"agent_id": agent_id, "agent_name": name, "text": text, "platforms": results}
        return ok, summary, result, _round_of(results)

    return _intervention(simulation_id, "whisper", {k: data.get(k) for k in ("agent_id", "text", "platform")}, action)


@god_bp.route('/<simulation_id>/interview', methods=['POST'])
def interview_agent_live(simulation_id: str):
    """
    Question one agent. Works mid-run (answered between rounds) and after
    the last round. The exchange is not written to the agent's memory.

    JSON: {"agent_id": 3, "question": "...", "platform": optional}
    """
    data = request.get_json(silent=True) or {}

    def action():
        agent_id = _require_int(data, "agent_id")
        question = _require_text(data, "question")
        name = _agent_name(_agent_configs(simulation_id), agent_id)
        results = god_control.send_all(
            simulation_id, "interview",
            {"agent_id": agent_id, "prompt": _interview_prompt(question)},
            data.get("platform"),
        )
        answered = [p for p, r in results.items() if "error" not in r]
        ok = bool(answered)
        summary = (
            f"{name} answered on {', '.join(answered)}" if ok else f"No answer: {_platform_errors(results)}"
        )
        result = {"agent_id": agent_id, "agent_name": name, "question": question, "platforms": results}
        return ok, summary, result, _round_of(results)

    return _intervention(simulation_id, "interview", {k: data.get(k) for k in ("agent_id", "question", "platform")}, action)


def tally_answers(answers: List[dict], options: List[str]) -> Dict[str, int]:
    """
    Count poll answers by the option each one starts with.

    Answers that start with none of the options, or failed, are counted
    under "unparsed" rather than guessed at.
    """
    counts = {option: 0 for option in options}
    counts["unparsed"] = 0
    # Longest first so "no" does not claim an answer that starts "not sure".
    ordered = sorted(options, key=len, reverse=True)
    for answer in answers:
        text = (answer.get("response") or "").strip().lower().lstrip("\"'*`([ ")
        choice = next(
            (o for o in ordered
             if text.startswith(o.lower()) and not text[len(o):len(o) + 1].isalnum()),
            None,
        )
        answer["choice"] = choice
        counts[choice if choice else "unparsed"] += 1
    return counts


@god_bp.route('/<simulation_id>/poll', methods=['POST'])
def poll_agents(simulation_id: str):
    """
    Ask many agents one question and tally the answers.

    Each agent is asked on one platform (its memory differs per platform):
    ``platform`` if given, otherwise the first running one.

    JSON: {"question": "...", "options": ["yes","no","unsure"] (optional),
           "agent_ids": [..] (optional, default all), "platform": optional}
    """
    data = request.get_json(silent=True) or {}

    def action():
        question = _require_text(data, "question")
        options = data.get("options") or POLL_DEFAULT_OPTIONS
        if (not isinstance(options, list) or len(options) < 2
                or not all(isinstance(o, str) and o.strip() for o in options)):
            raise ValueError("options must be a list of at least two non-empty strings")
        options = [o.strip() for o in options]
        configs = _agent_configs(simulation_id)
        agent_ids = data.get("agent_ids")
        if agent_ids is None:
            agent_ids = [c["agent_id"] for c in configs]
        if (not isinstance(agent_ids, list) or not agent_ids
                or not all(isinstance(a, int) and not isinstance(a, bool) for a in agent_ids)):
            raise ValueError("agent_ids must be a non-empty list of integers")

        prompt = _interview_prompt(
            f"{question}\nBegin your reply with exactly one of these words: "
            f"{' / '.join(options)}. Then give one sentence of reasoning."
        )
        platform = god_control._require_platforms(simulation_id, data.get("platform"))[0]
        result = god_control.send(
            simulation_id, platform, "poll",
            {"agent_ids": agent_ids, "prompt": prompt},
            timeout=float(data.get("timeout", 600)),
        )
        answers = result.get("answers", [])
        for answer in answers:
            answer["agent_name"] = _agent_name(configs, answer["agent_id"])
        counts = tally_answers(answers, options)
        summary = f"{len(answers)} asked on {platform}: " + ", ".join(
            f"{option} {count}" for option, count in counts.items() if count or option != "unparsed"
        )
        payload = {
            "question": question, "options": options, "platform": platform,
            "counts": counts, "answers": answers,
        }
        return True, summary, payload, result.get("round")

    args = {k: data.get(k) for k in ("question", "options", "platform")}
    args["agent_count"] = len(data["agent_ids"]) if isinstance(data.get("agent_ids"), list) else "all"
    return _intervention(simulation_id, "poll", args, action)


@god_bp.route('/<simulation_id>/report', methods=['POST'])
def trigger_report(simulation_id: str):
    """
    Start the report agent on this simulation.

    Delegates to POST /api/report/generate, which only accepts a simulation
    whose run has ended and needs Zep configured; its refusal is passed on.
    """
    def action():
        from .report import generate_report
        with current_app.test_request_context(json={"simulation_id": simulation_id, "force_regenerate": True}):
            response = generate_report()
        status = 200
        if isinstance(response, tuple):
            response, status = response[0], response[1]
        body = response.get_json() or {}
        if status >= 400 or not body.get("success"):
            return False, f"Report not started: {body.get('error') or status}", body, None
        data = body.get("data") or {}
        return True, f"Report started ({data.get('report_id') or data.get('task_id')})", data, None

    return _intervention(simulation_id, "report", {}, action)


@god_bp.route('/<simulation_id>/agents/<int:agent_id>/memory', methods=['GET'])
def get_agent_memory(simulation_id: str, agent_id: int):
    """
    Read one agent's working memory (its LLM context) from the running
    simulation process. Read-only, so it is not written to the audit log.

    Query: platform (optional; default every running platform)
    """
    if not _exists(simulation_id):
        return jsonify({"success": False, "error": f"Simulation not found: {simulation_id}"}), 404
    try:
        results = god_control.send_all(
            simulation_id, "memory", {"agent_id": agent_id}, request.args.get("platform")
        )
    except GodUnavailable as error:
        return jsonify({"success": False, "error": str(error)}), 409
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    return jsonify({"success": True, "data": {"agent_id": agent_id, "platforms": results}})


@god_bp.route('/<simulation_id>/audit', methods=['GET'])
def get_audit_log(simulation_id: str):
    """Every intervention on this run, oldest first."""
    if not _exists(simulation_id):
        return jsonify({"success": False, "error": f"Simulation not found: {simulation_id}"}), 404
    entries, offset = [], 0
    while True:
        items, new_offset, _ = read_new_lines(god_control.audit_path(simulation_id), offset, "audit")
        if new_offset == offset:
            break
        entries.extend(items)
        offset = new_offset
    return jsonify({"success": True, "data": {"count": len(entries), "entries": entries}})


# ============== branches ==============

@god_bp.route('/<simulation_id>/fork', methods=['POST'])
def fork_simulation(simulation_id: str):
    """
    Branch the world at the current round. The branch is a new simulation
    (``<root>__<name>``) that shares all history up to the fork and then runs
    on its own. If the clock is paused, the branch starts paused as well.

    JSON: {"name": "whatif"}
    """
    data = request.get_json(silent=True) or {}

    def action():
        info = god_branches.fork(simulation_id, data.get("name"))
        return True, f"Forked '{info['name']}' at round {info['fork_round']} ({info['simulation_id']})", info, info["fork_round"]

    return _intervention(simulation_id, "fork", {"name": data.get("name")}, action)


@god_bp.route('/<simulation_id>/branches', methods=['GET'])
def get_branches(simulation_id: str):
    """The base run and every fork in this simulation's family."""
    if not _exists(simulation_id):
        return jsonify({"success": False, "error": f"Simulation not found: {simulation_id}"}), 404
    return jsonify({"success": True, "data": {
        "current": god_branches.branch_name(simulation_id),
        "branches": god_branches.list_branches(simulation_id),
    }})


@god_bp.route('/<simulation_id>/diff', methods=['GET'])
def diff_branches(simulation_id: str):
    """
    Compare two branches of this simulation's family.

    Query: a, b - branch names ('base' is the original run) or simulation ids
    """
    if not _exists(simulation_id):
        return jsonify({"success": False, "error": f"Simulation not found: {simulation_id}"}), 404
    try:
        a = god_branches.resolve(simulation_id, request.args.get("a", ""))
        b = god_branches.resolve(simulation_id, request.args.get("b", ""))
        return jsonify({"success": True, "data": god_branches.diff(a, b)})
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400
