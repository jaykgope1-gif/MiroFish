import json
from types import SimpleNamespace

import pytest

from app.config import Config
from app.utils import claude
from app.utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text


def _response(content, stop="end_turn", model="claude-haiku-5-5", usage=None):
    return SimpleNamespace(
        id="msg_1", model=model, stop_reason=stop, stop_details=None, content=content,
        usage=SimpleNamespace(**(usage or {"input_tokens": 1000, "output_tokens": 200,
                                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})),
    )


def _text(text):
    return SimpleNamespace(type="text", text=text)


class FakeClient:
    """Records each request; answers with the queued responses."""

    def __init__(self, *responses):
        self.requests, self.responses = [], list(responses)
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append(params)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(claude, "_ledgers", {})
    monkeypatch.setenv("MIROFISH_RUN_ID", "backend")
    return tmp_path


def test_messages_convert_system_tools_and_merge_roles():
    system, messages = claude.to_anthropic_messages([
        {"role": "system", "content": "You are Maya."},
        {"role": "user", "content": "Observe the feed."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "like_post", "arguments": '{"post_id": 3}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"success": true}'},
        {"role": "user", "content": "Anything else?"},
    ])

    assert system == "You are Maya."
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == [{"type": "tool_use", "id": "call_1", "name": "like_post", "input": {"post_id": 3}}]
    # tool_result first, then the following user text, in one user turn
    assert [b["type"] for b in messages[2]["content"]] == ["tool_result", "text"]
    assert messages[2]["content"][0]["tool_use_id"] == "call_1"


def test_orphaned_tool_halves_become_text():
    # History trimmed to the context window: a result without its call, and a call without its result.
    _, messages = claude.to_anthropic_messages([
        {"role": "tool", "tool_call_id": "gone", "content": "old result"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_9", "type": "function", "function": {"name": "follow", "arguments": '{"followee_id": 2}'}}]},
    ])

    flat = [b for m in messages for b in m["content"]]
    assert not any(b["type"] in ("tool_use", "tool_result") for b in flat)
    assert messages[0]["role"] == "user" and messages[-1]["role"] == "user"
    assert "[tool result: old result]" in json.dumps(flat)
    assert "used tool follow" in json.dumps(flat)


def test_tools_convert_to_input_schema():
    tools = claude.to_anthropic_tools([{"type": "function", "function": {
        "name": "create_post", "description": "Post", "parameters": {"type": "object", "properties": {"content": {"type": "string"}}}}}])
    assert tools == [{"name": "create_post", "description": "Post",
                      "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}}}]


def test_tiers_route_to_their_models_without_sampling_parameters(monkeypatch):
    monkeypatch.setattr(Config, "CLAUDE_MODELS", {"report": "claude-sonnet-5-5", "fast": "claude-haiku-5-5",
                                                  "simulation": "claude-haiku-5-5"})
    fast = FakeClient(_response([_text('{"bio": "x"}')]))
    report = FakeClient(_response([_text("Summary")], model="claude-sonnet-5-5"))

    create_chat_completion(claude.ClaudeChat("fast", client=fast), model="ignored",
                           messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                           temperature=0.7, response_format={"type": "json_object"})
    create_chat_completion(claude.ClaudeChat("report", client=report), model="ignored",
                           messages=[{"role": "user", "content": "u"}], max_tokens=4096)

    sent = fast.requests[0]
    assert sent["model"] == "claude-haiku-5-5"
    assert "temperature" not in sent and "top_p" not in sent
    assert sent["max_tokens"] >= claude.MIN_MAX_TOKENS
    assert "JSON object" in sent["system"]
    assert sent["output_config"] == {"effort": Config.claude_effort("fast")}
    assert "betas" not in sent  # Haiku has no server-side fallback

    sent = report.requests[0]
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["betas"] == [claude.FALLBACK_BETA] and sent["fallbacks"] == "default"
    assert "thinking" not in sent  # Sonnet 5.5 rejects disabled thinking


def test_response_maps_to_chat_completion_shape():
    chat = claude.ClaudeChat("fast", client=FakeClient(_response([_text("partial")], stop="max_tokens")))
    result = create_chat_completion(chat, model="x", messages=[{"role": "user", "content": "u"}])

    assert extract_chat_completion_text(result) == "partial"
    assert result.choices[0].finish_reason == "length"


def test_ledger_costs_calls_and_keeps_per_run_totals(isolated_ledger, monkeypatch):
    (isolated_ledger / "sim_a").mkdir()
    monkeypatch.setattr(Config, "USD_ZAR_RATE", 20.0)
    chat = claude.ClaudeChat("fast", run="sim_a", client=FakeClient(
        _response([_text("{}")], usage={"input_tokens": 1_000_000, "output_tokens": 100_000,
                                        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})))

    chat.chat_completion([{"role": "user", "content": "u"}])

    # Haiku 5.5 over 100K prompt tokens: $0.50/M in, $2.50/M out
    cost = claude.run_cost("sim_a")
    assert cost["usd"] == pytest.approx(0.75)
    assert cost["zar"] == pytest.approx(15.0)
    assert cost["calls"] == 1
    lines = (isolated_ledger / "sim_a" / "llm_usage.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["model"] == "claude-haiku-5-5"


def test_short_prompts_use_base_haiku_price():
    usage = {"input_tokens": 10_000, "output_tokens": 1_000, "cache_read_input_tokens": 50_000}
    assert claude.usd_cost("claude-haiku-5-5", usage) == pytest.approx((10_000 * 0.10 + 1_000 * 0.50 + 50_000 * 0.01) / 1e6)


def test_camel_backend_returns_tool_calls_as_chat_completion(monkeypatch):
    camel_mod = pytest.importorskip("app.utils.claude_camel")
    backend = camel_mod.ClaudeCamelBackend(model="claude-haiku-5-5", context_tokens=8000)
    fake = FakeClient(_response([
        _text("Liking this."),
        SimpleNamespace(type="tool_use", id="toolu_1", name="like_post", input={"post_id": 7}),
    ], stop="tool_use"))
    backend._sync_client = fake

    result = backend._run(
        [{"role": "system", "content": "You are Ann. Stance: opposing."}, {"role": "user", "content": "feed"}],
        tools=[{"type": "function", "function": {"name": "like_post", "parameters": {
            "type": "object", "properties": {"post_id": {"type": "integer"}}}}}],
    )

    sent = fake.requests[0]
    assert sent["tools"][0]["name"] == "like_post"
    assert sent["thinking"] == {"type": "disabled"} or Config.CLAUDE_SIMULATION_THINKING != "disabled"
    choice = result.choices[0]
    assert choice.finish_reason == "tool_calls"
    assert choice.message.tool_calls[0].function.name == "like_post"
    assert json.loads(choice.message.tool_calls[0].function.arguments) == {"post_id": 7}
    assert backend.token_limit == 8000
