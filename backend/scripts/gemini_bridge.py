"""
Gemini bridge: an OpenAI-compatible endpoint in front of Gemini's native API.

Google AI Studio now issues API keys that start with "AQ.". Those keys are
rejected by Gemini's OpenAI-compatible endpoint (/v1beta/openai), which is
what MiroFish's OpenAI provider calls, but they work on the native
generateContent API with the key in an `x-goog-api-key` header.

This bridge listens on 127.0.0.1, accepts OpenAI Chat Completions requests
(text, JSON mode and function calling, as MiroFish and the OASIS agents send
them), calls Gemini's native API, and answers in the OpenAI format.

    python scripts/gemini_bridge.py            # port 5056; key from GEMINI_API_KEY

Then in .env:

    LLM_PROVIDER=openai
    LLM_API_KEY=local-bridge
    LLM_BASE_URL=http://127.0.0.1:5056/v1
    LLM_MODEL_NAME=gemini-2.5-flash-lite
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# JSON-schema keys Gemini's function declarations accept (an OpenAPI subset).
SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format", "nullable",
               "minimum", "maximum", "minItems", "maxItems", "anyOf"}
FINISH = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter"}
RETRIES = 4


def clean_schema(schema):
    """Drop JSON-schema keys Gemini rejects; keep the structure."""
    if isinstance(schema, list):
        return [clean_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key not in SCHEMA_KEYS:
            continue
        if key == "properties":
            out[key] = {name: clean_schema(sub) for name, sub in value.items()}
        elif key in ("items", "anyOf"):
            out[key] = clean_schema(value)
        elif key == "type" and isinstance(value, list):  # ["string", "null"]
            kinds = [v for v in value if v != "null"]
            out[key] = kinds[0] if kinds else "string"
            if "null" in value:
                out["nullable"] = True
        else:
            out[key] = value
    if out.get("type") == "object" and not out.get("properties"):
        out.pop("required", None)
    return out


def text_of(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)


def to_gemini(body):
    """OpenAI Chat Completions request -> Gemini generateContent request."""
    system, contents, call_names = [], [], {}

    def add(role, parts):
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": list(parts)})

    for message in body.get("messages", []):
        role = message.get("role")
        if role in ("system", "developer"):
            if text_of(message.get("content")).strip():
                system.append(text_of(message.get("content")))
        elif role == "assistant":
            parts = []
            if text_of(message.get("content")).strip():
                parts.append({"text": text_of(message.get("content"))})
            for call in message.get("tool_calls") or []:
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                call_names[call.get("id")] = fn.get("name")
                parts.append({"functionCall": {"name": fn.get("name"), "args": args if isinstance(args, dict) else {}}})
            if parts:
                add("model", parts)
        elif role == "tool":
            name = call_names.get(message.get("tool_call_id"))
            result = text_of(message.get("content"))
            if name:
                try:
                    payload = json.loads(result)
                except (json.JSONDecodeError, TypeError):
                    payload = result
                add("user", [{"functionResponse": {"name": name, "response": {"result": payload}}}])
            else:  # its call fell out of the context window
                add("user", [{"text": f"[tool result: {result}]"}])
        else:
            if text_of(message.get("content")).strip():
                add("user", [{"text": text_of(message.get("content"))}])

    if not contents or contents[0]["role"] != "user":
        contents.insert(0, {"role": "user", "parts": [{"text": "Begin."}]})

    request = {"contents": contents}
    if system:
        request["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    config = {}
    if body.get("temperature") is not None:
        config["temperature"] = body["temperature"]
    if body.get("max_tokens") or body.get("max_completion_tokens"):
        config["maxOutputTokens"] = body.get("max_tokens") or body.get("max_completion_tokens")
    if (body.get("response_format") or {}).get("type") == "json_object":
        config["responseMimeType"] = "application/json"
    if config:
        request["generationConfig"] = config
    tools = [t["function"] for t in body.get("tools") or [] if t.get("type") == "function"]
    if tools:
        request["tools"] = [{"functionDeclarations": [
            {"name": t["name"], "description": t.get("description", ""),
             **({"parameters": clean_schema(t["parameters"])} if (t.get("parameters") or {}).get("properties") else {})}
            for t in tools
        ]}]
    return request


def to_openai(model, response):
    """Gemini generateContent response -> OpenAI chat.completion."""
    candidate = (response.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
    calls = [
        {"id": "call_" + uuid.uuid4().hex[:16], "type": "function",
         "function": {"name": p["functionCall"]["name"], "arguments": json.dumps(p["functionCall"].get("args") or {})}}
        for p in parts if "functionCall" in p
    ]
    usage = response.get("usageMetadata") or {}
    message = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = calls
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message,
                     "finish_reason": "tool_calls" if calls else FINISH.get(candidate.get("finishReason"), "stop")}],
        "usage": {"prompt_tokens": usage.get("promptTokenCount", 0),
                  "completion_tokens": usage.get("candidatesTokenCount", 0),
                  "total_tokens": usage.get("totalTokenCount", 0)},
    }


def call_gemini(model, request, api_key):
    data = json.dumps(request).encode()
    delay = 4
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(GEMINI.format(model=model), data=data, method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return 200, json.loads(response.read())
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")
            # Free tiers rate-limit hard: wait and retry instead of losing the call.
            if error.code in (429, 500, 503) and attempt < RETRIES:
                time.sleep(delay)
                delay *= 2
                continue
            return error.code, {"error": {"message": body[:1000], "type": "gemini_error", "code": error.code}}


class Handler(BaseHTTPRequestHandler):
    api_key = ""
    lock = threading.Lock()
    calls = 0

    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {"object": "list", "data": []})
        else:
            self._send(200, {"status": "ok", "calls": Handler.calls})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": {"message": "only /v1/chat/completions is supported"}})
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        model = body.get("model") or "gemini-2.5-flash-lite"
        status, response = call_gemini(model, to_gemini(body), self.api_key)
        with Handler.lock:
            Handler.calls += 1
        if status != 200:
            self._send(status, response)
            return
        self._send(200, to_openai(model, response))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("GEMINI_BRIDGE_PORT", "5056"))
    Handler.api_key = os.environ.get("GEMINI_API_KEY", "")
    if not Handler.api_key:
        sys.exit("Set GEMINI_API_KEY (the key from aistudio.google.com).")
    print(f"Gemini bridge on http://127.0.0.1:{port}/v1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
