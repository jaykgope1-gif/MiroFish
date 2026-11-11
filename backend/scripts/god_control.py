"""
God View control channel (simulation-process side).

The Flask backend cannot reach into the simulation process, so operator
commands travel through files under ``<sim_dir>/god/``:

    control.json                 {"paused": bool, "step_seq": int}  (backend writes)
    state.json                   per-platform round / holding / finished (this side writes)
    commands/<platform>/<id>.json   one operator command              (backend writes)
    responses/<platform>/<id>.json  its result                        (this side writes)

Each platform loop calls ``checkpoint()`` before every round. Commands are
executed there, between rounds, so they never race a round that is in flight.
While the operator has paused the clock the checkpoint holds the loop and
keeps serving commands. After the last round ``serve()`` keeps answering
read-only commands (interview, poll, memory) until the environment closes.

Commands act on agents directly rather than through ``env.step()``, which
would refresh the recommender and advance the Twitter clock.

Forking: the ``snapshot`` command writes a platform's world into another
simulation directory (``<branch>/god/snapshot/``): a copy of its database,
its action log so far, every agent's memory, and its clock. A simulation
started in a directory that has ``god/resume.json`` restores from that
snapshot and continues from the forked round instead of starting fresh.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, Optional

GOD_DIR = "god"
HOLD_POLL_SECONDS = 0.3
POLL_CONCURRENCY = 10
MEMORY_MAX_MESSAGES = 80
MEMORY_MAX_CHARS = 4000

SNAPSHOT_DIR = "snapshot"
RESUME_FILE = "resume.json"

# Commands that change the world; refused once a platform has no rounds left.
MUTATING = {"inject", "whisper", "snapshot"}


def _write_json(path: str, data: dict) -> None:
    """Write atomically so the other process never reads a partial file."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


class GodControl:
    def __init__(self, simulation_dir: str, shutdown_event: Optional[asyncio.Event] = None):
        self.simulation_dir = simulation_dir
        self.dir = os.path.join(simulation_dir, GOD_DIR)
        self.control_path = os.path.join(self.dir, "control.json")
        self.state_path = os.path.join(self.dir, "state.json")
        self.shutdown_event = shutdown_event
        self.platforms: Dict[str, Dict[str, Any]] = {}
        self._steps_taken: Dict[str, int] = {}

        # A new run is a new world: drop commands and pause state left over
        # from a previous run, and archive that run's audit log.
        for name in ("commands", "responses"):
            shutil.rmtree(os.path.join(self.dir, name), ignore_errors=True)
        os.makedirs(self.dir, exist_ok=True)
        audit_path = os.path.join(self.dir, "audit.jsonl")
        # A fork keeps the audit log it inherited from its parent.
        is_fork = os.path.exists(os.path.join(self.dir, RESUME_FILE))
        if os.path.exists(audit_path) and not is_fork:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(audit_path, os.path.join(self.dir, f"audit.{stamp}.jsonl"))
        _write_json(self.control_path, {"paused": False, "step_seq": 0})
        self._write_state()

    # ---------- resuming from a fork snapshot ----------

    def resume_point(self, platform: str) -> Optional[dict]:
        """Snapshot metadata for this platform if this run is a fork, else None."""
        if _read_json(os.path.join(self.dir, RESUME_FILE)) is None:
            return None
        return _read_json(os.path.join(self.dir, SNAPSHOT_DIR, f"{platform}.json"))

    def restore_files(self, platform: str, db_path: str) -> None:
        """Put the snapshot's database and action log in place before the env opens them."""
        snapshot = os.path.join(self.dir, SNAPSHOT_DIR)
        shutil.copyfile(os.path.join(snapshot, f"{platform}.db"), db_path)
        log_dir = os.path.join(self.simulation_dir, platform)
        os.makedirs(log_dir, exist_ok=True)
        shutil.copyfile(
            os.path.join(snapshot, f"{platform}_actions.jsonl"),
            os.path.join(log_dir, "actions.jsonl"),
        )

    def restore_runtime(self, platform: str, db_path: str) -> int:
        """
        Restore agent memories and the platform clock after the env is up.

        Returns the last trace rowid already written to the action log, so
        the loop does not log the shared history a second time.
        """
        info = self.platforms[platform]
        meta = self.resume_point(platform) or {}
        memories = _read_json(os.path.join(self.dir, SNAPSHOT_DIR, f"{platform}_memory.json")) or {}
        for agent_id, agent in info["agent_graph"].get_agents():
            records = memories.get(str(agent_id))
            if records is None:
                continue
            storage = agent.memory._chat_history_block.storage
            storage.clear()
            storage.save(records)

        clock = info["env"].platform.sandbox_clock
        clock.time_step = meta.get("time_step", clock.time_step)
        # Reddit timestamps posts by wall time since the run started; carry
        # the parent's elapsed time over so new posts sort after old ones.
        clock.real_start_time = datetime.fromtimestamp(time.time() - meta.get("elapsed_seconds", 0))

        if meta.get("paused"):
            _write_json(self.control_path, {"paused": True, "step_seq": 0})
        return int(meta.get("last_rowid", 0))

    # ---------- state ----------

    def register(self, platform: str, env, agent_graph) -> None:
        self.platforms[platform] = {
            "env": env, "agent_graph": agent_graph,
            "round": 0, "holding": False, "finished": False,
        }
        os.makedirs(os.path.join(self.dir, "commands", platform), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "responses", platform), exist_ok=True)
        self._steps_taken[platform] = (_read_json(self.control_path) or {}).get("step_seq", 0)
        self._write_state()

    def _write_state(self) -> None:
        _write_json(self.state_path, {
            "updated_at": datetime.now().isoformat(),
            "platforms": {
                name: {"round": p["round"], "holding": p["holding"], "finished": p["finished"]}
                for name, p in self.platforms.items()
            },
        })

    def _set(self, platform: str, **changes) -> None:
        info = self.platforms[platform]
        if any(info[key] != value for key, value in changes.items()):
            info.update(changes)
            self._write_state()

    def _shutting_down(self) -> bool:
        return bool(self.shutdown_event and self.shutdown_event.is_set())

    def _should_hold(self, platform: str) -> bool:
        control = _read_json(self.control_path) or {}
        if not control.get("paused"):
            return False
        step_seq = control.get("step_seq", 0)
        if step_seq > self._steps_taken.get(platform, 0):
            # One "step" lets each platform run exactly one more round.
            self._steps_taken[platform] = step_seq
            return False
        return True

    # ---------- called by the simulation loops ----------

    async def checkpoint(self, platform: str, round_num: int) -> None:
        """Run before a round starts: serve commands, and hold while paused."""
        if platform not in self.platforms:
            return
        self._set(platform, round=round_num)
        await self._drain(platform)
        while self._should_hold(platform) and not self._shutting_down():
            self._set(platform, holding=True)
            await self._drain(platform)
            await asyncio.sleep(HOLD_POLL_SECONDS)
        self._set(platform, holding=False)

    def finish(self, platform: str) -> None:
        if platform in self.platforms:
            self._set(platform, finished=True, holding=False)

    async def serve(self) -> None:
        """Run from the post-simulation wait loop."""
        for platform in list(self.platforms):
            await self._drain(platform)

    # ---------- commands ----------

    async def _drain(self, platform: str) -> None:
        commands_dir = os.path.join(self.dir, "commands", platform)
        try:
            names = sorted(
                (n for n in os.listdir(commands_dir) if n.endswith(".json")),
                key=lambda n: os.path.getmtime(os.path.join(commands_dir, n)),
            )
        except OSError:
            return
        for name in names:
            path = os.path.join(commands_dir, name)
            command = _read_json(path)
            if command is None:
                continue  # still being written; pick it up next time
            command_id = command.get("command_id", name[:-5])
            try:
                result = await self._execute(platform, command)
                response = {"command_id": command_id, "status": "completed", "result": result}
            except Exception as error:  # report every failure to the operator
                response = {"command_id": command_id, "status": "failed", "error": str(error)}
            response["round"] = self.platforms[platform]["round"]
            response["timestamp"] = datetime.now().isoformat()
            _write_json(os.path.join(self.dir, "responses", platform, f"{command_id}.json"), response)
            try:
                os.remove(path)
            except OSError:
                pass

    async def _execute(self, platform: str, command: dict) -> dict:
        info = self.platforms[platform]
        kind = command.get("command_type")
        args = command.get("args", {})
        if kind in MUTATING and info["finished"]:
            raise RuntimeError(
                f"{platform} has no rounds left, so '{kind}' could not affect anything"
            )
        handler = getattr(self, f"_cmd_{kind}", None)
        if handler is None:
            raise ValueError(f"unknown god command: {kind}")
        return await handler(platform, info, args)

    def _agent(self, info: dict, agent_id: int):
        try:
            return info["agent_graph"].get_agent(int(agent_id))
        except Exception:
            raise ValueError(f"no agent with id {agent_id} on this platform") from None

    async def _cmd_inject(self, platform, info, args) -> dict:
        from oasis import ActionType
        agent = self._agent(info, args["agent_id"])
        result = await agent.perform_action_by_data(ActionType.CREATE_POST, content=args["content"])
        if not (isinstance(result, dict) and result.get("success")):
            raise RuntimeError(f"platform refused the post: {result}")
        return {"post_id": result.get("post_id"), "agent_id": int(args["agent_id"])}

    async def _cmd_whisper(self, platform, info, args) -> dict:
        from camel.messages import BaseMessage
        from camel.types import OpenAIBackendRole
        agent = self._agent(info, args["agent_id"])
        agent.update_memory(
            message=BaseMessage.make_user_message(
                role_name="User",
                content=f"Private information only you know: {args['text']}",
            ),
            role=OpenAIBackendRole.USER,
        )
        return {"agent_id": int(args["agent_id"])}

    async def _interview(self, info, agent_id: int, prompt: str) -> str:
        agent = self._agent(info, agent_id)
        # perform_interview does not write to the agent's memory
        # (SocialAgent.interview_record is False), so the simulation is unaffected.
        result = await agent.perform_interview(prompt)
        return result.get("content") or ""

    async def _cmd_interview(self, platform, info, args) -> dict:
        answer = await self._interview(info, args["agent_id"], args["prompt"])
        return {"agent_id": int(args["agent_id"]), "response": answer}

    async def _cmd_poll(self, platform, info, args) -> dict:
        gate = asyncio.Semaphore(POLL_CONCURRENCY)

        async def ask(agent_id):
            async with gate:
                try:
                    return {"agent_id": int(agent_id),
                            "response": await self._interview(info, agent_id, args["prompt"])}
                except Exception as error:
                    return {"agent_id": int(agent_id), "error": str(error)}

        answers = await asyncio.gather(*(ask(agent_id) for agent_id in args["agent_ids"]))
        return {"answers": list(answers)}

    async def _cmd_snapshot(self, platform, info, args) -> dict:
        """Write this platform's world into ``args['dest_dir']`` for a fork."""
        dest = os.path.join(args["dest_dir"], GOD_DIR, SNAPSHOT_DIR)
        os.makedirs(dest, exist_ok=True)

        db_path = os.path.join(self.simulation_dir, f"{platform}_simulation.db")
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(os.path.join(dest, f"{platform}.db"))
        try:
            source.backup(target)  # consistent copy even with the platform's connection open
            last_rowid = source.execute("SELECT COALESCE(MAX(rowid), 0) FROM trace").fetchone()[0]
        finally:
            target.close()
            source.close()

        log_path = os.path.join(self.simulation_dir, platform, "actions.jsonl")
        log_copy = os.path.join(dest, f"{platform}_actions.jsonl")
        if os.path.exists(log_path):
            shutil.copyfile(log_path, log_copy)
        else:
            open(log_copy, "w").close()

        memories = {
            str(agent_id): agent.memory._chat_history_block.storage.load()
            for agent_id, agent in info["agent_graph"].get_agents()
        }
        with open(os.path.join(dest, f"{platform}_memory.json"), "w", encoding="utf-8") as handle:
            json.dump(memories, handle, ensure_ascii=False, default=str)

        clock = info["env"].platform.sandbox_clock
        control = _read_json(self.control_path) or {}
        meta = {
            "platform": platform,
            # The next round this platform would run; the fork starts there.
            "round": info["round"],
            "last_rowid": last_rowid,
            "time_step": clock.time_step,
            "elapsed_seconds": (datetime.now() - clock.real_start_time).total_seconds(),
            "paused": bool(control.get("paused")),
            "agents": len(memories),
        }
        _write_json(os.path.join(dest, f"{platform}.json"), meta)
        return meta

    async def _cmd_memory(self, platform, info, args) -> dict:
        agent = self._agent(info, args["agent_id"])
        messages, _tokens = agent.memory.get_context()
        out = []
        for message in messages[-MEMORY_MAX_MESSAGES:]:
            content = message.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            if message.get("tool_calls"):
                content = (content or "") + " " + json.dumps(
                    message["tool_calls"], ensure_ascii=False, default=str)
            out.append({"role": message.get("role", ""), "content": (content or "")[:MEMORY_MAX_CHARS]})
        return {"agent_id": int(args["agent_id"]), "total": len(messages), "messages": out}
