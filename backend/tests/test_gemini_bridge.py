import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gemini_bridge as gb  # noqa: E402


def test_request_converts_system_tools_and_tool_results():
    request = gb.to_gemini({
        "model": "gemini-2.5-flash-lite",
        "temperature": 0.5,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You are Maya."},
            {"role": "user", "content": "Observe."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "like_post", "arguments": '{"post_id": 3}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": '{"success": true}'},
            {"role": "tool", "tool_call_id": "gone", "content": "old"},
        ],
        "tools": [{"type": "function", "function": {"name": "like_post", "description": "Like", "parameters": {
            "type": "object", "properties": {"post_id": {"type": ["integer", "null"], "default": 1}},
            "required": ["post_id"], "additionalProperties": False, "$schema": "x"}}},
                  {"type": "function", "function": {"name": "do_nothing", "parameters": {"type": "object", "properties": {}}}}],
    })

    assert request["systemInstruction"] == {"parts": [{"text": "You are Maya."}]}
    assert [c["role"] for c in request["contents"]] == ["user", "model", "user"]
    assert request["contents"][1]["parts"] == [{"functionCall": {"name": "like_post", "args": {"post_id": 3}}}]
    assert request["contents"][2]["parts"][0] == {"functionResponse": {"name": "like_post", "response": {"result": {"success": True}}}}
    assert request["contents"][2]["parts"][1] == {"text": "[tool result: old]"}
    declarations = request["tools"][0]["functionDeclarations"]
    assert declarations[0]["parameters"] == {"type": "object", "required": ["post_id"],
                                             "properties": {"post_id": {"type": "integer", "nullable": True}}}
    assert "parameters" not in declarations[1]
    assert request["generationConfig"] == {"temperature": 0.5, "responseMimeType": "application/json"}


def test_response_converts_function_calls_and_text():
    out = gb.to_openai("gemini-2.5-flash-lite", {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "thinking", "thought": True}, {"text": "Liking it."},
            {"functionCall": {"name": "like_post", "args": {"post_id": 7}}}]}}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10, "totalTokenCount": 110},
    })
    choice = out["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "Liking it."
    assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {"post_id": 7}
    assert out["usage"]["total_tokens"] == 110

    out = gb.to_openai("m", {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{\"a\""}]}}]})
    assert out["choices"][0]["finish_reason"] == "length" and "tool_calls" not in out["choices"][0]["message"]
