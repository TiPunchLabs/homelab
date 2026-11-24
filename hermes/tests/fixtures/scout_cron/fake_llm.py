"""Scripted OpenAI-compatible endpoint for the scout_cron image lab (127.0.0.1 only, no network).

usage: fake_llm.py <port> <scenarios.json> <requests.jsonl>

A conversation names its scenario with a ``[[SC:<id>]]`` marker anywhere in its messages. The step
played is the number of assistant turns already in the conversation. A step is either
``{"call": <tool>, "args": {...}}`` — sent directly when the request offers that tool, else through
Hermes' ``tool_call`` bridge — or ``{"say": <text>}`` (final answer). A scenario may also be ``{"runs": [[steps], [steps], ...]}``: each new
conversation (step 0) moves to the next script, for successive cron runs of the same job prompt. Every request is appended to
the JSONL file (scenario, step, offered tool names, last tool result, the first user message), so the
lab asserts what the model was really shown. Streaming and non-streaming are both served.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, SCENARIOS, LOG = int(sys.argv[1]), sys.argv[2], sys.argv[3]
MARK = re.compile(r"\[\[SC:([A-Za-z0-9_.-]+)\]\]")
_lock = threading.Lock()
_runs: dict[str, int] = {}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(p.get("text") if isinstance(p, dict) else p) for p in content)
    return ""


def _plan(body: dict) -> tuple[str, int, dict]:
    messages = body.get("messages") or []
    scenario = ""
    for m in messages:
        found = MARK.search(_text(m.get("content")))
        if found:
            scenario = found.group(1)
            break
    step = sum(1 for m in messages if m.get("role") == "assistant")
    with open(SCENARIOS, encoding="utf-8") as fh:
        steps = json.load(fh).get(scenario, [{"say": "[[no scenario]]"}])
    run = 0
    if isinstance(steps, dict):
        with _lock:
            if step == 0:
                _runs[scenario] = _runs.get(scenario, -1) + 1
            run = _runs.get(scenario, 0)
        scripts = steps.get("runs") or [[]]
        steps = scripts[min(run, len(scripts) - 1)]
    action = steps[step] if step < len(steps) else {"say": "[[scenario exhausted]]"}
    tools = {t.get("function", {}).get("name") for t in body.get("tools") or []}
    with _lock, open(LOG, "a", encoding="utf-8") as fh:
        last_tool = next((_text(m.get("content")) for m in reversed(messages) if m.get("role") == "tool"), None)
        first_user = next((_text(m.get("content")) for m in messages if m.get("role") == "user"), "")
        system = next((_text(m.get("content")) for m in messages if m.get("role") == "system"), "")
        fh.write(json.dumps({"t": time.time(), "scenario": scenario, "run": run, "step": step, "tools": sorted(t for t in tools if t),
                             "last_tool": last_tool, "first_user": first_user, "system_len": len(system)},
                            ensure_ascii=False) + "\n")
    if "call" in action:
        name, args = action["call"], action.get("args") or {}
        if name not in tools and "tool_call" in tools:
            name, args = "tool_call", {"calls": [{"name": action["call"], "arguments": args}]}
        call = {"id": f"call_{scenario}_{step}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
        return scenario, step, {"role": "assistant", "content": None, "tool_calls": [call]}
    return scenario, step, {"role": "assistant", "content": action.get("say", "")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {"object": "list", "data": [{"id": "fake-model", "object": "model",
                                                          "context_length": 128000}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": {"message": f"unsupported path {self.path}"}})
            return
        _scenario, _step, message = _plan(body)
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if not body.get("stream"):
            self._send(200, {"id": "cmpl-fake", "object": "chat.completion", "created": int(time.time()),
                             "model": "fake-model", "usage": usage,
                             "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        delta = {"role": "assistant"}
        if message.get("tool_calls"):
            delta["tool_calls"] = [{"index": 0, **message["tool_calls"][0]}]
        else:
            delta["content"] = message["content"]
        for chunk in ({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}):
            chunk.update({"id": "cmpl-fake", "object": "chat.completion.chunk", "created": int(time.time()),
                          "model": "fake-model"})
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
