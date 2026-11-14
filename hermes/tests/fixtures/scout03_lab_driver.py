"""SCOUT-03 lab driver: runs INSIDE the real Hermes v0.22.5 image, offline (`--network none`).

Input (/lab/input.json): the profile declarations to apply, the MCP policies and
the fake server URL. Creates throwaway profiles, applies the declared config
with the same `hermes config set` the role uses, starts fake_kandidat_mcp.py,
then collects facts with Hermes' own code: the deploy check (`hermes_checks.py
mcp`), the tools each platform exposes, and what really happens when tools are
called (unknown tool, approval gate, duplicates, injection, lost connection,
server down), and a concurrent phase in ONE process shaped like the multiplex
gateway (per-turn profile scopes carried into worker threads, the real gateway
approval queue). Prints one `LAB_RESULT <json>` line.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import Any

LAB = "/lab"
INPUT = json.load(open(f"{LAB}/input.json", encoding="utf-8"))
CHECKS = open(f"{LAB}/hermes_checks.py", encoding="utf-8").read()
CALLS = "/tmp/calls.jsonl"
PORT = INPUT["port"]
ROOT = "/tmp/data"
RELEASE = "/tmp/release-get-stats"


def run(*argv: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command in /opt/hermes and capture its output."""
    return subprocess.run(list(argv), capture_output=True, text=True, cwd="/opt/hermes", env=env, timeout=300)


def home(profile: str) -> str:
    """HERMES_HOME of a profile (default is the root)."""
    return ROOT if profile == "default" else f"{ROOT}/profiles/{profile}"


def start_server(port: int = PORT, flip: bool = False) -> subprocess.Popen[bytes]:
    """Start a fake Kandidat server and wait for its port."""
    proc = subprocess.Popen(
        [sys.executable, f"{LAB}/fixtures/fake_kandidat_mcp.py", str(port), CALLS,
         f"{LAB}/fixtures/kandidat_mcp_tools.json"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=dict(os.environ, FAKE_FLIP="1" if flip else "0", FAKE_RELEASE=RELEASE),
    )
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 1).close()
            return proc
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("fake Kandidat server did not start")


def calls() -> list[dict[str, Any]]:
    """Every call that reached the fake server."""
    if not os.path.exists(CALLS):
        return []
    return [json.loads(line) for line in open(CALLS, encoding="utf-8")]


def check(profile: str, policy: dict[str, Any]) -> list[Any]:
    """The role's deploy check, same script and arguments as profile_multiplex.yml."""
    r = run("python3", "-c", CHECKS, "mcp", json.dumps(policy), env=dict(os.environ, HERMES_HOME=home(profile)))
    return [r.returncode, (r.stdout + r.stderr).strip()[-1500:]]


CALLER = r'''
import json, logging, os, sys
logging.disable(logging.CRITICAL)
from hermes_cli.config import load_config
from hermes_cli.tools_config import _get_platform_tools
import model_tools
from tools.mcp_tool_discovery import register_mcp_servers
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.registry import registry
import tools.approval_prompt as ap

steps = json.loads(sys.argv[1])
real_consent = ap.request_elicitation_consent
asked = []
cfg = load_config()
register_mcp_servers({n: s for n, s in (cfg.get("mcp_servers") or {}).items() if s.get("enabled", True)})
out = {"exposed": {}, "results": [], "registry_mcp": sorted(t for t in registry.get_all_tool_names() if t.startswith("mcp"))}
for p in ("telegram", "api_server", "cli", "cron"):
    defs = model_tools.get_tool_definitions(enabled_toolsets=sorted(_get_platform_tools(cfg, p)),
                                            disabled_toolsets=(cfg.get("agent") or {}).get("disabled_toolsets"),
                                            quiet_mode=True)
    out["exposed"][p] = sorted(d["function"]["name"] for d in defs if d["function"]["name"].startswith("mcp"))
out["asked"] = []
for step in steps:
    consent = step.get("consent")
    asked.clear()
    if consent:
        def recorder(message, description, *a, _answer=consent, **k):
            asked.append(message)
            return _answer
        ap.request_elicitation_consent = recorder
    else:
        ap.request_elicitation_consent = real_consent
    if step.get("nobody"):
        os.environ["HERMES_CRON_SESSION"] = "1"
    else:
        os.environ.pop("HERMES_CRON_SESSION", None)
    res = registry.dispatch(step["tool"], step.get("args", {}))
    out["results"].append(res if isinstance(res, str) else json.dumps(res))
    out["asked"].append(len(asked))
out["registry_mcp_after"] = sorted(t for t in registry.get_all_tool_names() if t.startswith("mcp"))
out["config_servers_after"] = sorted((load_config().get("mcp_servers") or {}))
shutdown_mcp_servers()
print("CALLER " + json.dumps(out))
'''


SCOPED = r'''
import json, logging, sys
from pathlib import Path
logging.disable(logging.CRITICAL)
from agent.secret_scope import set_multiplex_active
set_multiplex_active(True)
from gateway.run import _profile_runtime_scope
from hermes_cli.config import load_config
from hermes_cli.tools_config import _get_platform_tools
import model_tools
from tools.mcp_tool_discovery import register_mcp_servers
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.registry import registry
seq = json.loads(sys.argv[1])
out = []
for name, home in seq:
    with _profile_runtime_scope(Path(home)):
        cfg = load_config()
        enabled = {n: s for n, s in (cfg.get("mcp_servers") or {}).items() if s.get("enabled", True)}
        if enabled:
            register_mcp_servers(enabled)
        exposed = {}
        for p in ("telegram", "cron"):
            defs = model_tools.get_tool_definitions(enabled_toolsets=sorted(_get_platform_tools(cfg, p)),
                                                    disabled_toolsets=(cfg.get("agent") or {}).get("disabled_toolsets"),
                                                    quiet_mode=True)
            exposed[p] = sorted(d["function"]["name"] for d in defs if d["function"]["name"].startswith("mcp"))
        res = registry.dispatch("mcp__kandidat__list_cibles", {})
        out.append({"profile": name, "exposed": exposed, "list_cibles": res if isinstance(res, str) else json.dumps(res)})
shutdown_mcp_servers()
print("SCOPED " + json.dumps(out))
'''


CONCURRENT = r'''
import json, logging, os, sys, threading, time
from contextvars import copy_context
from pathlib import Path
logging.disable(logging.CRITICAL)
from agent.secret_scope import set_multiplex_active
set_multiplex_active(True)
from gateway.run import _profile_runtime_scope
from gateway.session_context import set_session_vars
from hermes_cli.config import load_config
from hermes_cli.tools_config import _get_platform_tools
import model_tools
from tools import approval as A
from tools.approval_context import set_current_session_key
from tools.mcp_tool_discovery import discover_mcp_tools
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.registry import registry

homes, calls_log, release = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3]
SESSION = {"job-search": "telegram:scout-chat", "default": "telegram:nora-chat", "cafe-ia": "telegram:kafeine-chat"}
prompts = []          # (session, prompt text) in the order the gateway would send them
prompt_lock = threading.Lock()
out = {"timeouts": []}


def wait_until(label, predicate, limit=60.0):
    # A condition, never a fixed delay; the limit only turns a hang into a recorded failure.
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    out["timeouts"].append(label)
    return False


def server_calls():
    return [json.loads(x) for x in open(calls_log, encoding="utf-8")] if os.path.exists(calls_log) else []


def notifier(session):
    def cb(data):
        with prompt_lock:
            prompts.append((session, data.get("command", "")))
    return cb


# Gateway start: MCP discovery once per served profile, inside that profile's scope (gateway/run.py).
for name, home in homes.items():
    with _profile_runtime_scope(Path(home)):
        copy_context().run(discover_mcp_tools)
for name in homes:
    A.register_gateway_notify(SESSION[name], notifier(SESSION[name]))


def start(label, name, fn, results, barrier=None):
    # One turn: the profile scope is entered on the loop and copied into the agent worker (copy_context()).
    with _profile_runtime_scope(Path(homes[name])):
        ctx = copy_context()

    def body():
        set_session_vars(platform="telegram", session_key=SESSION[name], profile=name)
        set_current_session_key(SESSION[name])
        if barrier is not None:
            barrier.wait(30)
        try:
            results[label] = fn()
        except Exception as exc:  # recorded, never raised: the assertions read it
            results[label] = "EXC " + repr(exc)

    thread = threading.Thread(target=ctx.run, args=(body,), daemon=True)
    thread.start()
    return thread


def dispatch(tool, args=None):
    res = registry.dispatch(tool, args or {})
    return res if isinstance(res, str) else json.dumps(res)


def probe():
    # What a non-Scout turn sees and can do while Scout is busy.
    cfg = load_config()
    exposed = {}
    for p in ("telegram", "cron"):
        defs = model_tools.get_tool_definitions(enabled_toolsets=sorted(_get_platform_tools(cfg, p)),
                                                disabled_toolsets=(cfg.get("agent") or {}).get("disabled_toolsets"),
                                                quiet_mode=True)
        exposed[p] = sorted(d["function"]["name"] for d in defs if "kandidat" in d["function"]["name"]
                            or d["function"]["name"].startswith("mcp"))
    return {
        "servers": sorted(n for n, spec in (cfg.get("mcp_servers") or {}).items() if spec.get("enabled", True)),
        "declared": {n: spec.get("enabled", True) for n, spec in (cfg.get("mcp_servers") or {}).items()},
        "exposed": exposed,
        "registry": sorted(t for t in registry.get_all_tool_names() if "kandidat" in t or t.startswith("mcp")),
        "entry": registry.get_entry("mcp__kandidat__list_cibles") is not None,
        "read": dispatch("mcp__kandidat__list_cibles"),
        "held_read": dispatch("mcp__kandidat__get_stats"),
        "write": dispatch("mcp__kandidat_confirm__create_candidature", {"entreprise": "Fuite", "cible_id": 2}),
    }


res = {}
# Phase 1: a Scout read is held in flight by the server; Nora and Kaféine run their turns meanwhile, together.
scout_read = start("scout_read", "job-search", lambda: dispatch("mcp__kandidat__get_stats"), res)
wait_until("scout read reached the server", lambda: any(c["tool"] == "get_stats" for c in server_calls()))
both = threading.Barrier(2)
others = [start(n, n, probe, res, both) for n in ("default", "cafe-ia")]
for t in others:
    t.join(60)
out["scout_read_in_flight_during_others"] = scout_read.is_alive()

# Phase 2: a Scout write waits for approval; the other profiles act meanwhile and cannot answer it.
scout_write = start("scout_write", "job-search", lambda: dispatch(
    "mcp__kandidat_confirm__create_candidature", {"entreprise": "Offre Concurrente", "cible_id": 2}), res)
wait_until("scout prompt", lambda: len(prompts) == 1)
others = [start(n + "_during_prompt", n, probe, res, both) for n in ("default", "cafe-ia")]
for t in others:
    t.join(60)
out["foreign_resolves"] = {s: A.resolve_gateway_approval(s, "always", resolve_all=True)
                           for s in (SESSION["default"], SESSION["cafe-ia"])}
out["scout_queue_while_pending"] = len(A._gateway_queues.get(SESSION["job-search"], []))
out["scout_write_pending_after_foreign"] = scout_write.is_alive()
open(release, "w").close()
scout_read.join(60)
out["scout_resolved_deny"] = A.resolve_gateway_approval(SESSION["job-search"], "deny")
scout_write.join(60)
out["prompts_phase2"] = list(prompts)

# Phase 3: two Scout writes in parallel in the same chat, the first answered with the widest choice.
prompts.clear()
pair = threading.Barrier(2)
writers = [start("parallel_" + x, "job-search", lambda x=x: dispatch(
    "mcp__kandidat_confirm__create_candidature", {"entreprise": "Parallele " + x, "cible_id": 1}), res, pair)
    for x in ("A", "B")]
wait_until("first parallel prompt", lambda: len(prompts) == 1)
out["parallel_queue_at_first_prompt"] = len(A._gateway_queues.get(SESSION["job-search"], []))
A.resolve_gateway_approval(SESSION["job-search"], "session")
out["second_prompt_seen"] = wait_until("second parallel prompt", lambda: len(prompts) == 2)
A.resolve_gateway_approval(SESSION["job-search"], "deny")
for t in writers:
    t.join(60)
out["prompts_phase3"] = list(prompts)

# Phase 4: sequential writes after an "always": the next one still asks.
prompts.clear()
for label, answer in (("after_always_1", "always"), ("after_always_2", "deny")):
    expected = len(prompts) + 1  # counted before the worker can publish its prompt
    t = start(label, "job-search", lambda l=label: dispatch(
        "mcp__kandidat_confirm__create_cible", {"nom": l, "categorie": "esn"}), res)
    wait_until(label + " prompt", lambda n=expected: len(prompts) == n)
    A.resolve_gateway_approval(SESSION["job-search"], answer)
    t.join(60)
out["prompts_phase4"] = list(prompts)
check = {}
t = start("cible_2", "job-search", lambda: dispatch("mcp__kandidat__get_cible_detail", {"cible_id": 2}), check)
t.join(60)
out["cible_2_after"] = check["cible_2"]
out["results"] = res
shutdown_mcp_servers()
print("CONCURRENT " + json.dumps(out))
'''


def concurrent() -> Any:
    """Scout, Nora and Kaféine turns overlapping in one multiplex-shaped process."""
    homes = {name: home(name) for name in ("job-search", "default", "cafe-ia")}
    r = run("python3", "-c", CONCURRENT, json.dumps(homes), CALLS, RELEASE, env=dict(os.environ, HERMES_HOME=ROOT))
    line = next((x for x in r.stdout.splitlines() if x.startswith("CONCURRENT ")), None)
    return json.loads(line.removeprefix("CONCURRENT ")) if line else {"error": r.stderr[-3000:]}


def scoped(sequence: list[str]) -> Any:
    """One process, the gateway's own per-turn profile scope, profiles in turn (multiplex emulation)."""
    pairs = [[name, home(name)] for name in sequence]
    r = run("python3", "-c", SCOPED, json.dumps(pairs), env=dict(os.environ, HERMES_HOME=ROOT))
    line = next((x for x in r.stdout.splitlines() if x.startswith("SCOPED ")), None)
    return json.loads(line.removeprefix("SCOPED ")) if line else {"error": r.stderr[-2000:]}


def call(profile: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Register the profile's MCP servers in a fresh process and dispatch `steps` like the agent does."""
    r = run("python3", "-c", CALLER, json.dumps(steps), env=dict(os.environ, HERMES_HOME=home(profile)))
    line = next((x for x in r.stdout.splitlines() if x.startswith("CALLER ")), None)
    return json.loads(line.removeprefix("CALLER ")) if line else {"error": r.stderr[-1500:]}


out: dict[str, Any] = {}
os.makedirs(ROOT, exist_ok=True)
for name in INPUT["profiles"]:
    if name != "default":
        run("hermes", "profile", "create", name, "--no-alias")
out["set"] = {}
for name, cfg in INPUT["profiles"].items():
    prefix = [] if name == "default" else ["-p", name]
    out["set"][name] = {k: run("hermes", *prefix, "config", "set", k, v).returncode for k, v in cfg.items()}
out["get"] = {k: run("hermes", "-p", "job-search", "config", "get", k, "--json").stdout
              for k in INPUT["profiles"]["job-search"]}

server = start_server()
out["check"] = {name: check(name, policy) for name, policy in INPUT["policies"].items()}
out["check_drift"] = {}
for label, (key, value, *policy) in INPUT["drifts"].items():
    run("hermes", "-p", "job-search", "config", "set", key, value)
    out["check_drift"][label] = check("job-search", policy[0] if policy else INPUT["policies"]["job-search"])
    run("hermes", "-p", "job-search", "config", "set", key, INPUT["profiles"]["job-search"][key])
out["check_restored"] = check("job-search", INPUT["policies"]["job-search"])
out["others"] = {name: call(name, [])["exposed"] for name in INPUT["profiles"] if name != "job-search"}

before = len(calls())
out["scout"] = call("job-search", INPUT["steps"])
out["calls"] = calls()[before:]

out["scoped"] = scoped(["job-search", "default", "cafe-ia", "job-search"])
before = len(calls())
out["concurrent"] = concurrent()
out["concurrent_calls"] = calls()[before:]

# A release advertising the gated writes as read-only: the deploy check refuses it, and the local
# cost gate still asks before every call.
flip_port = PORT + 1
flip = start_server(flip_port, flip=True)
flip_url = f"http://127.0.0.1:{flip_port}/mcp"
confirm = json.loads(INPUT["profiles"]["job-search"]["mcp_servers.kandidat_confirm"]) | {"url": flip_url}
run("hermes", "-p", "job-search", "config", "set", "mcp_servers.kandidat_confirm", json.dumps(confirm))
flip_policy = json.loads(json.dumps(INPUT["policies"]["job-search"]))
flip_policy["servers"]["kandidat_confirm"]["url"] = flip_url
out["flip_check"] = check("job-search", flip_policy)
before = len(calls())
out["flip"] = call("job-search", INPUT["flip_steps"])
out["flip_calls"] = calls()[before:]
flip.kill()
run("hermes", "-p", "job-search", "config", "set", "mcp_servers.kandidat_confirm",
    INPUT["profiles"]["job-search"]["mcp_servers.kandidat_confirm"])

# Lost connection after the server received a write: Hermes must not replay it.
before = len(calls())
out["cut"] = call("job-search", [{"tool": "mcp__kandidat_confirm__create_candidature", "consent": "accept",
                                  "args": {"entreprise": "Coupure", "cible_id": 1}}])
out["cut_calls"] = calls()[before:]
server.kill()
# Server down: reads fail safe, nothing raises.
out["down"] = call("job-search", [{"tool": "mcp__kandidat__list_cibles", "args": {}}])
out["down_check"] = check("job-search", INPUT["policies"]["job-search"])
print("LAB_RESULT " + json.dumps(out))
