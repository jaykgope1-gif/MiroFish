"""
Demo-only stand-in for the LLM: answers both the Anthropic Messages API
(/v1/messages, used with LLM_PROVIDER=anthropic) and OpenAI Chat
Completions (/v1/chat/completions).

It lets the God View demo run with no API key. It does not think: every
request gets one tool call picked at random from the tools the request
offers (so the real OASIS engine performs real platform actions), and all
text is a canned sentence chosen by the agent's stance. Interview and poll
replies are canned too and say so ("[demo reply]").

Do not use it for anything but the demo.
"""

import json
import random
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOPICS = ["tuition hike", "library closure", "student union", "campus protest", "budget audit"]
LINES = {
    "supportive": [
        "The {t} is painful but necessary. The numbers leave no other option.",
        "People attacking the {t} have not read the budget. I back the administration here.",
        "Unpopular view: the {t} will protect teaching quality in the long run.",
    ],
    "opposing": [
        "The {t} is a betrayal of students. We were never consulted.",
        "Nobody voted for the {t}. Reverse it now.",
        "Another day, another excuse for the {t}. Students are paying for bad management.",
    ],
    "neutral": [
        "Trying to understand the {t}. Does anyone have the actual figures?",
        "Both sides on the {t} are talking past each other. Where is the data?",
        "Reporting: a new statement on the {t} is expected this week.",
    ],
}
# How often each platform action is picked, when the request offers it.
WEIGHTS = {
    "create_post": 4, "like_post": 5, "repost": 2, "quote_post": 1, "follow": 1,
    "create_comment": 4, "dislike_post": 1, "like_comment": 1, "do_nothing": 2,
}
# MiroFish adds this phrase to interview prompts to ask for a plain-text reply.
NO_TOOLS_MARKER = "不调用任何工具"
POLL_PATTERN = re.compile(r"exactly one of these words: (.+?)\. Then")


def _stance(messages):
    text = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "system").lower()
    for stance in ("opposing", "supportive"):
        if f"stance: {stance}" in text:
            return stance
    return "neutral"


def _sentence(stance):
    return random.choice(LINES[stance]).format(t=random.choice(TOPICS))


def _arguments(schema, stance, context):
    post_ids = [int(x) for x in re.findall(r'"post_id":\s*(\d+)', context)] or [1]
    comment_ids = [int(x) for x in re.findall(r'"comment_id":\s*(\d+)', context)] or [1]
    user_ids = [int(x) for x in re.findall(r'"user_id":\s*(\d+)', context)] or [1]
    args = {}
    for key in (schema or {}).get("properties", {}):
        if key == "post_id":
            args[key] = random.choice(post_ids)
        elif key == "comment_id":
            args[key] = random.choice(comment_ids)
        elif key in ("followee_id", "mutee_id", "user_id"):
            args[key] = random.choice(user_ids)
        elif key == "query":
            args[key] = random.choice(TOPICS)
        else:
            args[key] = _sentence(stance)
    return args


def _decide(system_text, context, tools, delay):
    """Pick one tool call or a text reply. tools: [(name, json schema)]."""
    stance = _stance([{"role": "system", "content": system_text}])
    time.sleep(random.uniform(*delay))
    usable = [(name, schema) for name, schema in tools if name in WEIGHTS]
    if usable and NO_TOOLS_MARKER not in context:
        name, schema = random.choices(usable, weights=[WEIGHTS[n] for n, _ in usable])[0]
        return "tool", name, _arguments(schema, stance, context)
    poll = POLL_PATTERN.search(context)
    if poll:
        options = [o.strip() for o in poll.group(1).split("/")]
        # Mostly answer by stance (first option if opposing, second if
        # supportive, last otherwise), sometimes at random.
        pick = {"opposing": 0, "supportive": 1}.get(stance, len(options) - 1)
        if random.random() < 0.15:
            pick = random.randrange(len(options))
        answer = options[min(pick, len(options) - 1)].capitalize()
        return "text", f"{answer}. [demo reply, stance={stance}] {_sentence(stance)}", None
    return "text", f"[demo reply, stance={stance}] {_sentence(stance)}", None


def _reply(body, delay):
    """OpenAI Chat Completions format (/v1/chat/completions)."""
    messages = body.get("messages", [])
    system_text = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
    context = " ".join(str(m.get("content", "")) for m in messages[-2:])
    tools = [(t["function"]["name"], t["function"].get("parameters"))
             for t in body.get("tools", []) if t.get("type") == "function"]
    kind, value, args = _decide(system_text, context, tools, delay)

    message = {"role": "assistant", "content": None}
    if kind == "tool":
        message["tool_calls"] = [{
            "id": "call_" + uuid.uuid4().hex[:12],
            "type": "function",
            "function": {"name": value, "arguments": json.dumps(args)},
        }]
        finish = "tool_calls"
    else:
        message["content"] = value
        finish = "stop"
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "demo"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _block_text(content):
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_result":
            parts.append(_block_text(block.get("content")))
    return " ".join(parts)


def _reply_messages(body, delay):
    """
    Anthropic Messages format (/v1/messages), as sent by the Anthropic SDK.

    Token counts are estimated from the request size (about 4 characters per
    token), so the demo's cost figures show roughly what a real run of the
    same size would be billed.
    """
    system = body.get("system") or ""
    system_text = system if isinstance(system, str) else _block_text(system)
    messages = body.get("messages", [])
    context = " ".join(_block_text(m.get("content")) for m in messages[-2:])
    tools = [(t["name"], t.get("input_schema")) for t in body.get("tools", []) if "name" in t]
    kind, value, args = _decide(system_text, context, tools, delay)

    if kind == "tool":
        content = [{"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:20], "name": value, "input": args}]
        stop = "tool_use"
    else:
        content = [{"type": "text", "text": value}]
        stop = "end_turn"
    return {
        "id": "msg_" + uuid.uuid4().hex[:24],
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "demo"),
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": max(1, len(json.dumps(body)) // 4),
            "output_tokens": max(1, len(json.dumps(content)) // 4),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


def serve(port, delay=(0.4, 1.0)):
    """Start the stand-in on 127.0.0.1:<port> in a background thread."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                body = {}
            if self.path.startswith("/v1/messages"):
                data = json.dumps(_reply_messages(body, delay)).encode()
            else:
                data = json.dumps(_reply(body, delay)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
