import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from god_control import GodControl  # noqa: E402

from app.services import god_branches, god_control  # noqa: E402


def _set_control(control: GodControl, **values):
    with open(control.control_path, "w", encoding="utf-8") as handle:
        json.dump(values, handle)


def _state(control: GodControl, platform: str) -> dict:
    with open(control.state_path, encoding="utf-8") as handle:
        return json.load(handle)["platforms"][platform]


def test_checkpoint_passes_straight_through_when_not_paused(tmp_path):
    control = GodControl(str(tmp_path))
    control.register("reddit", env=None, agent_graph=None)

    asyncio.run(asyncio.wait_for(control.checkpoint("reddit", 3), timeout=2))

    assert _state(control, "reddit") == {"round": 3, "holding": False, "finished": False}


def test_checkpoint_holds_while_paused_and_step_releases_one_round(tmp_path):
    control = GodControl(str(tmp_path))
    control.register("reddit", env=None, agent_graph=None)

    async def scenario():
        _set_control(control, paused=True, step_seq=0)
        held = asyncio.create_task(control.checkpoint("reddit", 4))
        await asyncio.sleep(0.5)
        assert not held.done()
        assert _state(control, "reddit")["holding"] is True

        _set_control(control, paused=True, step_seq=1)  # operator typed "step"
        await asyncio.wait_for(held, timeout=3)

        # Still paused: the next round holds again until resumed.
        held = asyncio.create_task(control.checkpoint("reddit", 5))
        await asyncio.sleep(0.5)
        assert not held.done()
        _set_control(control, paused=False, step_seq=1)
        await asyncio.wait_for(held, timeout=3)
        assert _state(control, "reddit") == {"round": 5, "holding": False, "finished": False}

    asyncio.run(scenario())


def test_commands_are_answered_at_the_checkpoint_and_failures_reported(tmp_path):
    control = GodControl(str(tmp_path))
    control.register("twitter", env=None, agent_graph=None)
    commands = tmp_path / "god" / "commands" / "twitter"
    (commands / "c1.json").write_text(json.dumps({"command_id": "c1", "command_type": "nonsense", "args": {}}))

    asyncio.run(control.checkpoint("twitter", 2))

    response = json.loads((tmp_path / "god" / "responses" / "twitter" / "c1.json").read_text())
    assert response["status"] == "failed"
    assert "unknown god command" in response["error"]
    assert response["round"] == 2
    assert not (commands / "c1.json").exists()


def test_world_changing_commands_are_refused_once_rounds_are_over(tmp_path):
    control = GodControl(str(tmp_path))
    control.register("reddit", env=None, agent_graph=None)
    control.finish("reddit")
    commands = tmp_path / "god" / "commands" / "reddit"
    (commands / "c2.json").write_text(json.dumps(
        {"command_id": "c2", "command_type": "inject", "args": {"agent_id": 0, "content": "x"}}))

    asyncio.run(control.serve())

    response = json.loads((tmp_path / "god" / "responses" / "reddit" / "c2.json").read_text())
    assert response["status"] == "failed"
    assert "no rounds left" in response["error"]


def test_new_run_archives_audit_log_but_a_fork_keeps_it(tmp_path):
    fresh, fork = tmp_path / "fresh", tmp_path / "fork"
    for directory in (fresh, fork):
        (directory / "god").mkdir(parents=True)
        (directory / "god" / "audit.jsonl").write_text('{"command": "pause"}\n')
    (fork / "god" / "resume.json").write_text("{}")

    GodControl(str(fresh))
    GodControl(str(fork))

    assert not (fresh / "god" / "audit.jsonl").exists()
    assert any(name.startswith("audit.") for name in os.listdir(fresh / "god"))
    assert (fork / "god" / "audit.jsonl").exists()


# ---------- branches ----------

def _make_sim(base, sim_id, actions, branch=None, audit=()):
    directory = base / sim_id
    (directory / "reddit").mkdir(parents=True)
    (directory / "god").mkdir()
    (directory / "state.json").write_text("{}")
    (directory / "simulation_config.json").write_text(json.dumps({
        "agent_configs": [
            {"agent_id": 0, "entity_name": "Ann", "stance": "supportive"},
            {"agent_id": 1, "entity_name": "Bob", "stance": "opposing"},
        ],
        "event_config": {"hot_topics": ["strike"]},
    }))
    lines = []
    for round_num, agent_id, text in actions:
        lines.append({"round": round_num, "agent_id": agent_id, "action_type": "CREATE_POST",
                      "action_args": {"content": text}})
    last = max((a[0] for a in actions), default=0)
    lines += [{"round": r, "event_type": "round_end"} for r in range(last + 1)]
    (directory / "reddit" / "actions.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))
    (directory / "god" / "audit.jsonl").write_text("".join(json.dumps(e) + "\n" for e in audit))
    if branch:
        (directory / "branch.json").write_text(json.dumps(branch))


@pytest.fixture
def family(tmp_path, monkeypatch):
    monkeypatch.setattr(god_control.Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    shared = [(1, 0, "hello"), (2, 1, "hello")]
    _make_sim(tmp_path, "sim_x", shared + [(3, 0, "calm"), (4, 0, "calm")])
    _make_sim(
        tmp_path, "sim_x__alt", shared + [(3, 1, "strike now"), (3, 1, "strike"), (4, 1, "strike")],
        branch={"name": "alt", "root": "sim_x", "parent": "sim_x", "fork_round": 3, "created_at": "1"},
        audit=[
            {"round": 2, "command": "pause", "ok": True, "summary": "before the fork"},
            {"round": 3, "command": "inject", "ok": True, "summary": "posted"},
            {"round": 3, "command": "whisper", "ok": False, "summary": "failed"},
        ],
    )
    _make_sim(
        tmp_path, "sim_x__deep", shared,
        branch={"name": "deep", "root": "sim_x", "parent": "sim_x__alt", "fork_round": 4, "created_at": "2"},
    )
    return tmp_path


def test_branch_names_resolve_within_the_family(family):
    assert [b["name"] for b in god_branches.list_branches("sim_x__alt")] == ["base", "alt", "deep"]
    assert god_branches.resolve("sim_x", "base") == "sim_x"
    assert god_branches.resolve("sim_x", "alt") == "sim_x__alt"
    with pytest.raises(ValueError):
        god_branches.resolve("sim_x", "nope")


def test_divergence_round_follows_the_fork_tree(family):
    assert god_branches.divergence_round("sim_x", "sim_x__alt") == 3
    assert god_branches.divergence_round("sim_x__alt", "sim_x__deep") == 4
    # deep left base's timeline when its ancestor alt did
    assert god_branches.divergence_round("sim_x", "sim_x__deep") == 3
    with pytest.raises(ValueError):
        god_branches.divergence_round("sim_x", "sim_x")


def test_diff_counts_only_rounds_after_the_fork(family):
    result = god_branches.diff("sim_x", "sim_x__alt")

    assert (result["diverged_at"], result["compared_through"]) == (3, 4)
    assert result["a"]["totals"] == {"actions": 2, "stance": {"supportive": 2, "opposing": 0, "neutral": 0, "observer": 0}}
    assert result["b"]["totals"] == {"actions": 3, "stance": {"supportive": 0, "opposing": 3, "neutral": 0, "observer": 0}}
    assert [(r["round"], r["a"]["total"], r["b"]["total"]) for r in result["rounds"]] == [(3, 1, 2), (4, 1, 1)]
    assert result["b"]["by_topic"] == {"strike": 3}
    assert result["a"]["by_topic"] == {}
    # only successful interventions from the fork round on
    assert [(e["round"], e["command"]) for e in result["b"]["interventions"]] == [(3, "inject")]
    assert {(row["name"], row["a"], row["b"]) for row in result["agents"]} == {("Ann", 2, 0), ("Bob", 0, 3)}
