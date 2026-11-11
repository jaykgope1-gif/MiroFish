"""
Demo-only stand-in for an OpenAI-compatible chat API.

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


def _reply(body, delay):
    messages = body.get("messages", [])
    tools = [t["function"] for t in body.get("tools", []) if t.get("type") == "function"]
    stance = _stance(messages)
    context = " ".join(str(m.get("content", "")) for m in messages[-2:])
    time.sleep(random.uniform(*delay))

    message = {"role": "assistant", "content": None}
    usable = [t for t in tools if t["name"] in WEIGHTS]
    if usable and NO_TOOLS_MARKER not in context:
        tool = random.choices(usable, weights=[WEIGHTS[t["name"]] for t in usable])[0]
        message["tool_calls"] = [{
            "id": "call_" + uuid.uuid4().hex[:12],
            "type": "function",
            "function": {"name": tool["name"],
                         "arguments": json.dumps(_arguments(tool.get("parameters"), stance, context))},
        }]
        finish = "tool_calls"
    else:
        poll = POLL_PATTERN.search(context)
        if poll:
            options = [o.strip() for o in poll.group(1).split("/")]
            # Mostly answer by stance (first option if opposing, second if
            # supportive, last otherwise), sometimes at random.
            pick = {"opposing": 0, "supportive": 1}.get(stance, len(options) - 1)
            if random.random() < 0.15:
                pick = random.randrange(len(options))
            answer = options[min(pick, len(options) - 1)].capitalize()
            message["content"] = f"{answer}. [demo reply, stance={stance}] {_sentence(stance)}"
        else:
            message["content"] = f"[demo reply, stance={stance}] {_sentence(stance)}"
        finish = "stop"

    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "demo"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
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
            data = json.dumps(_reply(body, delay)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
