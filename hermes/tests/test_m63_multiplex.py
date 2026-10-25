"""M6.3.B: hermes-31 on Hermes v0.22.5, one multiplexed gateway for the four assistants.

Static: inventory and host_vars (hermes-31 multiplexed, hermes-30 unchanged and locked), the
deploy.yml target guard (run for real on localhost), the multiplex task file against profile.yml,
main.yml ordering, rendered templates. hermes_checks: multiplex and per-profile Telegram verdicts.
Real profile_multiplex.yml against a fake container. Effective inventory (vault, skipped without).
**Real image, offline** (v0.22.5, `--network none`, skipped without it): multiplex boot, served
profiles, one API on loopback, tool surfaces, managed allowlist in every profile scope, lifecycle
verbs, container restart, dashboard login. Fake secrets only; nothing reaches hermes-30 or hermes-31.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import FAKE_TOKEN, REPO, ROLE, RunTasks, recap

sys.path.insert(0, str(ROLE / "files"))
sys.path.insert(0, str(ROLE / "filter_plugins"))
import hermes_checks as hc
import hermes_profiles as hp

ANSIBLE_DIR = REPO / "hermes/ansible"
TASKS = ROLE / "tasks"
GROUP_VARS = yaml.safe_load((ANSIBLE_DIR / "group_vars/hermes/all/main.yml").read_text())
HOST_31 = yaml.safe_load((ANSIBLE_DIR / "host_vars/hermes-31/main.yml").read_text())
HOST_30 = yaml.safe_load((ANSIBLE_DIR / "host_vars/hermes-30/main.yml").read_text())
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
IMAGE = f"{DEFAULTS['hermes_image']}:{HOST_31['hermes_image_tag']}"
ALLOWLIST = GROUP_VARS["hermes_telegram_allowed_users"]
PROFILE_KEYS = ("hermes_profile_cafe_ia", "hermes_profile_tech_watch", "hermes_profile_job_search")
NAMES = ["cafe-ia", "tech-watch", "job-search"]
TOKENS = {
    "default": "111111111:FAKE-default-aaaaaaaaaaaaaaaaaaaaaaaaaa",
    "cafe-ia": "222222222:FAKE-cafeia-bbbbbbbbbbbbbbbbbbbbbbbbbb",
    "tech-watch": "333333333:FAKE-techwatch-cccccccccccccccccccccc",
    "job-search": "444444444:FAKE-jobsearch-dddddddddddddddddddddd",
}
# Tool surface of v0.20.4 (M3.3.1, M4.3, M5.4): unchanged on v0.22.5 with tool_search off.
NINE_TOOLS = {
    "clarify", "memory", "session_search", "skill_manage", "skill_view", "skills_list",
    "todo_list", "web_extract", "web_search",
}
NORA_TOOLS = {"clarify", "memory", "todo_list", "web_extract", "web_search"}
BRIDGE_TOOLS = {"tool_search", "tool_describe", "tool_call"}
# sha256 of /opt/hermes/docker/SOUL.md in the v0.22.5 image, seeded into a fresh /opt/data by stage2-hook.sh.
V0225_STOCK_SOUL_SHA = "3bd38ef92efb90d0fdda1bb73036185d4a4bc11079963cb0e2db71c84281e64e"


def tasks_of(path: Path) -> list[dict[str, Any]]:
    """The top-level tasks of a task file."""
    return yaml.safe_load(path.read_text())


def names_of(path: Path) -> list[str]:
    """Task names of a task file, in order."""
    return [t.get("name", "") for t in tasks_of(path)]


def overlay() -> dict[str, Any]:
    """The v0.22-only config keys hermes-31 adds to every profile."""
    return HOST_31["hermes_v022_config"]


def effective_configs() -> dict[str, dict[str, Any]]:
    """Config keys per profile as hermes-31 resolves them (fake private hint for Scout)."""
    out = {"default": GROUP_VARS["hermes_default_nora"]["config"] | overlay()}
    for key in PROFILE_KEYS:
        decl = GROUP_VARS[key]
        cfg = decl["config"] | overlay()
        if "agent.environment_hint" in cfg and "vault_" in str(cfg["agent.environment_hint"]):
            cfg["agent.environment_hint"] = "Contexte FAKE de Scout."
        out[decl["name"]] = cfg
    return out


# --- Inventory and host_vars ------------------------------------------------------------


def test_inventory_has_both_hosts_with_their_ssh_aliases() -> None:
    """hermes-31 joins the hermes group beside hermes-30, each through its own SSH alias."""
    hosts = yaml.safe_load((ANSIBLE_DIR / "inventory.yml").read_text())["all"]["children"]["hermes"]["hosts"]
    assert hosts == {"hermes-30": {"ansible_host": "hermes-30"}, "hermes-31": {"ansible_host": "hermes-31"}}


def test_hermes_31_is_v0225_multiplexed_and_starts_without_telegram() -> None:
    """Exact tag, multiplex on, Telegram off (phase 1), Komodo identity not hermes-30's."""
    assert HOST_31["hermes_image_tag"] == "v0.22.5"
    assert HOST_31["hermes_gateway_multiplex"] is True
    assert HOST_31["hermes_telegram_enabled"] is False
    assert HOST_31["komodo_connect_as"] == "hermes-31"
    assert overlay() == {"tools.tool_search.enabled": "off"}


def test_hermes_31_reuses_the_four_declarations_plus_the_overlay_only() -> None:
    """Same declarations as group_vars, same order; the only addition is the v0.22 overlay."""
    expected = [
        f"{{{{ {key} | combine({{'config': {key}.config | combine(hermes_v022_config)}}) }}}}" for key in PROFILE_KEYS
    ]
    assert HOST_31["hermes_profiles"] == expected
    assert HOST_31["hermes_default_profile"] == (
        "{{ hermes_default_nora | combine({'config': hermes_default_nora.config | combine(hermes_v022_config)}) }}"
    )
    assert set(HOST_31) == {
        "hermes_image_tag", "hermes_gateway_multiplex", "hermes_telegram_enabled", "hermes_v022_config",
        "hermes_profiles", "hermes_default_profile", "komodo_connect_as", "hermes_default_soul_predecessor_sha256",
    }


def test_hermes_31_replaces_the_image_stock_soul_not_hermes_30s() -> None:
    """Fresh volume: the predecessor is v0.22.5's seeded docker/SOUL.md; hermes-30 keeps its own."""
    assert HOST_31["hermes_default_soul_predecessor_sha256"] == V0225_STOCK_SOUL_SHA
    assert GROUP_VARS["hermes_default_soul_predecessor_sha256"] != V0225_STOCK_SOUL_SHA


def test_hermes_30_keeps_the_role_defaults_and_is_locked() -> None:
    """hermes-30: no image, topology or profile override; only the deploy lock."""
    assert HOST_30 == {"hermes_deploy_locked": True}
    assert DEFAULTS["hermes_image_tag"] == "v2026.8.18"
    assert DEFAULTS["hermes_gateway_multiplex"] is False
    assert "tools.tool_search.enabled" not in str(GROUP_VARS)


# --- deploy.yml target guard (real task, localhost) ---------------------------------------


def guard_task() -> dict[str, Any]:
    """The first deploy.yml pre_task."""
    return yaml.safe_load((ANSIBLE_DIR / "deploy.yml").read_text())[0]["pre_tasks"][0]


def test_guard_runs_first_and_always() -> None:
    """Before the timezone write and under any --tags."""
    task = guard_task()
    assert task["name"] == "Refuse an implicit or locked deployment target"
    assert task["tags"] == ["always"]


@pytest.mark.parametrize(
    ("limit", "extra", "ok"),
    [
        (None, [], {"hermes-30": False, "hermes-31": False}),
        ("hermes-31", [], {"hermes-31": True}),
        ("hermes-30", [], {"hermes-30": False}),
        ("hermes-30", ["-e", "hermes_deploy_unlock=hermes-30"], {"hermes-30": True}),
        ("hermes-30", ["-e", "hermes_deploy_unlock=hermes-31"], {"hermes-30": False}),
        ("hermes", [], {"hermes-30": False, "hermes-31": True}),
    ],
    ids=["no-limit", "limit-31", "limit-30-locked", "limit-30-unlocked", "unlock-wrong-host", "limit-group"],
)
def test_guard_verdicts(tmp_path: Path, limit: str | None, extra: list[str], ok: dict[str, bool]) -> None:
    """Explicit --limit required; hermes-30 refused unless unlocked by its own name."""
    task = {k: v for k, v in guard_task().items() if k != "tags"}
    (tmp_path / "play.yml").write_text(
        yaml.safe_dump([{"hosts": "hermes", "connection": "local", "gather_facts": False, "tasks": [task]}])
    )
    (tmp_path / "inventory.yml").write_text(
        yaml.safe_dump(
            {"all": {"children": {"hermes": {"hosts": {"hermes-30": {"hermes_deploy_locked": True}, "hermes-31": {}}}}}}
        )
    )
    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    argv = [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "inventory.yml", "play.yml"]
    argv += ["-e", f"ansible_python_interpreter={sys.executable}", *extra]
    if limit:
        argv += ["--limit", limit]
    result = subprocess.run(
        argv, cwd=tmp_path, env={**os.environ, "ANSIBLE_CONFIG": str(tmp_path / "ansible.cfg"), "ANSIBLE_NOCOLOR": "1"},
        capture_output=True, text=True, check=False,
    )
    lines = {line.split()[0]: line for line in result.stdout.splitlines() if " : ok=" in line}
    assert set(lines) == set(ok), result.stdout
    for host, passed in ok.items():
        assert ("failed=0" in lines[host]) is passed, lines[host]


# --- hermes_checks: multiplex and per-profile Telegram verdicts ---------------------------


def root_state(pid: int = 4242, start: float = 1.5, served: list[str] | None = None, **platforms: str) -> dict:
    """A root gateway_state.json as the v0.22 multiplexer writes it."""
    return {
        "pid": pid,
        "start_time": start,
        "gateway_state": "running",
        "served_profiles": ["default", *NAMES] if served is None else served,
        "platforms": {
            key: {"state": state, "writer_pid": pid, "writer_start_time": start} for key, state in platforms.items()
        },
    }


UP = "up (pid 4242 pgid 4242) 30 seconds"
DOWN = "down (not started yet)"
ALL = {"default", *NAMES}


@pytest.mark.parametrize(
    ("statuses", "state", "expected"),
    [
        ({"gateway-default": UP} | {f"gateway-{n}": DOWN for n in NAMES}, root_state(), "one multiplexed gateway"),
        ({"gateway-default": DOWN}, root_state(), "gateway-default not up"),
        ({"gateway-default": UP, "gateway-cafe-ia": "up (pid 77) 3 seconds"}, root_state(), "beside the multiplexer: gateway-cafe-ia"),
        ({"gateway-default": UP}, root_state(pid=99), "written by pid 99"),
        ({"gateway-default": UP}, root_state(served=["default", "cafe-ia"]), "served profiles"),
        ({"gateway-default": UP}, root_state(served=["default", *NAMES, "extra"]), "served profiles"),
        ({"gateway-default": UP}, None, "absent or malformed"),
    ],
    ids=["ok", "root-down", "named-slot-up", "stale-writer", "missing-profile", "extra-profile", "no-state"],
)
def test_multiplex_verdict(statuses: dict[str, str], state: Any, expected: str) -> None:
    """One root process, named slots down, served set exact."""
    ok, message = hc.multiplex_verdict(state, statuses, ALL, lambda _s: True)
    assert ok == expected.startswith("one multiplexed gateway")
    assert expected in message


def test_multiplex_verdict_refuses_a_dead_writer() -> None:
    """The recorded pid must be the live process s6 supervises."""
    ok, message = hc.multiplex_verdict(root_state(), {"gateway-default": UP}, ALL, lambda _s: False)
    assert not ok and "dead process" in message


@pytest.mark.parametrize(
    ("key", "platforms", "expected"),
    [
        ("cafe-ia:telegram", {"telegram": "connected", "cafe-ia:telegram": "connected"}, "cafe-ia:telegram connected"),
        ("cafe-ia:telegram", {"telegram": "connected"}, "no cafe-ia:telegram entry"),
        ("job-search:telegram", {"job-search:telegram": "retrying"}, "job-search:telegram state is 'retrying'"),
        ("telegram", {"cafe-ia:telegram": "connected"}, "no telegram entry"),
    ],
    ids=["profile-connected", "profile-absent", "profile-retrying", "default-is-not-a-profile-entry"],
)
def test_telegram_verdict_per_multiplexed_profile(key: str, platforms: dict[str, str], expected: str) -> None:
    """A profile is judged on ITS entry of the root state; default's entry never stands in for it."""
    ok, message = hc.telegram_verdict(root_state(**platforms), UP, lambda _s: True, key)
    assert ok == expected.endswith("connected")
    assert expected in message


def test_telegram_verdict_rejects_a_profile_entry_from_a_previous_process() -> None:
    """A `<profile>:telegram` entry written by an earlier root process is not trusted."""
    state = root_state(**{"cafe-ia:telegram": "connected"})
    state["platforms"]["cafe-ia:telegram"]["writer_pid"] = 1
    ok, message = hc.telegram_verdict(state, UP, lambda _s: True, "cafe-ia:telegram")
    assert not ok and "left over" in message


# --- Task files (static) -------------------------------------------------------------------

SHARED = (
    "Create the profile",
    "Read the stock SOUL.md checksum",
    "Seed the SOUL.md",
    "Deploy the owned content",
    "Read the config keys",
    "Set the config keys",
    "Verify that API_SERVER_KEY",
    "Verify that the declared tool restrictions",
)


def by_prefix(tasks: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    """The single task whose name starts with `prefix`."""
    found = [t for t in tasks if t.get("name", "").startswith(prefix)]
    assert len(found) == 1, prefix
    return found[0]


@pytest.mark.parametrize("prefix", SHARED)
def test_multiplex_profile_shares_the_deployed_tasks(prefix: str) -> None:
    """Creation, content, config and checks are the very tasks of profile.yml (hermes-30's path)."""
    multiplex, standalone = tasks_of(TASKS / "profile_multiplex.yml"), tasks_of(TASKS / "profile.yml")
    assert by_prefix(multiplex, prefix) == by_prefix(standalone, prefix)


def test_multiplex_profile_writes_the_token_last_after_every_check() -> None:
    """Checks and getMe first; the .env (token) after them; then only the restart flag."""
    names = names_of(TASKS / "profile_multiplex.yml")
    pin = next(i for i, n in enumerate(names) if n.startswith("Pin the .env keys"))
    for prefix in ("Set the config keys", "Verify that API_SERVER_KEY", "Verify that the declared tool", "Verify that the token belongs"):
        assert next(i for i, n in enumerate(names) if n.startswith(prefix)) < pin, prefix
    assert names[pin + 1:] == ["Schedule one restart of the multiplexed gateway ({{ hermes_profile.name }})"]


def test_multiplex_profile_has_no_per_profile_gateway_action() -> None:
    """No s6 slot, no start/restart, no profile port: none exists under multiplex."""
    text = (TASKS / "profile_multiplex.yml").read_text()
    for absent in ("s6-svstat", "gateway\n      - start", "wait_for", "api_server_port }}", "- listen", "- restart"):
        assert absent not in text, absent
    env = by_prefix(tasks_of(TASKS / "profile_multiplex.yml"), "Pin the .env keys")
    keys = env["vars"]["hermes_env_keys"]
    assert "hermes_profile.telegram_bot_token if hermes_telegram_enabled else ''" in keys
    assert "'API_SERVER_PORT': ''" in keys


def test_multiplex_getme_reads_the_token_from_stdin_without_logging() -> None:
    """Reuses candidate_bot_identity.yml: token on stdin, no_log, skipped while Telegram is off."""
    task = by_prefix(tasks_of(TASKS / "profile_multiplex.yml"), "Verify that the token belongs")
    assert task["ansible.builtin.include_tasks"] == "candidate_bot_identity.yml"
    assert "hermes_telegram_enabled" in task["when"]
    ask = tasks_of(TASKS / "candidate_bot_identity.yml")[0]
    argv = ask["ansible.builtin.command"]["argv"]
    assert ask["no_log"] is True and argv[argv.index("bot-identity") + 1] == "-"
    assert "stdin" in ask["ansible.builtin.command"]


def test_main_orders_the_multiplex_block_after_the_profiles() -> None:
    """Profiles, one restart, API, topology, then Telegram for the four: all gated on multiplex."""
    tasks = tasks_of(TASKS / "main.yml")
    names = [t.get("name", "") for t in tasks]
    order = [
        "Deploy the additional Hermes profiles (multiplexed gateway)",
        "Restart the multiplexed gateway once with the final profile configuration",
        "Wait for the multiplexed gateway API to listen",
        "Verify that the multiplexed gateway API listens on loopback only",
        "Verify that one multiplexed gateway serves every profile",
        "Wait until Telegram is connected for every multiplexed profile (levels 2-3)",
    ]
    assert [names.index(n) for n in order] == sorted(names.index(n) for n in order)
    for name in order:
        when = tasks[names.index(name)]["when"]
        assert "hermes_gateway_multiplex" in (when if isinstance(when, list) else [when]), name


def test_main_keeps_the_per_slot_checks_for_hermes_30_only() -> None:
    """The v0.20.4 path (profiles.yml, per-slot default checks) is skipped under multiplex, unchanged otherwise."""
    tasks = {t.get("name", ""): t for t in tasks_of(TASKS / "main.yml")}
    for name in (
        "Wait until the default gateway is up and Telegram connected (levels 2-3)",
        "Verify that the default gateway survived the profiles (levels 2-3)",
        "Deploy the additional Hermes profiles",
    ):
        assert "not hermes_gateway_multiplex" in tasks[name]["when"], name
    assert tasks["Deploy the additional Hermes profiles"]["ansible.builtin.include_tasks"] == "profiles.yml"


# --- Rendered templates ----------------------------------------------------------------------


def render(tmp_path: Path, template: str, variables: dict[str, Any]) -> str:
    """Render one role template with the real template module on localhost."""
    dest = tmp_path / f"out-{template}"
    play = tmp_path / "render.yml"
    play.write_text(
        yaml.safe_dump(
            [{"hosts": "localhost", "connection": "local", "gather_facts": False,
              "tasks": [{"ansible.builtin.template": {"src": str(ROLE / "templates" / template), "dest": str(dest)}}]}]
        )
    )
    (tmp_path / "vars.json").write_text(json.dumps({"ansible_python_interpreter": sys.executable, **variables}))
    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(play), "-e", "@vars.json"],
        cwd=tmp_path, env={**os.environ, "ANSIBLE_CONFIG": str(tmp_path / "ansible.cfg")},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return dest.read_text()


COMPOSE_VARS = {k: DEFAULTS[k] for k in (
    "hermes_image", "hermes_data_dir", "hermes_managed_dir", "hermes_ca_bundle", "hermes_puid", "hermes_pgid",
    "hermes_memory_limit", "hermes_cpu_limit", "hermes_dashboard_port")}


@pytest.mark.parametrize("host", ["hermes-30", "hermes-31"])
def test_compose_renders_one_gateway_and_the_separate_dashboard(tmp_path: Path, host: str) -> None:
    """Same compose for both hosts: `gateway run` + dashboard container; only the tag differs."""
    tag = HOST_31["hermes_image_tag"] if host == "hermes-31" else DEFAULTS["hermes_image_tag"]
    compose = yaml.safe_load(render(tmp_path, "docker-compose.yml.j2", COMPOSE_VARS | {"hermes_image_tag": tag}))
    services = compose["services"]
    assert set(services) == {"gateway", "dashboard"}
    assert {s["image"] for s in services.values()} == {f"nousresearch/hermes-agent:{tag}"}
    assert services["gateway"]["command"] == ["gateway", "run"]
    assert services["dashboard"]["command"][0] == "dashboard"
    assert all(s["network_mode"] == "host" for s in services.values())


# --- Real profile_multiplex.yml against a fake container ---------------------------------

FAKE_DOCKER = r'''#!/usr/bin/env python3
"""Fake `docker exec ... hermes`: profile create, `-p <name> config get/set`, checks; logs every call."""
import hashlib, json, os, sys
from pathlib import Path
import yaml
data = Path(os.environ["FAKE_DATA"])
stdin = sys.stdin.read() if "-i" in sys.argv[1:4] else ""
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "stdin_sha": hashlib.sha256(stdin.strip().encode()).hexdigest() if stdin else None}) + "\n")
args = sys.argv[2:]
while args and args[0] in ("-u", "-e", "-i"):
    args = args[1:] if args[0] == "-i" else args[2:]
cmd = args[1:]
if cmd[:3] == ["hermes", "profile", "create"]:
    home = data / "profiles" / cmd[3]
    home.mkdir(parents=True)
    (home / "SOUL.md").write_text("STOCK SOUL\n")
elif cmd[:2] == ["hermes", "-p"] and cmd[3] == "config":
    cfg_path = (data if cmd[2] == "default" else data / "profiles" / cmd[2]) / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    op, key = cmd[4], cmd[5]
    node = cfg
    *parents, leaf = key.split(".")
    if op == "get":
        for p in parents:
            node = node.get(p) if isinstance(node, dict) else None
        if not isinstance(node, dict) or leaf not in node:
            sys.exit(1)
        print(json.dumps(node[leaf]))
        sys.exit(0)
    try:
        value = json.loads(cmd[6])
    except ValueError:
        value = cmd[6]
    for p in parents:
        node = node.setdefault(p, {})
    node[leaf] = value
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
elif cmd[:1] == ["python3"]:
    if "DEFAULT_SOUL_MD" in cmd[2]:
        print(hashlib.sha256(b"STOCK SOUL\n").hexdigest())
    elif "bot-identity" in cmd:
        print(f"token belongs to @{cmd[-1]}")
    else:
        print("ok")
else:
    sys.exit(f"unexpected: {cmd}")
'''


@pytest.fixture
def fake_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """A fake docker on PATH and an empty data directory (fresh hermes-31)."""
    bindir, data = tmp_path / "bin", tmp_path / "data"
    bindir.mkdir()
    data.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
    (bindir / "docker").chmod(0o755)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_DATA", str(data))
    yield {"data": data, "log": log}


def cafe_ia() -> dict[str, Any]:
    """Kaféine as hermes-31 resolves it, fake token and Tavily key."""
    decl = GROUP_VARS["hermes_profile_cafe_ia"]
    return decl | {
        "telegram_bot_token": FAKE_TOKEN,
        "env": {"TAVILY_API_KEY": "tvly-FAKE-cafe"},
        "config": decl["config"] | overlay(),
    }


def apply_profile(run: RunTasks, host: dict[str, Any], telegram: bool, *extra: str) -> Any:
    """Run the real profile_multiplex.yml for Kaféine against the fake container."""
    return run(
        "profile_multiplex.yml",
        {"hermes_profile": cafe_ia(), "hermes_data_dir": str(host["data"]), "hermes_telegram_enabled": telegram},
        *extra,
    )


def logged(host: dict[str, Any]) -> list[dict[str, Any]]:
    """Calls made to the fake docker, in order."""
    return [json.loads(x) for x in host["log"].read_text().splitlines()] if host["log"].exists() else []


def test_fake_phase1_configures_everything_and_writes_no_token(run_tasks: RunTasks, fake_host: dict[str, Any]) -> None:
    """Telegram off: profile, SOUL, config (overlay included) and Tavily key, no token, no port, no getMe."""
    result = apply_profile(run_tasks, fake_host, False, "-v")
    assert result.returncode == 0, result.stdout
    home = fake_host["data"] / "profiles/cafe-ia"
    env = (home / ".env").read_text()
    assert "TAVILY_API_KEY=tvly-FAKE-cafe" in env
    assert "TELEGRAM_BOT_TOKEN" not in env and "API_SERVER_PORT" not in env
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["tools"]["tool_search"]["enabled"] == "off"
    assert cfg["platform_toolsets"]["telegram"] == cafe_ia()["config"]["platform_toolsets.telegram"]
    assert (home / "SOUL.md").read_text() == (ROLE / "files/profiles/cafe-ia/SOUL.md").read_text()
    assert not [c for c in logged(fake_host) if "bot-identity" in c["argv"]]
    assert '"hermes_multiplex_restart": true' in result.stdout
    assert not [c for c in logged(fake_host) if "gateway" in c["argv"]]


def test_fake_phase2_getme_on_stdin_before_the_token_is_written(run_tasks: RunTasks, fake_host: dict[str, Any]) -> None:
    """Telegram on: getMe gets the token on stdin while no .env holds it yet; the token is never printed."""
    assert apply_profile(run_tasks, fake_host, telegram=False).returncode == 0
    fake_host["log"].unlink()
    result = apply_profile(run_tasks, fake_host, True, "-vvv")
    assert result.returncode == 0, result.stdout
    getme = [c for c in logged(fake_host) if "bot-identity" in c["argv"]]
    assert len(getme) == 1 and getme[0]["argv"][-2:] == ["-", "kafeine_r64gnb_bot"]
    assert getme[0]["stdin_sha"] == hashlib.sha256(FAKE_TOKEN.encode()).hexdigest()
    assert f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}" in (fake_host["data"] / "profiles/cafe-ia/.env").read_text()
    assert FAKE_TOKEN not in result.stdout + result.stderr


def test_fake_second_run_changes_nothing_and_schedules_no_restart(run_tasks: RunTasks, fake_host: dict[str, Any]) -> None:
    """Converged: 0 changed, no `config set`, no restart flag."""
    assert apply_profile(run_tasks, fake_host, telegram=True).returncode == 0
    fake_host["log"].unlink()
    second = apply_profile(run_tasks, fake_host, True, "-v")
    assert second.returncode == 0, second.stdout
    assert recap(second)["changed"] == 0
    assert not [c for c in logged(fake_host) if "set" in c["argv"]]
    assert "hermes_multiplex_restart" not in second.stdout


def test_fake_check_mode_touches_nothing(run_tasks: RunTasks, fake_host: dict[str, Any]) -> None:
    """--check on a fresh host: no docker exec, no file."""
    result = apply_profile(run_tasks, fake_host, True, "--check")
    assert result.returncode == 0, result.stdout
    assert logged(fake_host) == []
    assert list(fake_host["data"].iterdir()) == []


# --- Effective inventory (vault) -------------------------------------------------------------

EFFECTIVE = r"""{% set ns = namespace(ts=[]) %}{% for p in hermes_profiles + [hermes_default_profile] %}{% set ns.ts = ns.ts + [p.config.get('tools.tool_search.enabled', 'ABSENT')] %}{% endfor %}{{ {
 'image': hermes_image ~ ':' ~ hermes_image_tag, 'multiplex': hermes_gateway_multiplex,
 'telegram': hermes_telegram_enabled, 'profiles': hermes_profiles | map(attribute='name') | list,
 'tool_search': ns.ts,
 'tokens_distinct': ([hermes_telegram_bot_token] + hermes_profiles | map(attribute='telegram_bot_token') | list) | select | unique | list | length == 4,
 'tavily_distinct': ([hermes_default_profile.env.TAVILY_API_KEY] + hermes_profiles | map(attribute='env') | map(attribute='TAVILY_API_KEY') | list) | select | unique | list | length == 4,
 'same_as_30': hermes_profiles | map(attribute='config') | map('dict2items') | map('rejectattr', 'key', 'eq', 'tools.tool_search.enabled') | map('items2dict') | list
   == hostvars['hermes-30'].hermes_profiles | map(attribute='config') | list,
 'nora_same_as_30': (hermes_default_profile.config | dict2items | rejectattr('key', 'eq', 'tools.tool_search.enabled') | items2dict)
   == hostvars['hermes-30'].hermes_default_profile.config,
 'soul_predecessor': hermes_default_profile.soul_predecessor_sha256,
 'allowlist': hermes_telegram_allowed_users} | to_json }}"""


@pytest.fixture(scope="module")
def effective(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """Both hosts as Ansible resolves them, after the role's real validate.yml; prints no secret."""
    tmp = tmp_path_factory.mktemp("effective")
    (tmp / "probe.j2").write_text(EFFECTIVE)
    (tmp / "play.yml").write_text(
        yaml.safe_dump(
            [{"hosts": "hermes", "connection": "local", "gather_facts": False, "tasks": [
                {"ansible.builtin.include_role": {"name": "hermes_agent", "tasks_from": "validate.yml", "public": True}},
                {"ansible.builtin.debug": {"msg": "EFFECTIVE {{ lookup('ansible.builtin.template', '%s') }}" % (tmp / "probe.j2")}},
            ]}]
        )
    )
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), str(tmp / "play.yml"),
         "-e", f"ansible_python_interpreter={sys.executable}"],
        cwd=REPO / "hermes",
        env={**os.environ, "ANSIBLE_ROLES_PATH": str(ROLE.parent), "ANSIBLE_NOCOLOR": "1"},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0 and "ecrypt" in result.stdout + result.stderr:
        pytest.skip("vault password unavailable: effective inventory not resolvable here")
    assert result.returncode == 0, result.stdout[-3000:]
    out, host = {}, None
    for line in result.stdout.splitlines():
        if line.startswith("ok: ["):
            host = line.split("[")[1].split("]")[0]
        if '"msg": "EFFECTIVE ' in line:
            out[host] = json.loads(json.loads(line.split('"msg": ', 1)[1]).removeprefix("EFFECTIVE "))
    return out


def test_effective_hermes_31(effective: dict[str, dict[str, Any]]) -> None:
    """v0.22.5, multiplexed, Telegram off, four profiles with tool_search off, distinct secrets."""
    e = effective["hermes-31"]
    assert e["image"] == "nousresearch/hermes-agent:v0.22.5"
    assert e["multiplex"] is True and e["telegram"] is False
    assert e["profiles"] == NAMES
    assert e["tool_search"] == ["off"] * 4
    assert e["tokens_distinct"] and e["tavily_distinct"]
    assert e["allowlist"] == ALLOWLIST
    assert e["soul_predecessor"] == V0225_STOCK_SOUL_SHA


def test_effective_hermes_31_differs_from_hermes_30_by_the_overlay_only(effective: dict[str, dict[str, Any]]) -> None:
    """Every identity, allowlist, tool and approval key equals hermes-30's; only tool_search is added."""
    assert effective["hermes-31"]["same_as_30"] is True
    assert effective["hermes-31"]["nora_same_as_30"] is True


def test_effective_hermes_30_unchanged(effective: dict[str, dict[str, Any]]) -> None:
    """hermes-30 still resolves to v0.20.4, standalone gateways, Telegram on, no v0.22 key."""
    e = effective["hermes-30"]
    assert e["image"] == "nousresearch/hermes-agent:v2026.8.18"
    assert e["multiplex"] is False and e["telegram"] is True
    assert e["profiles"] == NAMES
    assert e["tool_search"] == ["ABSENT"] * 4
    assert e["soul_predecessor"] == GROUP_VARS["hermes_default_soul_predecessor_sha256"]


# --- Lab: the real v0.22.5 image, offline ------------------------------------------------------

GW, DASH = "hermes-m63-lab-gw", "hermes-m63-lab-dash"


def _docker(*argv: str, stdin: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *argv], input=stdin, capture_output=True, text=True, timeout=timeout, check=False)


def _dx(*argv: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    flags = [x for k, v in (env or {}).items() for x in ("-e", f"{k}={v}")]
    return _docker("exec", "-u", str(os.getuid()), *flags, GW, *argv)


def _checks(*args: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    r = _dx("python3", "-c", (ROLE / "files/hermes_checks.py").read_text(), *args, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()


def _listening() -> list[tuple[str, int]]:
    """(address, port) of TCP listeners in the shared network namespace, from /proc/net/tcp{,6}."""
    found = []
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in _dx("cat", table).stdout.splitlines()[1:]:
            fields = line.split()
            if fields[3] != "0A":
                continue
            addr, port = fields[1].split(":")
            found.append((addr, int(port, 16)))
    return found


def _wait(predicate: Any, timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(3)
    return False


def _gateway_up() -> bool:
    return _dx("/command/s6-svstat", "/run/service/gateway-default").stdout.startswith("up") and any(
        p == DEFAULTS["hermes_gateway_port"] for _a, p in _listening()
    )


SCOPE_PROBE = r'''
import json, logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from agent.secret_scope import build_profile_secret_scope, set_secret_scope, reset_secret_scope, set_multiplex_context, reset_multiplex_context
from gateway.platforms._shared import platform_gate_env
out = {}
for name in ("default", "cafe-ia", "tech-watch", "job-search"):
    home = "/opt/data" if name == "default" else f"/opt/data/profiles/{name}"
    scope = build_profile_secret_scope(Path(home))
    t1 = set_multiplex_context(True); t2 = set_secret_scope(scope, profile_home=home)
    try:
        gate = {k: platform_gate_env(k) for k in ("TELEGRAM_ALLOWED_USERS", "TELEGRAM_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS", "GATEWAY_ALLOWED_USERS")}
    finally:
        reset_secret_scope(t2); reset_multiplex_context(t1)
    out[name] = {"gate": gate, "token_id": (scope.get("TELEGRAM_BOT_TOKEN") or "").split(":")[0], "tavily": scope.get("TAVILY_API_KEY")}
print(json.dumps(out))
'''

# The gateway's own authorization decision for an inbound Telegram DM, per profile runtime scope, multiplex on.
AUTHZ_PROBE = r'''
import json, logging, sys
logging.disable(logging.CRITICAL)
from pathlib import Path
from agent import secret_scope as ss
from gateway.config import Platform
from gateway.session import SessionSource
from gateway.run import GatewayRunner, _profile_runtime_scope
ss.set_multiplex_active(True)
runner = GatewayRunner.__new__(GatewayRunner)
runner.adapters, runner._profile_adapters, runner.config = {}, {}, None
out = {}
for name in ("default", "cafe-ia", "tech-watch", "job-search"):
    home = "/opt/data" if name == "default" else f"/opt/data/profiles/{name}"
    res = {}
    for uid in (sys.argv[1], "999", "123456"):
        src = SessionSource(platform=Platform.TELEGRAM, chat_id=uid, chat_type="dm", user_id=uid,
                            profile=None if name == "default" else name)
        with _profile_runtime_scope(Path(home)):
            res[uid] = runner._is_user_authorized(src)
            res["dm_behavior"] = runner._get_unauthorized_dm_behavior(Platform.TELEGRAM, profile=src.profile)
    out[name] = res
print(json.dumps(out))
'''

# Write-approval gates as the multiplexer evaluates them for a routed profile (home override contextvar).
APPROVAL_PROBE = r'''
import json, logging
logging.disable(logging.CRITICAL)
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from tools.write_approval import write_approval_enabled
out = {}
for name in ("default", "cafe-ia", "tech-watch", "job-search"):
    token = set_hermes_home_override("/opt/data" if name == "default" else f"/opt/data/profiles/{name}")
    try:
        out[name] = [write_approval_enabled("memory"), write_approval_enabled("skills")]
    finally:
        reset_hermes_home_override(token)
print(json.dumps(out))
'''

DASH_PROBE = r'''
import json, urllib.request, urllib.error
def call(path, data=None, cookie=None):
    req = urllib.request.Request("http://127.0.0.1:9119" + path, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(), r.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), []
out = {"profiles_anonymous": call("/api/profiles")[0]}
bad = call("/auth/password-login", {"provider": "basic", "username": "admin", "password": "wrong"})
out["login_bad"] = bad[0]
status, body, cookies = call("/auth/password-login", {"provider": "basic", "username": "admin", "password": "FAKE-dashboard-pass"})
out["login"] = status
cookie = "; ".join(c.split(";")[0] for c in cookies)
status, body, _ = call("/api/profiles", cookie=cookie)
out["profiles_status"] = status
try:
    data = json.loads(body)
    items = data.get("profiles", data) if isinstance(data, dict) else data
    out["profiles"] = sorted(p.get("name") for p in items if isinstance(p, dict))
except ValueError:
    out["profiles"] = body[:200]
out["status_version"] = json.loads(call("/api/status")[1]).get("version")
print(json.dumps(out))
'''


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """Run the M6.3.C phase-1/phase-2 shapes on the real v0.22.5 image, offline, and collect the facts."""
    docker = shutil.which("docker")
    if not docker or _docker("image", "inspect", IMAGE).returncode != 0:
        pytest.skip(f"{IMAGE} not available locally")
    tmp = tmp_path_factory.mktemp("m63lab")
    data, managed = tmp / "data", tmp / "managed"
    data.mkdir()
    managed.mkdir(mode=0o750)
    # The real managed templates, rendered by the template module with fake secrets.
    variables = {k: DEFAULTS[k] for k in (
        "hermes_provider_name", "hermes_provider_display_name", "hermes_provider_base_url", "hermes_provider_key_env",
        "hermes_model_default", "hermes_dashboard_public_url", "hermes_gateway_port", "hermes_dashboard_username",
        "hermes_pgid")} | {
        "hermes_managed_dir": "/etc/hermes", "hermes_deepseek_api_key": "sk-FAKE",
        "hermes_api_server_key": "FAKE-api-server-key-0123456789", "hermes_dashboard_password": "FAKE-dashboard-pass",
        "hermes_dashboard_secret": "FAKE-dashboard-secret-0123456789abcdef", "hermes_telegram_allowed_users": ALLOWLIST,
    }
    render_dir = tmp / "render"
    render_dir.mkdir()
    for template, dest in (("config.yaml.j2", "config.yaml"), ("hermes.env.j2", ".env")):
        (managed / dest).write_text(render(render_dir, template, variables))
        (managed / dest).chmod(0o640)
    facts: dict[str, Any] = {}
    for c in (DASH, GW):
        _docker("rm", "-f", c)
    try:
        run = _docker("run", "-d", "--name", GW, "--network", "none", "-v", f"{data}:/opt/data",
                      "-v", f"{managed}:/etc/hermes:ro", "-e", f"PUID={os.getuid()}", "-e", f"PGID={os.getgid()}",
                      IMAGE, "gateway", "run")
        assert run.returncode == 0, run.stderr
        assert _wait(_gateway_up), _docker("logs", GW).stdout[-3000:]
        facts["boot_first"] = (data / "logs/container-boot.log").read_text()
        facts["seeded_soul_sha"] = hashlib.sha256((data / "SOUL.md").read_bytes()).hexdigest()

        configs = effective_configs()
        # The stock checksum exactly as profile.yml / profile_multiplex.yml read it.
        facts["stock_soul_sha"] = _dx("python3", "-c", next(
            t for t in tasks_of(TASKS / "profile_multiplex.yml") if t["name"].startswith("Read the stock SOUL.md")
        )["ansible.builtin.command"]["argv"][-1]).stdout.strip()
        for name in NAMES:
            r = _dx("hermes", "profile", "create", name, "--no-alias")
            assert r.returncode == 0, r.stdout + r.stderr
            facts.setdefault("created_soul_sha", {})[name] = hashlib.sha256(
                (data / f"profiles/{name}/SOUL.md").read_bytes()
            ).hexdigest()
            shutil.copyfile(ROLE / f"files/profiles/{name}/SOUL.md", data / f"profiles/{name}/SOUL.md")
        facts["set"] = {}
        for name, cfg in configs.items():
            for key, value in cfg.items():
                r = _dx("hermes", "-p", name, "config", "set", key, hp.hermes_config_arg(value))
                facts["set"][f"{name}:{key}"] = r.returncode
            facts.setdefault("get", {})[name] = {
                key: _dx("hermes", "-p", name, "config", "get", key, "--json").stdout.strip() for key in cfg
            }
        # Phase 1: Tavily keys only, as profile_multiplex.yml writes them with Telegram off.
        for name in ["default", *NAMES]:
            env = data / ".env" if name == "default" else data / f"profiles/{name}/.env"
            env.write_text((env.read_text() if env.exists() else "") + f"\nTAVILY_API_KEY=tvly-FAKE-{name}\n")
        facts["managed"] = _checks("managed", ALLOWLIST)
        for name, cfg in configs.items():
            home = "/opt/data" if name == "default" else f"/opt/data/profiles/{name}"
            allowed = [t for t in cfg["platform_toolsets.telegram"] if t != "no_mcp"]
            facts.setdefault("toolsets", {})[name] = _checks(
                "toolsets", ",".join(allowed), ",".join(cfg["agent.disabled_toolsets"]), "true", env={"HERMES_HOME": home}
            )
            if name != "default":
                facts.setdefault("api_key", {})[name] = _checks("api-key", f"{home}/.env", env={"HERMES_HOME": home})
        # Without the overlay key, the same check on v0.22.5 (C3 of M6.1).
        _dx("hermes", "-p", "cafe-ia", "config", "set", "tools.tool_search.enabled", "auto")
        allowed = [t for t in configs["cafe-ia"]["platform_toolsets.telegram"] if t != "no_mcp"]
        facts["toolsets_auto"] = _checks(
            "toolsets", ",".join(allowed), ",".join(configs["cafe-ia"]["agent.disabled_toolsets"]), "true",
            env={"HERMES_HOME": "/opt/data/profiles/cafe-ia"},
        )
        _dx("hermes", "-p", "cafe-ia", "config", "set", "tools.tool_search.enabled", "off")

        facts["named_start"] = _dx("hermes", "-p", "cafe-ia", "gateway", "start").returncode
        facts["root_restart"] = _dx("hermes", "-p", "default", "gateway", "restart").returncode
        # Same order as main.yml: API listening first, then the topology check.
        facts["api_after_restart"] = _wait(_gateway_up)
        expected = ",".join(["default", *NAMES])
        facts["multiplex_ok"] = _wait(lambda: _checks("multiplex", "/opt/data/gateway_state.json", expected)[0] == 0, 120)
        facts["multiplex"] = _checks("multiplex", "/opt/data/gateway_state.json", expected)
        facts["listen"] = sorted(set(_listening()))
        facts["ps"] = _dx("ps", "-eo", "pid,args").stdout
        facts["gateway_processes"] = sum(
            " gateway run" in line for line in facts["ps"].splitlines() if "hermes_cli.main" in line
        )
        facts["phase1_telegram_entries"] = sorted(
            k for k in json.loads((data / "gateway_state.json").read_text()).get("platforms", {}) if "telegram" in k
        )

        # Phase 2 shape: one fake token per profile; cafe-ia's .env also tries to widen its access.
        for name in ["default", *NAMES]:
            env = data / ".env" if name == "default" else data / f"profiles/{name}/.env"
            env.write_text(env.read_text() + f"TELEGRAM_BOT_TOKEN={TOKENS[name]}\n")
        hostile = data / "profiles/cafe-ia/.env"
        hostile.write_text(
            hostile.read_text() + "TELEGRAM_ALLOWED_USERS=999\nGATEWAY_ALLOW_ALL_USERS=true\nTELEGRAM_ALLOW_ALL_USERS=true\n"
        )
        r = _dx("python3", "-c", SCOPE_PROBE)
        facts["scopes"] = json.loads(r.stdout) if r.returncode == 0 else r.stderr
        r = _dx("python3", "-c", AUTHZ_PROBE, ALLOWLIST)
        facts["authz"] = json.loads(r.stdout) if r.returncode == 0 else r.stderr
        r = _dx("python3", "-c", APPROVAL_PROBE)
        facts["approval"] = json.loads(r.stdout) if r.returncode == 0 else r.stderr
        _dx("hermes", "-p", "default", "gateway", "restart")

        def entries() -> list[str]:
            try:
                state = json.loads((data / "gateway_state.json").read_text())
            except (OSError, ValueError):
                return []
            return sorted(k for k in state.get("platforms", {}) if "telegram" in k)

        _wait(lambda: len(entries()) == 4, 240)
        facts["phase2_telegram_entries"] = entries()
        facts["telegram_checks"] = {
            key: _checks("telegram", "/opt/data/gateway_state.json", "gateway-default", key)
            for key in ["telegram", *(f"{n}:telegram" for n in NAMES)]
        }

        restart = _docker("restart", GW)
        assert restart.returncode == 0, restart.stderr
        assert _wait(_gateway_up)
        facts["after_restart_ok"] = _wait(
            lambda: _checks("multiplex", "/opt/data/gateway_state.json", expected)[0] == 0, 120
        )
        facts["boot_after_restart"] = (data / "logs/container-boot.log").read_text().splitlines()[-4:]

        dash = _docker("run", "-d", "--name", DASH, "--network", f"container:{GW}", "-v", f"{data}:/opt/data",
                       "-v", f"{managed}:/etc/hermes:ro", "-e", f"PUID={os.getuid()}", "-e", f"PGID={os.getgid()}",
                       IMAGE, "dashboard", "--host", "0.0.0.0", "--port", str(DEFAULTS["hermes_dashboard_port"]), "--no-open")
        assert dash.returncode == 0, dash.stderr
        assert _wait(lambda: any(p == DEFAULTS["hermes_dashboard_port"] for _a, p in _listening()), 120)
        r = _docker("exec", "-u", str(os.getuid()), DASH, "python3", "-c", DASH_PROBE)
        facts["dashboard"] = json.loads(r.stdout) if r.returncode == 0 else r.stderr
        facts["dashboard_log"] = _docker("logs", DASH).stdout
        yield facts
    finally:
        for c in (DASH, GW):
            _docker("rm", "-f", c)


LOOPBACK_V4 = "0100007F"


def test_lab_image_is_v0225(lab: dict[str, Any]) -> None:
    """The lab ran the tag pinned for hermes-31."""
    assert lab["dashboard"]["status_version"] == "0.22.5"


def test_lab_fresh_container_starts_the_root_gateway(lab: dict[str, Any]) -> None:
    """`gateway run` with no state: the root slot is seeded and started at the first boot."""
    assert "profile=default prior_state=running action=started" in lab["boot_first"]


def test_lab_fresh_default_soul_is_the_declared_predecessor(lab: dict[str, Any]) -> None:
    """default_soul.yml will find exactly the predecessor declared for hermes-31, and replace it once."""
    assert lab["seeded_soul_sha"] == HOST_31["hermes_default_soul_predecessor_sha256"]


def test_lab_profile_create_writes_the_stock_soul_the_role_seeds_over(lab: dict[str, Any]) -> None:
    """soul_seed.yml replaces only the stock text: v0.22.5's `profile create` writes exactly it."""
    assert set(lab["created_soul_sha"].values()) == {lab["stock_soul_sha"]}


def test_lab_every_declared_key_applies_and_reads_back(lab: dict[str, Any]) -> None:
    """All four declarations (overlay included) are accepted by v0.22.5 and read back equal."""
    assert set(lab["set"].values()) == {0}, {k: v for k, v in lab["set"].items() if v}
    for name, cfg in effective_configs().items():
        for key, value in cfg.items():
            assert hp.hermes_config_equal(lab["get"][name][key], value), f"{name}:{key}"


def test_lab_managed_contract_holds(lab: dict[str, Any]) -> None:
    """The rendered managed layer passes the role's own contract check on v0.22.5."""
    assert lab["managed"][0] == 0, lab["managed"]


@pytest.mark.parametrize("name", ["default", *NAMES])
def test_lab_tool_surface_is_the_v0204_one(lab: dict[str, Any], name: str) -> None:
    """With tool_search off: exactly the allowed toolsets and the same tools as on v0.20.4, no bridge tool."""
    rc, out = lab["toolsets"][name]
    assert rc == 0, out
    tools = set(out.split(" | tools: ")[1].split(", "))
    assert tools == (NORA_TOOLS if name == "default" else NINE_TOOLS)
    assert not tools & BRIDGE_TOOLS


def test_lab_without_the_overlay_the_check_refuses_the_bridge(lab: dict[str, Any]) -> None:
    """tool_search on (v0.22 default): three new tools, session_search/todo_list deferred — the deploy check stops."""
    rc, out = lab["toolsets_auto"]
    assert rc == 1
    assert "tools beyond the allowlist: tool_call, tool_describe, tool_search" in out
    assert "allowed tools not exposed: session_search, todo_list" in out


@pytest.mark.parametrize("name", NAMES)
def test_lab_api_key_comes_from_managed_only(lab: dict[str, Any], name: str) -> None:
    """No API_SERVER_KEY seeded into a profile .env by v0.22.5's stage2 hook."""
    assert lab["api_key"][name][0] == 0, lab["api_key"][name]


def test_lab_one_multiplexed_gateway_serves_the_four_profiles(lab: dict[str, Any]) -> None:
    """Root slot up, named slots down, served_profiles exact, one gateway process."""
    assert lab["api_after_restart"] and lab["multiplex_ok"], lab["multiplex"]
    assert lab["gateway_processes"] == 1, lab["ps"]


def test_lab_only_the_root_api_listens_and_on_loopback(lab: dict[str, Any]) -> None:
    """8642 on 127.0.0.1 only; nothing on the reserved profile ports 8643/8645/8646."""
    gateway_port = DEFAULTS["hermes_gateway_port"]
    assert {a for a, p in lab["listen"] if p == gateway_port} == {LOOPBACK_V4}
    reserved = set(GROUP_VARS["hermes_profile_reserved_ports"].values())
    assert not {p for _a, p in lab["listen"] if p in reserved}


def test_lab_named_gateway_start_is_refused(lab: dict[str, Any]) -> None:
    """`hermes -p <name> gateway start` exits 78 under multiplex: profile.yml's path cannot work here."""
    assert lab["named_start"] == 78
    assert lab["root_restart"] == 0


def test_lab_phase1_connects_no_bot(lab: dict[str, Any]) -> None:
    """Without tokens, no Telegram adapter exists for any profile."""
    assert lab["phase1_telegram_entries"] == []


@pytest.mark.parametrize("name", ["default", *NAMES])
def test_lab_managed_allowlist_governs_every_profile_scope(lab: dict[str, Any], name: str) -> None:
    """The scope the multiplexer builds for each profile carries the managed allowlist and closed switches,
    even when the profile .env sets its own (cafe-ia); each profile keeps its own token and Tavily key."""
    scope = lab["scopes"][name]
    assert scope["gate"] == {
        "TELEGRAM_ALLOWED_USERS": ALLOWLIST,
        "TELEGRAM_ALLOW_ALL_USERS": "false",
        "GATEWAY_ALLOW_ALL_USERS": "false",
        "GATEWAY_ALLOWED_USERS": "",
    }
    assert scope["token_id"] == TOKENS[name].split(":")[0]
    assert scope["tavily"] == f"tvly-FAKE-{name}"


@pytest.mark.parametrize("name", ["default", *NAMES])
def test_lab_gateway_authorizes_the_allowlisted_user_only(lab: dict[str, Any], name: str) -> None:
    """The gateway's real decision: the managed id in, anyone else out — including the id cafe-ia's own .env
    tries to allow with both allow-all switches on — and unknown senders ignored (no pairing code)."""
    assert lab["authz"][name] == {ALLOWLIST: True, "999": False, "123456": False, "dm_behavior": "ignore"}


def test_lab_write_approval_is_per_profile(lab: dict[str, Any]) -> None:
    """Nora keeps memory AND skills approval; the others keep skills approval only: nothing crosses profiles."""
    assert lab["approval"] == {
        "default": [True, True],
        "cafe-ia": [False, True],
        "tech-watch": [False, True],
        "job-search": [False, True],
    }


def test_lab_each_bot_is_reported_under_its_own_profile_key(lab: dict[str, Any]) -> None:
    """One root state, one entry per bot: `telegram` (default) and `<profile>:telegram`."""
    assert lab["phase2_telegram_entries"] == sorted(["telegram", *(f"{n}:telegram" for n in NAMES)])
    for key, (rc, out) in lab["telegram_checks"].items():
        # Offline: the adapters exist but cannot connect; the verdict names the right entry.
        assert rc == 1 and f"{key} state is" in out, (key, out)


def test_lab_container_restart_keeps_one_gateway(lab: dict[str, Any]) -> None:
    """Boot reconcile: root started, named slots registered down, the four still served."""
    assert lab["after_restart_ok"]
    assert "profile=default prior_state=running action=started" in lab["boot_after_restart"][0]
    assert all("action=registered" in line for line in lab["boot_after_restart"][1:])


def test_lab_dashboard_runs_beside_the_multiplexer(lab: dict[str, Any]) -> None:
    """Separate container: skips the reconcile, logs in with the managed credentials, lists the four profiles."""
    assert "reconcile: skipping (dashboard container" in lab["dashboard_log"]
    d = lab["dashboard"]
    assert d["profiles_anonymous"] == 401 and d["login_bad"] == 401
    assert d["login"] == 200 and d["profiles_status"] == 200
    assert d["profiles"] == sorted(["default", *NAMES])
