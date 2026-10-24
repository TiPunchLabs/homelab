"""Inventory and static guards for the M1 foundation.

T15 (cafe-ia alone deployed, M2 phase B), T16 (definitive ids), static halves of T17/T18,
and the M1 non-goals: no timezone (D1), no toolsets (D5), no MCP in managed.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import FAKE_TOKEN, FAKE_TOKEN_2, REPO, ROLE, RunTasks

HERMES = REPO / "hermes"
GROUP_VARS = HERMES / "ansible/group_vars/hermes/all/main.yml"
TASKS = sorted((ROLE / "tasks").glob("*.yml"))
TEMPLATES = ROLE / "templates"
FUTURE_IDS = {"tech-watch", "daily-life", "job-search", "cafe-ia"}


@pytest.fixture(scope="module")
def group_vars() -> dict[str, Any]:
    """The hermes group_vars, as written (vault references left unresolved)."""
    return yaml.safe_load(GROUP_VARS.read_text())


def iter_tasks(node: Any) -> list[dict[str, Any]]:
    """Flatten tasks, descending into block/rescue/always."""
    found: list[dict[str, Any]] = []
    for task in node or []:
        found.append(task)
        for key in ("block", "rescue", "always"):
            found += iter_tasks(task.get(key))
    return found


ALL_TASKS = [(path.name, task) for path in TASKS for task in iter_tasks(yaml.safe_load(path.read_text()))]


# --- T15 --------------------------------------------------------------------


def test_t15_group_vars_declare_cafe_ia_tech_watch_then_job_search(group_vars: dict[str, Any]) -> None:
    """T15 (M4.3): the inventory itself pins cafe-ia, tech-watch then job-search, by reference to their declarations."""
    assert "hermes_profiles" in group_vars
    assert group_vars["hermes_profiles"] == [
        "{{ hermes_profile_cafe_ia }}",
        "{{ hermes_profile_tech_watch }}",
        "{{ hermes_profile_job_search }}",
    ]


def test_t15_effective_value_is_cafe_ia_tech_watch_then_job_search() -> None:
    """T15 (M4.3): the profiles Ansible actually resolves for hermes-30 are cafe-ia, tech-watch then job-search.

    Needs the vault password (pass) to load group_vars; skipped without it.
    Prints the profile names only: the resolved list carries the tokens.
    """
    ansible = Path(sys.executable).parent / "ansible"
    names = "{{ hermes_profiles | map(attribute='name') | list | to_json }}"
    result = subprocess.run(
        [str(ansible), "hermes", "-m", "ansible.builtin.debug", "-a", f"msg=PROFILES={names}"],
        cwd=HERMES,
        env={**os.environ, "ANSIBLE_NOCOLOR": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and re.search(r"[Vv]ault|[Dd]ecrypt|password", result.stdout + result.stderr):
        pytest.skip("vault password unavailable: effective inventory not resolvable here")
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"msg": "PROFILES=[\\"cafe-ia\\", \\"tech-watch\\", \\"job-search\\"]"' in result.stdout


# --- T16 --------------------------------------------------------------------


def test_t16_reserved_ports_use_definitive_ids(group_vars: dict[str, Any]) -> None:
    """T16: the four future profiles, by their definitive ids, on fixed ports."""
    assert group_vars["hermes_profile_reserved_ports"] == {
        "tech-watch": 8643,
        "daily-life": 8644,
        "job-search": 8645,
        "cafe-ia": 8646,
    }


def test_t16_tech_watch_is_prepared_not_active(group_vars: dict[str, Any]) -> None:
    """T16/D2: Néo is tech-watch, on its own vault keys and bot name, still out of the list."""
    neo = group_vars["hermes_profile_tech_watch"]
    assert neo["name"] == "tech-watch"
    assert neo["description"].startswith("Néo — ")
    assert neo["api_server_port"] == group_vars["hermes_profile_reserved_ports"]["tech-watch"]
    assert neo["telegram_bot_token"] == "{{ vault_hermes_tech_watch_telegram_bot_token }}"
    assert "hermes_tech_watch_telegram_bot_username" in neo["telegram_bot_username"]
    assert "telegram_allowed_users" not in neo
    assert neo not in group_vars["hermes_profiles"]


def test_t16_no_veille_identifier_left() -> None:
    """T16: no `veille` id in declarations, vault refs, file names or task paths."""
    assert not (ROLE / "files/profiles/veille").exists()
    offenders = []
    for path in [*(HERMES / "ansible").rglob("*.yml"), *(HERMES / "ansible").rglob("*.j2")]:
        if "vault" in path.parts:
            continue
        text = path.read_text()
        if re.search(
            r"vault_hermes_veille|name:\s*veille\b|profiles/veille|veille_(collect|daily|weekly|sources)", text
        ):
            offenders.append(str(path.relative_to(REPO)))
    # Tracked files only: a stale, git-ignored __pycache__ on a workstation is
    # neither committed nor deployed (hermes_profile_payload drops it).
    tracked = subprocess.run(
        ["git", "ls-files", str(ROLE)], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    assert offenders == []
    assert [path for path in tracked if "veille" in Path(path).name] == []


def test_t16_prepared_profile_passes_the_guards(run_tasks: RunTasks, group_vars: dict[str, Any]) -> None:
    """The prepared tech-watch definition is valid as is (fake token and bot name substituted)."""
    neo = group_vars["hermes_profile_tech_watch"] | {
        "telegram_bot_token": FAKE_TOKEN_2,
        "telegram_bot_username": "neo_FAKE00_bot",
    }
    neo["env"] = {"TAVILY_API_KEY": "fake"}
    result = run_tasks(
        "validate.yml",
        {
            "hermes_telegram_enabled": True,
            "hermes_telegram_bot_token": FAKE_TOKEN,
            "hermes_telegram_allowed_users": group_vars["hermes_telegram_allowed_users"],
            "hermes_profile_reserved_ports": group_vars["hermes_profile_reserved_ports"],
            "hermes_profiles": [neo],
        },
    )
    assert result.returncode == 0, result.stdout


# --- T17 / T18, static half -------------------------------------------------

DESTRUCTIVE = re.compile(r"\brm\b|\btrash\b|profile\s+delete|\bcron\b|\bunset\b|reset|--force")


def test_t17_no_destructive_task_in_the_role() -> None:
    """T17: no file removal, no rm, no cron/profile/config destruction anywhere."""
    for name, task in ALL_TASKS:
        file_args = task.get("ansible.builtin.file") or {}
        assert file_args.get("state") != "absent", f"{name}: {task.get('name')}"
        command = task.get("ansible.builtin.command") or task.get("ansible.builtin.shell") or {}
        argv = command.get("argv") if isinstance(command, dict) else command
        text = " ".join(map(str, argv)) if isinstance(argv, list) else str(argv or "")
        assert not DESTRUCTIVE.search(text), f"{name}: {task.get('name')}"


def test_t17_line_edits_only_in_env_keys() -> None:
    """T17: the only in-place edit of a volume file is the key-by-key .env task."""
    editors = {name for name, task in ALL_TASKS if "ansible.builtin.lineinfile" in task}
    assert editors == {"env_keys.yml"}


def test_t17_only_soul_seed_may_force_a_copy() -> None:
    """T17: `force: true` exists only behind the seed-once guard."""
    forced = [(n, t) for n, t in ALL_TASKS if (t.get("ansible.builtin.copy") or {}).get("force") is True]
    assert [n for n, _ in forced] == ["soul_seed.yml"]
    assert "checksum in hermes_soul_stock_sha256" in forced[0][1]["when"]


def test_t18_every_task_handling_a_token_is_no_log() -> None:
    """T18: any task module touching a token or the .env key map hides its output."""
    # `hermes_env_keys.keys()` iterates key NAMES only: no value to hide.
    secret = re.compile(r"bot_token|hermes_env_keys\b(?!_|\.keys\(\))|tokens_in_use")
    for name, task in ALL_TASKS:
        if any(k in task for k in ("ansible.builtin.import_tasks", "ansible.builtin.include_tasks")):
            continue  # passes variables on; prints nothing
        body = {k: v for k, v in task.items() if k not in ("name", "no_log", "loop_control", "fail_msg")}
        if secret.search(yaml.safe_dump(body)):
            assert task.get("no_log") is True, f"{name}: {task.get('name')}"


def test_t18_managed_env_template_has_no_token() -> None:
    """T02: the managed .env template defines no bot token and no API port."""
    keys = {
        line.split("=", 1)[0]
        for line in (TEMPLATES / "hermes.env.j2").read_text().splitlines()
        if re.match(r"^[A-Z_]+=", line)
    }
    assert "TELEGRAM_BOT_TOKEN" not in keys
    assert not keys & {"API_SERVER_PORT", "API_SERVER_HOST"}
    assert {"TELEGRAM_ALLOWED_USERS", "TELEGRAM_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS"} <= keys


# --- M1 non-goals -----------------------------------------------------------


def test_d1_timezone_left_alone() -> None:
    """D1: no Hermes timezone and no TZ in M1 (applied in M6)."""
    assert "timezone" not in (TEMPLATES / "config.yaml.j2").read_text()
    assert not re.search(r"\bTZ\b|HERMES_TIMEZONE", (TEMPLATES / "docker-compose.yml.j2").read_text())


def test_managed_config_pins_no_toolsets_and_no_mcp() -> None:
    """D5 and §12: managed merges into every profile; neither belongs there."""
    managed = (TEMPLATES / "config.yaml.j2").read_text()
    assert not re.search(
        r"^\s*(mcp_servers|toolsets|platform_toolsets|disabled_toolsets|platforms)\s*:", managed, re.MULTILINE
    )


def test_compose_keeps_host_network_and_one_hermes_container() -> None:
    """6.2: a single hermes container, host networking, memory limit unchanged."""
    compose = (TEMPLATES / "docker-compose.yml.j2").read_text()
    assert compose.count("container_name: hermes\n") == 1
    assert len(re.findall(r"^\s+network_mode: host$", compose, re.MULTILINE)) == 2
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["hermes_memory_limit"] == "4G"


def test_b3_token_moves_without_a_gap_and_checks_judge_the_restarted_gateway() -> None:
    """8.3/B4: token written to default .env BEFORE managed loses it; flush before checks."""
    names = [task.get("name", "") for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text())]
    order = {name: names.index(name) for name in names}
    pin = order["Pin the default profile Telegram bot token in its own .env"]
    managed_env = order["Deploy the managed Hermes secrets file"]
    flush = order["Apply pending Hermes restarts before verifying"]
    assert pin < managed_env < flush
    for check in (
        "Verify the managed scope contract",
        "Verify that the default profile .env carries its Telegram token",
        "Wait until the default gateway is up and Telegram connected (levels 2-3)",
        "Deploy the additional Hermes profiles",
    ):
        assert order[check] > flush, check
