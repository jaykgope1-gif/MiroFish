"""
Claude (Anthropic) support for MiroFish.

MiroFish was written against OpenAI-style chat messages. With
``LLM_PROVIDER=anthropic`` every LLM call goes through the Anthropic SDK in
this module instead:

* ``ClaudeChat`` - one request at a time, used by ``LLMClient`` (ontology,
  report agent, graph search) and by the profile and config generators.
* ``claude_camel.ClaudeCamelBackend`` - the OASIS social agents.
* ``UsageLedger`` - records the tokens and cost of every call and enforces
  the per-run budget.

Model tiers (each overridable in .env):

    report      CLAUDE_REPORT_MODEL      claude-sonnet-5-5   ontology, report agent, graph search
    fast        CLAUDE_FAST_MODEL        claude-haiku-5-5    agent profiles, simulation config
    simulation  CLAUDE_SIMULATION_MODEL  claude-haiku-5-5    every OASIS agent action and interview

Knowledge-graph extraction itself is done by Zep Cloud with its own model,
not by MiroFish, so it is not routed here.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config

logger = logging.getLogger("mirofish.claude")

# Thinking counts toward max_tokens, so callers' small caps (often 4096) would
# truncate answers. Requests use at least this; only generated tokens are billed.
MIN_MAX_TOKENS = 16000

# Server-side refusal fallback for the models that support it: on a policy
# decline the API re-runs the request on a fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODEL_PREFIXES = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5")

JSON_INSTRUCTION = (
    "\n\nReply with exactly one JSON object and nothing else: "
    "no explanation and no Markdown code fence."
)

STOP_TO_FINISH = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "pause_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
}

# USD per million tokens: input, output, cache write (5 min), cache read.
# Haiku 5.5 doubles its rates for prompts over 100K tokens.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
}
HAIKU_LONG_PROMPT = 100_000


def usd_cost(model: str, usage: Any) -> float:
    """Cost of one response in US dollars, from its usage block."""
    name = next((key for key in PRICES if (model or "").startswith(key)), None)
    if name is None:
        logger.warning("No price for model %s; costing it as Sonnet", model)
        name = "claude-sonnet-5-5"
    price_in, price_out, price_write, price_read = PRICES[name]
    fresh = _int(usage, "input_tokens")
    written = _int(usage, "cache_creation_input_tokens")
    read = _int(usage, "cache_read_input_tokens")
    out = _int(usage, "output_tokens")
    if name == "claude-haiku-5-5" and fresh + written + read > HAIKU_LONG_PROMPT:
        price_in, price_out, price_write, price_read = (p * 5 for p in PRICES[name])
    return (fresh * price_in + out * price_out + written * price_write + read * price_read) / 1_000_000


def _int(usage: Any, key: str) -> int:
    value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
    return int(value or 0)


# ---------------------------------------------------------------- ledger

@dataclass
class _Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    usd: float = 0.0
    by_model: Dict[str, float] = field(default_factory=dict)


class UsageLedger:
    """
    Records every Claude call and keeps running cost totals per run.

    Each call is appended to a JSON-lines log. When the run is a simulation
    (``run`` names a simulation directory), totals are also kept in
    ``<sim_dir>/llm_cost.<component>.json`` so the God View can show the
    cost of the run and the simulation can stop at the budget.
    """

    def __init__(self, run: str, component: str, log_path: str):
        self.run = run
        self.component = component
        self.log_path = log_path
        self.usd_zar = Config.USD_ZAR_RATE
        self.budget_zar = Config.RUN_BUDGET_ZAR
        self._lock = threading.Lock()
        self._totals = _Totals()
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, run)
        self.summary_path = (
            os.path.join(sim_dir, f"llm_cost.{component}.json") if os.path.isdir(sim_dir) else None
        )
        previous = _read_json(self.summary_path) if self.summary_path else None
        if previous:  # keep accumulating across restarts of this component
            self._totals = _Totals(**{k: previous[k] for k in _Totals.__dataclass_fields__ if k in previous})

    def record(self, model: str, usage: Any, tier: str) -> float:
        cost = usd_cost(model, usage)
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "run": self.run,
            "component": self.component,
            "tier": tier,
            "model": model,
            "input_tokens": _int(usage, "input_tokens"),
            "output_tokens": _int(usage, "output_tokens"),
            "cache_read_tokens": _int(usage, "cache_read_input_tokens"),
            "cache_write_tokens": _int(usage, "cache_creation_input_tokens"),
            "usd": round(cost, 6),
        }
        with self._lock:
            t = self._totals
            t.calls += 1
            t.input_tokens += entry["input_tokens"]
            t.output_tokens += entry["output_tokens"]
            t.cache_read_tokens += entry["cache_read_tokens"]
            t.cache_write_tokens += entry["cache_write_tokens"]
            t.usd += cost
            t.by_model[model] = t.by_model.get(model, 0.0) + cost
            try:
                os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
                with open(self.log_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry) + "\n")
                if self.summary_path:
                    _write_json(self.summary_path, self.summary())
            except OSError as error:  # cost logging must never break a run
                logger.warning("Could not write LLM usage log: %s", error)
        return cost

    def summary(self) -> dict:
        t = self._totals
        return {
            "run": self.run,
            "component": self.component,
            "calls": t.calls,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "cache_read_tokens": t.cache_read_tokens,
            "cache_write_tokens": t.cache_write_tokens,
            "usd": round(t.usd, 6),
            "zar": round(t.usd * self.usd_zar, 4),
            "by_model": {k: round(v, 6) for k, v in t.by_model.items()},
            "usd_zar_rate": self.usd_zar,
            "budget_zar": self.budget_zar,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }


def run_cost(simulation_id: str) -> Optional[dict]:
    """Total cost of one simulation run across all components, or None if nothing was recorded."""
    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    try:
        names = [n for n in os.listdir(sim_dir) if n.startswith("llm_cost.") and n.endswith(".json")]
    except OSError:
        return None
    parts = [p for p in (_read_json(os.path.join(sim_dir, n)) for n in sorted(names)) if p]
    if not parts:
        return None
    usd = sum(p.get("usd", 0.0) for p in parts)
    rate = parts[0].get("usd_zar_rate", Config.USD_ZAR_RATE)
    return {
        "usd": round(usd, 4),
        "zar": round(usd * rate, 2),
        "budget_zar": Config.RUN_BUDGET_ZAR,
        "calls": sum(p.get("calls", 0) for p in parts),
        "by_component": {p["component"]: round(p.get("usd", 0.0) * rate, 2) for p in parts},
    }


_ledgers: Dict[Tuple[str, str], UsageLedger] = {}
_ledgers_lock = threading.Lock()


def ledger(run: Optional[str] = None, component: Optional[str] = None) -> UsageLedger:
    """
    The ledger for a run. ``run`` is a simulation id when known; it defaults
    to MIROFISH_RUN_ID (set for simulation processes) or "backend".
    """
    run = run or os.environ.get("MIROFISH_RUN_ID") or "backend"
    component = component or os.environ.get("MIROFISH_RUN_COMPONENT") or "backend"
    key = (run, component)
    with _ledgers_lock:
        if key not in _ledgers:
            sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, run)
            default_log = (
                os.path.join(sim_dir, "llm_usage.jsonl") if os.path.isdir(sim_dir)
                else os.path.join(os.path.dirname(__file__), "../../logs/llm_usage.jsonl")
            )
            _ledgers[key] = UsageLedger(run, component, os.path.abspath(default_log))
        return _ledgers[key]


def _read_json(path: Optional[str]) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, TypeError, json.JSONDecodeError):
        return None


def _write_json(path: str, data: dict) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)


# ------------------------------------------------- message conversion

def _text(content: Any) -> str:
    """Plain text from an OpenAI-style content field (string or list of parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)


def _append(out: List[dict], role: str, blocks: List[dict]) -> None:
    if out and out[-1]["role"] == role:
        out[-1]["content"].extend(blocks)
    else:
        out.append({"role": role, "content": list(blocks)})


def _tool_use_as_text(block: dict) -> dict:
    return {"type": "text", "text": f"[used tool {block['name']} with {json.dumps(block['input'], ensure_ascii=False)}]"}


def _tool_result_as_text(block: dict) -> dict:
    content = block.get("content")
    return {"type": "text", "text": f"[tool result: {content if isinstance(content, str) else json.dumps(content)}]"}


def _repair_tool_pairs(messages: List[dict]) -> List[dict]:
    """
    Make tool calls and results pair up as the Messages API requires.

    Chat histories trimmed to a context window can keep a tool call without
    its result, or a result without its call. Those halves are turned into
    plain text so the request stays valid.
    """
    for index, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        following = messages[index + 1] if index + 1 < len(messages) else None
        answered = {
            b.get("tool_use_id") for b in (following["content"] if following and following["role"] == "user" else [])
            if b.get("type") == "tool_result"
        }
        message["content"] = [
            b if b.get("type") != "tool_use" or b["id"] in answered else _tool_use_as_text(b)
            for b in message["content"]
        ]
    for index, message in enumerate(messages):
        if message["role"] != "user":
            continue
        previous = messages[index - 1] if index > 0 else None
        called = {
            b["id"] for b in (previous["content"] if previous and previous["role"] == "assistant" else [])
            if b.get("type") == "tool_use"
        }
        blocks = [
            b if b.get("type") != "tool_result" or b.get("tool_use_id") in called else _tool_result_as_text(b)
            for b in message["content"]
        ]
        # Tool results must come before any other content in their message.
        message["content"] = (
            [b for b in blocks if b.get("type") == "tool_result"]
            + [b for b in blocks if b.get("type") != "tool_result"]
        )
    cleaned = [m for m in messages if m["content"]]
    # Merging again: removing empty messages can leave two of one role in a row.
    merged: List[dict] = []
    for message in cleaned:
        _append(merged, message["role"], message["content"])
    return merged


def to_anthropic_messages(messages: List[Dict[str, Any]]) -> Tuple[str, List[dict]]:
    """
    Convert OpenAI-style chat messages to (system, messages) for the Messages API.

    System messages become the top-level system prompt; assistant tool calls
    become ``tool_use`` blocks and ``tool`` messages become ``tool_result``
    blocks; consecutive messages of one role are merged.
    """
    system_parts: List[str] = []
    out: List[dict] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role in ("system", "developer"):
            text = _text(content).strip()
            if text:
                system_parts.append(text)
        elif role in ("tool", "function"):
            _append(out, "user", [{
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id") or "",
                "content": _text(content) or "(no output)",
            }])
        elif role == "assistant":
            blocks = []
            text = _text(content).strip()
            if text:
                blocks.append({"type": "text", "text": text})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {"raw": function.get("arguments")}
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
                blocks.append({
                    "type": "tool_use",
                    "id": call.get("id") or f"toolu_{uuid.uuid4().hex[:20]}",
                    "name": function.get("name") or "unknown",
                    "input": arguments,
                })
            if blocks:
                _append(out, "assistant", blocks)
        else:
            text = _text(content).strip()
            if text:
                _append(out, "user", [{"type": "text", "text": text}])

    out = _repair_tool_pairs(out)
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "Begin."}]})
    if out[-1]["role"] != "user":
        # No assistant prefill on current models: the request must end with a user turn.
        out.append({"role": "user", "content": [{"type": "text", "text": "Continue."}]})
    return "\n\n".join(system_parts), out


def to_anthropic_tools(tools: Optional[List[Dict[str, Any]]]) -> List[dict]:
    """OpenAI function-tool schemas to Messages API tool definitions."""
    converted = []
    for tool in tools or []:
        function = tool.get("function", tool)
        schema = function.get("parameters") or {"type": "object", "properties": {}}
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {"value": schema}}
        converted.append({
            "name": function["name"],
            "description": function.get("description") or "",
            "input_schema": schema,
        })
    return converted


# ----------------------------------------------------- requests

def request_params(
    tier: str,
    system: str,
    messages: List[dict],
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    tools: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Messages API parameters for one request on a tier. Sampling parameters are never sent."""
    model = Config.claude_model(tier)
    params: Dict[str, Any] = {
        "model": model,
        "max_tokens": max(max_tokens or 0, MIN_MAX_TOKENS),
        "messages": messages,
        # Caches the shared prefix (tools + system + earlier turns) between calls.
        "cache_control": {"type": "ephemeral"},
    }
    system = (system or "") + (JSON_INSTRUCTION if json_mode else "")
    if system.strip():
        params["system"] = system
    effort = Config.claude_effort(tier)
    if effort:
        params["output_config"] = {"effort": effort}
    if Config.claude_thinking(tier) == "disabled":
        params["thinking"] = {"type": "disabled"}
    if tools:
        params["tools"] = tools
    return params


def uses_fallback(model: str) -> bool:
    return model.startswith(FALLBACK_MODEL_PREFIXES)


def response_text(response: Any) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()


def check_refusal(response: Any) -> None:
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        logger.warning(
            "Claude declined a request (category=%s): %s",
            getattr(details, "category", None), getattr(details, "explanation", None),
        )


def make_client(asynchronous: bool = False):
    import anthropic

    kwargs = {"api_key": Config.ANTHROPIC_API_KEY or None, "max_retries": 4}
    return anthropic.AsyncAnthropic(**kwargs) if asynchronous else anthropic.Anthropic(**kwargs)


def send(client: Any, params: Dict[str, Any]):
    """One request, with the server-side refusal fallback where the model supports it."""
    if uses_fallback(params["model"]):
        return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
    return client.messages.create(**params)


async def send_async(client: Any, params: Dict[str, Any]):
    if uses_fallback(params["model"]):
        return await client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
    return await client.messages.create(**params)


class ClaudeChat:
    """
    A chat client for one tier, used where MiroFish expects an OpenAI client.

    ``create_chat_completion`` (utils/openai_chat_compat.py) sends requests
    for a ClaudeChat here and gets back an object shaped like a Chat
    Completions response (``choices[0].message.content`` and
    ``finish_reason``), so callers did not have to change.
    """

    def __init__(self, tier: str, run: Optional[str] = None, client: Any = None):
        self.tier = tier
        self.model = Config.claude_model(tier)
        self.run = run
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = make_client()
        return self._client

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> SimpleNamespace:
        system, converted = to_anthropic_messages(messages)
        params = request_params(self.tier, system, converted, max_tokens, json_mode)
        started = time.monotonic()
        response = send(self.client, params)
        check_refusal(response)
        cost = ledger(self.run).record(response.model, response.usage, self.tier)
        logger.debug("claude %s %.1fs $%.5f", response.model, time.monotonic() - started, cost)
        finish = STOP_TO_FINISH.get(response.stop_reason, "stop")
        return SimpleNamespace(
            model=response.model,
            usage=response.usage,
            choices=[SimpleNamespace(
                index=0,
                finish_reason=finish,
                message=SimpleNamespace(role="assistant", content=response_text(response), tool_calls=None),
            )],
        )


def chat_client(tier: str, run: Optional[str] = None) -> Tuple[Any, str]:
    """
    The client and model name a service should use for a tier:
    a ClaudeChat when LLM_PROVIDER=anthropic, else the configured OpenAI client.
    """
    if Config.LLM_PROVIDER == "anthropic":
        chat = ClaudeChat(tier, run=run)
        return chat, chat.model
    from openai import OpenAI

    return OpenAI(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL), Config.LLM_MODEL_NAME
