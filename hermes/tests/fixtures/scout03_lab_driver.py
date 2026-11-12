"""SCOUT-03 lab driver: runs INSIDE the real Hermes v0.22.5 image, offline (`--network none`).

Input (/lab/input.json): the profile declarations to apply, the MCP policies and
the fake server URL. Creates throwaway profiles, applies the declared config
with the same `hermes config set` the role uses, starts fake_kandidat_mcp.py,
then collects facts with Hermes' own code: the deploy check (`hermes_checks.py
mcp`), the tools each platform exposes, and what really happens when tools are
called (unknown tool, approval gate, duplicates, injection, lost connection,
server down). Prints one `LAB_RESULT <json>` line.
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
        env=dict(os.environ, FAKE_FLIP="1" if flip else "0"),
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
out["cut"] = call("job-search", [{"tool": "mcp__kandidat__create_candidature",
                                  "args": {"entreprise": "Coupure", "cible_id": 1}}])
out["cut_calls"] = calls()[before:]
server.kill()
# Server down: reads fail safe, nothing raises.
out["down"] = call("job-search", [{"tool": "mcp__kandidat__list_cibles", "args": {}}])
out["down_check"] = check("job-search", INPUT["policies"]["job-search"])
print("LAB_RESULT " + json.dumps(out))
