"""
Claude backend for the OASIS social agents (camel-ai).

OASIS agents are camel-ai ChatAgents, which speak OpenAI Chat Completions:
they send OpenAI-format messages and tool schemas and expect a
``ChatCompletion`` back. This backend converts each request to the
Messages API, sends it with the Anthropic SDK, and converts the reply
(text and ``tool_use`` blocks) back into a ``ChatCompletion``.

camel-ai's own AnthropicModel is not used because it calls Claude through
the OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Type

from camel.models.base_model import BaseModelBackend
from camel.types import ChatCompletion, ModelType
from camel.utils import BaseTokenCounter, OpenAITokenCounter
from pydantic import BaseModel

from ..config import Config
from . import claude

TIER = "simulation"


class ClaudeCamelBackend(BaseModelBackend):
    """A camel-ai model backend that runs on Claude through the Anthropic SDK."""

    def __init__(self, model: Optional[str] = None, context_tokens: Optional[int] = None):
        super().__init__(model_type=model or Config.claude_model(TIER), model_config_dict={})
        self._context_tokens = context_tokens or Config.CLAUDE_SIMULATION_CONTEXT_TOKENS
        self._sync_client = None
        self._async_client = None

    @property
    def token_counter(self) -> BaseTokenCounter:
        # camel uses this only to trim agent memory to token_limit, so an
        # approximate count is enough; the bill uses the API's own usage.
        if self._token_counter is None:
            self._token_counter = OpenAITokenCounter(ModelType.GPT_4O_MINI)
        return self._token_counter

    @property
    def token_limit(self) -> int:
        """History an agent sees per call. Lower is cheaper."""
        return self._context_tokens

    @property
    def stream(self) -> bool:
        return False

    def check_model_config(self) -> None:
        """Sampling settings from camel's config are ignored: current Claude models reject them."""

    # ---------------------------------------------------------------- calls

    def _params(self, messages, response_format, tools) -> Dict[str, Any]:
        system, converted = claude.to_anthropic_messages(messages)
        if response_format is not None:
            schema = json.dumps(response_format.model_json_schema(), ensure_ascii=False)
            system += f"\n\nReply with one JSON object matching this schema: {schema}"
        return claude.request_params(
            TIER, system, converted,
            max_tokens=4096,
            json_mode=False,
            tools=claude.to_anthropic_tools(tools) or None,
        )

    def _run(
        self,
        messages: List[Dict[str, Any]],
        response_format: Optional[Type[BaseModel]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatCompletion:
        if self._sync_client is None:
            self._sync_client = claude.make_client()
        response = claude.send(self._sync_client, self._params(messages, response_format, tools))
        return self._completion(response)

    async def _arun(
        self,
        messages: List[Dict[str, Any]],
        response_format: Optional[Type[BaseModel]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatCompletion:
        if self._async_client is None:
            self._async_client = claude.make_client(asynchronous=True)
        response = await claude.send_async(self._async_client, self._params(messages, response_format, tools))
        return self._completion(response)

    def _completion(self, response: Any) -> ChatCompletion:
        claude.check_refusal(response)
        claude.ledger().record(response.model, response.usage, TIER)

        tool_calls = [
            {
                "id": block.id,
                "type": "function",
                "function": {"name": block.name, "arguments": json.dumps(block.input, ensure_ascii=False)},
            }
            for block in response.content
            if getattr(block, "type", None) == "tool_use"
        ]
        text = claude.response_text(response)
        prompt_tokens = (
            (response.usage.input_tokens or 0)
            + (getattr(response.usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(response.usage, "cache_creation_input_tokens", 0) or 0)
        )
        return ChatCompletion.model_validate({
            "id": response.id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response.model,
            "choices": [{
                "index": 0,
                "finish_reason": "tool_calls" if tool_calls else claude.STOP_TO_FINISH.get(response.stop_reason, "stop"),
                "message": {"role": "assistant", "content": text or None, "tool_calls": tool_calls or None},
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": response.usage.output_tokens or 0,
                "total_tokens": prompt_tokens + (response.usage.output_tokens or 0),
            },
        })
