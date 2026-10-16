"""M2 — Kaféine (profile cafe-ia): declaration, identity, tools, secrets, rollback.

Numbering follows the M2 mission (T01-T24). Everything runs against throwaway
directories, fake tokens and a fake `docker`/`ss` on PATH: nothing reaches
hermes-30. What only a deployment can prove (real gateway, real bot) is listed
as phase B in the role README.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import FAKE_TOKEN, FAKE_TOKEN_2, REPO, ROLE, RunTasks, recap

sys.path.insert(0, str(ROLE / "files"))
sys.path.insert(0, str(ROLE / "filter_plugins"))

import hermes_checks as hc
import hermes_profiles as hp

HERMES = REPO / "hermes"
GROUP_VARS = HERMES / "ansible/group_vars/hermes/all/main.yml"
TASKS = ROLE / "tasks"
TEMPLATES = ROLE / "templates"
CAFE_SRC = ROLE / "files/profiles/cafe-ia"
STAGE2_BLOCK = Path(__file__).parent / "fixtures/stage2_api_server_key.sh"
FAKE_TOKEN_3 = "555555555:FAKE-token-for-tests-ONLY-cccccccccccc"
FAKE_TAVILY = "tvly-FAKE-for-tests-only"

# Toolset names of Hermes v0.20.4 (toolsets.TOOLSETS, read in the image
# v2026.8.18). An unknown name in platform_toolsets is dropped silently
# (issue #38798), so a typo would quietly widen or break the profile.
HERMES_TOOLSETS = {
    "bfl",
    "browser",
    "clarify",
    "code_execution",
    "coding",
    "computer_use",
    "context_engine",
    "cronjob",
    "debugging",
    "delegation",
    "desktop_ui",
    "discord",
    "discord_admin",
    "feishu_doc",
    "feishu_drive",
    "file",
    "homeassistant",
    "image_gen",
    "kanban",
    "memory",
    "project",
    "safe",
    "search",
    "session_search",
    "skills",
    "spotify",
    "terminal",
    "todo",
    "tts",
    "video",
    "video_gen",
    "vision",
    "web",
    "x_search",
    "yuanbao",
}
# What would let Kaféine act on the host, other profiles' secrets, or the
# outside world without a human in the loop.
SENSITIVE = {"terminal", "file", "code_execution", "browser", "computer_use", "delegation", "cronjob", "kanban"}


@pytest.fixture(scope="module")
def group_vars() -> dict[str, Any]:
    """The hermes group_vars, as written (vault references left unresolved)."""
    return yaml.safe_load(GROUP_VARS.read_text())


@pytest.fixture(scope="module")
def cafe(group_vars: dict[str, Any]) -> dict[str, Any]:
    """The prepared cafe-ia declaration."""
    return group_vars["hermes_profile_cafe_ia"]


def resolved(cafe: dict[str, Any], token: str = FAKE_TOKEN_2) -> dict[str, Any]:
    """The cafe-ia declaration with fake secrets in place of vault references."""
    return cafe | {"telegram_bot_token": token, "env": {"TAVILY_API_KEY": FAKE_TAVILY}}


def validate(run: RunTasks, group_vars: dict[str, Any], profiles: list[dict[str, Any]], **overrides: Any) -> Any:
    """Run the real validate.yml with the hermes inventory and `profiles`."""
    variables = {
        "hermes_telegram_enabled": True,
        "hermes_telegram_bot_token": FAKE_TOKEN,
        "hermes_telegram_allowed_users": "1111111111",
        "hermes_profile_reserved_ports": group_vars["hermes_profile_reserved_ports"],
        "hermes_profiles": profiles,
        **overrides,
    }
    return run("validate.yml", variables)


def assert_fails_quietly(result: Any) -> None:
    """The guard failed, and no fake secret leaked into the output."""
    assert result.returncode != 0, result.stdout
    for secret in (FAKE_TOKEN, FAKE_TOKEN_2, FAKE_TOKEN_3, FAKE_TAVILY):
        assert secret not in result.stdout + result.stderr


def task_names(path: Path) -> list[str]:
    """Names of the top-level tasks of a task file, in order."""
    return [task.get("name", "") for task in yaml.safe_load(path.read_text())]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A stand-in for /opt/hermes/data with a lived-in default profile."""
    data = tmp_path / "data"
    for sub in ("memories", "sessions", "cron", "skills/custom-default-skill"):
        (data / sub).mkdir(parents=True)
    (data / "memories/MEMORY.md").write_text("souvenir de default\n")
    (data / "memories/USER.md").write_text("profil utilisateur de default\n")
    (data / "sessions/s1.json").write_text('{"default": true}\n')
    (data / "cron/jobs.json").write_text(
        json.dumps(
            {"jobs": [{"id": "x1", "name": "ai-coffee-scout", "schedule": {"kind": "cron", "expr": "0 8 * * 6"}}]}
        )
    )
    (data / "skills/custom-default-skill/SKILL.md").write_text("# skill de default\n")
    (data / "SOUL.md").write_text("Tu es Hermes, l'assistant de default.\n")
    (data / ".env").write_text(
        f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}\nAPI_SERVER_KEY=default-generated-1\nAPI_SERVER_KEY=default-generated-2\n"
    )
    # What `hermes profile create cafe-ia --no-alias` leaves (observed in the
    # v2026.8.18 image): empty dirs, a header-only .env, the stock SOUL.md.
    profile = data / "profiles/cafe-ia"
    for sub in ("memories", "sessions", "cron", "skills", "logs", "plans", "workspace", "home", "skins"):
        (profile / sub).mkdir(parents=True)
    (profile / ".env").write_text("# Per-profile secrets for this Hermes profile.\n")
    (profile / "SOUL.md").write_text(STOCK_SOUL)
    return data


STOCK_SOUL = "You are Hermes Agent, an intelligent AI assistant created by Nous Research."


def snapshot(root: Path) -> dict[str, bytes]:
    """Map every file under `root` to its content."""
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def deploy_host_side(run: RunTasks, tmp_path: Path, data: Path, cafe: dict[str, Any]) -> list[Any]:
    """Run, for real, the host-side tasks profile.yml chains for cafe-ia."""
    import hashlib

    profile = data / "profiles/cafe-ia"
    keys = {
        "TELEGRAM_BOT_TOKEN": FAKE_TOKEN_2,
        "API_SERVER_PORT": str(cafe["api_server_port"]),
        "TAVILY_API_KEY": FAKE_TAVILY,
    }
    return [
        run(
            "soul_seed.yml",
            {
                "hermes_soul_src": str(CAFE_SRC / "SOUL.md"),
                "hermes_soul_dest": str(profile / "SOUL.md"),
                "hermes_soul_stock_sha256": [hashlib.sha256(STOCK_SOUL.encode()).hexdigest()],
                "hermes_data_dir": str(data),
            },
        ),
        run("profile_content.yml", {"hermes_content_src": str(CAFE_SRC), "hermes_content_dest": str(profile)}),
        run("env_keys.yml", {"hermes_env_path": str(profile / ".env"), "hermes_env_keys": keys}),
    ]


# --- T01 création à blanc ----------------------------------------------------


def test_t01_profile_is_created_natively_without_clone() -> None:
    """T01/D7: `hermes profile create <name> --no-alias`, never a --clone flavour."""
    create = yaml.safe_load((TASKS / "profile.yml").read_text())[0]
    argv = create["ansible.builtin.command"]["argv"]
    assert "'profile', 'create', hermes_profile.name, '--no-alias'" in argv
    for path in TASKS.glob("*.yml"):
        assert "--clone" not in path.read_text(), path.name
        assert "clone_from" not in path.read_text(), path.name


# --- T02 / T03 identité -------------------------------------------------------


def test_t02_cafe_ia_has_its_own_soul() -> None:
    """T02: a dedicated SOUL.md naming Kaféine and Café IA, distinct from every other one."""
    soul = (CAFE_SRC / "SOUL.md").read_text()
    assert soul.startswith("Tu es **Kaféine**")
    assert "Café IA" in soul
    for other in (ROLE / "files/profiles").glob("*/SOUL.md"):
        if other.parent.name != "cafe-ia":
            assert other.read_text() != soul


def test_t02_soul_invents_no_history_and_states_its_limits() -> None:
    """6.4/7.4: no fake memories or participants; the hard limits are spelled out."""
    soul = (CAFE_SRC / "SOUL.md").read_text()
    assert "Tu démarres sans historique" in soul
    assert not re.search(r"\b(lors de la dernière rencontre|comme d'habitude|tu te souviens)\b", soul, re.IGNORECASE)
    assert not re.search(r"\b\d{9,10}\b", soul)  # no Telegram id
    for limit in ("Publier", "invitation", "automatisation récurrente", "Installer"):
        assert limit in soul
    assert "Ne jamais inventer" in soul


def test_t02_soul_is_seeded_over_the_stock_text(
    run_tasks: RunTasks, tmp_path: Path, data_dir: Path, cafe: dict[str, Any]
) -> None:
    """T02: after `profile create` (stock SOUL.md), the seed installs Kaféine."""
    results = deploy_host_side(run_tasks, tmp_path, data_dir, cafe)
    assert all(r.returncode == 0 for r in results), [r.stdout for r in results]
    assert (data_dir / "profiles/cafe-ia/SOUL.md").read_text() == (CAFE_SRC / "SOUL.md").read_text()


def test_t03_customised_soul_survives_the_next_run(
    run_tasks: RunTasks, tmp_path: Path, data_dir: Path, cafe: dict[str, Any]
) -> None:
    """T03/D6: once edited, SOUL.md is left alone: content, mode, mtime."""
    deploy_host_side(run_tasks, tmp_path, data_dir, cafe)
    soul = data_dir / "profiles/cafe-ia/SOUL.md"
    soul.write_text("Tu es Kaféine, version retouchée par l'utilisateur.\n")
    before = (soul.read_bytes(), soul.stat().st_mode, soul.stat().st_mtime_ns)
    deploy_host_side(run_tasks, tmp_path, data_dir, cafe)
    assert (soul.read_bytes(), soul.stat().st_mode, soul.stat().st_mtime_ns) == before


# --- T04 / T05 / T06 / T16 / T24 rien n'est hérité de default ------------------


def test_t04_t05_t06_t16_t24_host_tasks_copy_nothing_from_default(
    run_tasks: RunTasks, tmp_path: Path, data_dir: Path, cafe: dict[str, Any]
) -> None:
    """Memories, sessions, cron, skills and identity of default: untouched, and never copied."""
    profile = data_dir / "profiles/cafe-ia"
    default_before = {k: v for k, v in snapshot(data_dir).items() if not k.startswith("profiles/")}
    results = deploy_host_side(run_tasks, tmp_path, data_dir, cafe)
    assert all(r.returncode == 0 for r in results)

    assert {k: v for k, v in snapshot(data_dir).items() if not k.startswith("profiles/")} == default_before
    assert sorted(snapshot(profile)) == [".env", "SOUL.md"]
    blob = b"".join(snapshot(profile).values())
    for leaked in (
        b"souvenir de default",
        b"profil utilisateur",
        b"ai-coffee-scout",
        b"custom-default-skill",
        FAKE_TOKEN.encode(),
    ):
        assert leaked not in blob


def test_t04_t06_shipped_payload_is_identity_only() -> None:
    """D7: the repo ships SOUL.md only — no memory, session, cron, USER.md or skill."""
    shipped = sorted(str(p.relative_to(CAFE_SRC)) for p in CAFE_SRC.rglob("*") if p.is_file())
    assert shipped == ["SOUL.md"]
    items = [{"path": "SOUL.md", "state": "file", "src": str(CAFE_SRC / "SOUL.md")}]
    assert hp.hermes_profile_payload(items) == []


def test_t06_t24_no_automation_and_no_cron_contact(cafe: dict[str, Any]) -> None:
    """§12: cronjob toolset denied; no task of the role or the M2 playbooks touches a cron."""
    assert "cronjob" in cafe["config"]["agent.disabled_toolsets"]
    assert not any(key.startswith("cron") for key in cafe["config"])
    for path in [*TASKS.glob("profile*.yml"), HERMES / "ansible/m2-preflight.yml", HERMES / "ansible/m2-rollback.yml"]:
        text = path.read_text()
        assert not re.search(r"\bcron\s+(pause|resume|remove|run|create|edit)\b|jobs\.json", text), path.name


# --- T07 pas de Kandidat ------------------------------------------------------


def test_t07_no_mcp_and_no_kandidat(cafe: dict[str, Any]) -> None:
    """T07/D5: no MCP server declared, `no_mcp` set, no Kandidat reference anywhere for cafe-ia."""
    assert not any(key.startswith("mcp") for key in cafe["config"])
    assert "no_mcp" in cafe["config"]["platform_toolsets.telegram"]
    assert "kandidat" not in json.dumps(cafe).lower()
    assert "kandidat" not in (CAFE_SRC / "SOUL.md").read_text().lower()
    errors = hc.toolset_errors({"telegram": {"web"}}, {"web"}, set(), {"kandidat"}, True)
    assert errors == ["MCP servers configured: kandidat"]


# --- T08 / T09 jeton ----------------------------------------------------------


def test_t08_cafe_ia_cannot_reuse_another_token(
    run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any]
) -> None:
    """T08: default's token, or the tech-watch one, is refused without being printed."""
    assert validate(run_tasks, group_vars, [resolved(cafe)]).returncode == 0
    assert_fails_quietly(validate(run_tasks, group_vars, [resolved(cafe, FAKE_TOKEN)]))
    alex = group_vars["hermes_profile_tech_watch"] | {
        "telegram_bot_token": FAKE_TOKEN_3,
        "env": {"TAVILY_API_KEY": "x"},
    }
    assert_fails_quietly(validate(run_tasks, group_vars, [alex, resolved(cafe, FAKE_TOKEN_3)]))


def test_t08_token_points_to_its_own_vault_key(cafe: dict[str, Any], group_vars: dict[str, Any]) -> None:
    """9.3: dedicated vault key, never the default or tech-watch one."""
    assert cafe["telegram_bot_token"] == "{{ vault_hermes_cafe_ia_telegram_bot_token }}"
    assert cafe["telegram_bot_token"] not in (
        group_vars["hermes_telegram_bot_token"],
        group_vars["hermes_profile_tech_watch"]["telegram_bot_token"],
    )


@pytest.mark.parametrize("token", ["", "   "])
def test_t09_missing_token_blocks_activation(
    run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any], token: str
) -> None:
    """T09: an empty token is refused before any write."""
    assert_fails_quietly(validate(run_tasks, group_vars, [resolved(cafe, token.strip())]))


def test_t09_unresolved_vault_key_blocks_activation(
    run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any]
) -> None:
    """T09: the raw declaration, vault keys not created yet, cannot pass the guards."""
    result = validate(run_tasks, group_vars, [cafe])
    assert result.returncode != 0
    assert "vault_hermes_cafe_ia_" in result.stdout + result.stderr


def test_t09_empty_search_key_is_refused(run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any]) -> None:
    """A blank env value would silently remove the key (env_keys.yml): refused instead."""
    assert_fails_quietly(validate(run_tasks, group_vars, [resolved(cafe) | {"env": {"TAVILY_API_KEY": " "}}]))


def test_t09_not_active_until_phase_b(group_vars: dict[str, Any], cafe: dict[str, Any]) -> None:
    """Phase A: prepared, not in hermes_profiles."""
    assert cafe not in group_vars["hermes_profiles"]
    assert group_vars["hermes_profiles"] == []


# --- T10 / T11 politique Telegram commune -----------------------------------


def test_t10_t11_cafe_ia_cannot_carry_or_bypass_the_allowlist(
    run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any]
) -> None:
    """D3: no per-profile allowlist, no allow-all switch, in fields or env."""
    assert "telegram_allowed_users" not in cafe
    assert_fails_quietly(validate(run_tasks, group_vars, [resolved(cafe) | {"telegram_allowed_users": "1"}]))
    for key in ("TELEGRAM_ALLOWED_USERS", "TELEGRAM_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS"):
        bad = resolved(cafe)
        bad["env"] = bad["env"] | {key: "true"}
        assert_fails_quietly(validate(run_tasks, group_vars, [bad]))


def test_t11_managed_pins_both_switches_off() -> None:
    """T11: both bypasses are false in the managed layer, which every profile loads last."""
    env = (TEMPLATES / "hermes.env.j2").read_text()
    assert re.search(r"^TELEGRAM_ALLOW_ALL_USERS=false$", env, re.MULTILINE)
    assert re.search(r"^GATEWAY_ALLOW_ALL_USERS=false$", env, re.MULTILINE)


# --- T12 ports ---------------------------------------------------------------


def test_t12_ports(group_vars: dict[str, Any], cafe: dict[str, Any]) -> None:
    """T12: default 8642, cafe-ia 8646, no collision."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert defaults["hermes_gateway_port"] == 8642
    assert cafe["api_server_port"] == group_vars["hermes_profile_reserved_ports"]["cafe-ia"] == 8646


def test_t12_cafe_ia_on_default_port_is_refused(
    run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any]
) -> None:
    """T12: 8642 (default) is refused for cafe-ia."""
    assert_fails_quietly(validate(run_tasks, group_vars, [resolved(cafe) | {"api_server_port": 8642}]))


# --- T13 API_SERVER_KEY -------------------------------------------------------


def stage2(home: Path) -> subprocess.CompletedProcess[str]:
    """Run the verbatim stage2 API_SERVER_KEY block with HERMES_HOME=`home`."""
    return subprocess.run(
        ["sh", str(STAGE2_BLOCK)],
        env={**os.environ, "HERMES_HOME": str(home)},
        capture_output=True,
        text=True,
        check=True,
    )


def key_lines(path: Path) -> int:
    """Count API_SERVER_KEY assignments in a dotenv file."""
    return len(re.findall(r"^API_SERVER_KEY=", path.read_text(), re.MULTILINE)) if path.exists() else 0


def test_t13_stage2_scenarios(tmp_path: Path) -> None:
    """T13: absent .env -> nothing; present without key -> one key; with key -> untouched; repeated -> stable."""
    home = tmp_path / "data"
    home.mkdir()
    env = home / ".env"
    stage2(home)
    assert not env.exists()

    env.write_text("TELEGRAM_BOT_TOKEN=x\nAPI_SERVER_KEY=\n")
    assert "Generated API_SERVER_KEY" in stage2(home).stdout
    assert key_lines(env) == 1 and "API_SERVER_KEY=\n" not in env.read_text()

    content = env.read_text()
    for _ in range(3):
        stage2(home)
    assert env.read_text() == content


def test_t13_stage2_never_touches_a_profile_env(tmp_path: Path) -> None:
    """T13: the hook targets $HERMES_HOME/.env only; a profile .env, with or without key, is left alone."""
    home = tmp_path / "data"
    profile_env = home / "profiles/cafe-ia/.env"
    profile_env.parent.mkdir(parents=True)
    profile_env.write_text(f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN_2}\nAPI_SERVER_PORT=8646\n")
    before = profile_env.read_bytes()
    (home / ".env").write_text("X=1\n")
    stage2(home)
    assert profile_env.read_bytes() == before
    block = STAGE2_BLOCK.read_text().split("refuse_symlinked_path() {", 1)[1]
    assert set(re.findall(r'"(\$HERMES_HOME[^"]*)"', block)) == {"$HERMES_HOME/.env"}


def test_t13_concurrent_stage2_explains_the_m1_duplicate(tmp_path: Path) -> None:
    """T13: two containers on one volume race check-then-append; a profile .env is never hit.

    The race is timing-dependent: duplicates are possible, not guaranteed, so
    the test asserts the invariants only (>= 1 key, profile .env intact).
    """
    home = tmp_path / "data"
    profile_env = home / "profiles/cafe-ia/.env"
    profile_env.parent.mkdir(parents=True)
    profile_env.write_text("TELEGRAM_BOT_TOKEN=y\n")
    before = profile_env.read_bytes()
    for _ in range(10):
        (home / ".env").write_text("TELEGRAM_BOT_TOKEN=x\n")
        barrier = threading.Barrier(2)

        def boot(barrier: threading.Barrier = barrier) -> None:
            barrier.wait()
            stage2(home)

        threads = [threading.Thread(target=boot) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert 1 <= key_lines(home / ".env") <= 2
    assert profile_env.read_bytes() == before


def test_t13_api_key_verdicts() -> None:
    """T13: deterministic = managed carries the key, the profile .env does not, the effective one is managed's."""
    assert hc.api_key_errors({"TELEGRAM_BOT_TOKEN", "API_SERVER_PORT"}, True, True) == []
    assert hc.api_key_errors(set(), True, True) == []  # .env present but header-only
    assert hc.api_key_errors({"API_SERVER_KEY"}, True, True) == [
        "API_SERVER_KEY present in the profile .env (must come from managed only)"
    ]
    assert hc.api_key_errors(set(), False, True) == ["effective API_SERVER_KEY differs from the managed one"]
    assert hc.api_key_errors(set(), False, False) == ["API_SERVER_KEY missing from managed .env"]


def test_t13_no_new_api_key_secret(run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any]) -> None:
    """§10.4: cafe-ia declares no API_SERVER_* key; one in env is refused; managed keeps the only one."""
    assert not any(key.startswith("API_SERVER") for key in cafe["env"])
    bad = resolved(cafe)
    bad["env"] = bad["env"] | {"API_SERVER_KEY": "x" * 32}
    assert_fails_quietly(validate(run_tasks, group_vars, [bad]))
    assert re.findall(r"^API_SERVER_KEY=", (TEMPLATES / "hermes.env.j2").read_text(), re.MULTILINE) == [
        "API_SERVER_KEY="
    ]


def test_t13_profile_env_gets_no_api_key_from_the_role(
    run_tasks: RunTasks, tmp_path: Path, data_dir: Path, cafe: dict[str, Any]
) -> None:
    """T13: after the host tasks, the profile .env holds its 3 keys and no API_SERVER_KEY; default's duplicates are left as is."""
    deploy_host_side(run_tasks, tmp_path, data_dir, cafe)
    profile_env = data_dir / "profiles/cafe-ia/.env"
    keys = re.findall(r"^([A-Z_]+)=", profile_env.read_text(), re.MULTILINE)
    assert sorted(keys) == ["API_SERVER_PORT", "TAVILY_API_KEY", "TELEGRAM_BOT_TOKEN"]
    assert stat.S_IMODE(profile_env.stat().st_mode) == 0o600
    assert key_lines(data_dir / ".env") == 2


# --- T14 caches ---------------------------------------------------------------


def test_t14_no_cache_shipped_for_cafe_ia(run_tasks: RunTasks, tmp_path: Path, data_dir: Path) -> None:
    """T14: a stray __pycache__ next to SOUL.md is never deployed."""
    src = tmp_path / "cafe-src"
    (src / "__pycache__").mkdir(parents=True)
    (src / "__pycache__/x.cpython-312.pyc").write_bytes(b"\x00")
    (src / "SOUL.md").write_text("x\n")
    dest = data_dir / "profiles/cafe-ia"
    before = snapshot(dest)
    assert (
        run_tasks("profile_content.yml", {"hermes_content_src": str(src), "hermes_content_dest": str(dest)}).returncode
        == 0
    )
    assert snapshot(dest) == before


# --- T15 idempotence ----------------------------------------------------------


def test_t15_second_run_changes_nothing(
    run_tasks: RunTasks, tmp_path: Path, data_dir: Path, cafe: dict[str, Any]
) -> None:
    """T15: the second pass reports 0 changed on every host task and resets nothing."""
    deploy_host_side(run_tasks, tmp_path, data_dir, cafe)
    before = snapshot(data_dir)
    second = deploy_host_side(run_tasks, tmp_path, data_dir, cafe)
    assert [recap(r)["changed"] for r in second] == [0, 0, 0]
    assert snapshot(data_dir) == before


@pytest.mark.parametrize(
    "key", ["web.backend", "platform_toolsets.telegram", "agent.disabled_toolsets", "skills.write_approval"]
)
def test_t15_config_values_converge(cafe: dict[str, Any], key: str) -> None:
    """T15: what `config set` stores reads back equal (`config get --json`), so no perpetual change."""
    value = cafe["config"][key]
    stored = yaml.safe_load(hp.hermes_config_arg(value))  # config set parses its argument as YAML
    assert stored == value
    assert hp.hermes_config_equal(json.dumps(stored), value)


# --- T17 nommage Telegram -----------------------------------------------------

BOTFATHER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def test_t17_bot_username_follows_d2(cafe: dict[str, Any]) -> None:
    """T17/D2: kafeine_<6 alphanumerics>_bot, and acceptable to BotFather (5-32 chars, ends in bot)."""
    username = cafe["telegram_bot_username"]
    assert re.fullmatch(r"kafeine_[A-Za-z0-9]{6}_bot", username)
    assert BOTFATHER.fullmatch(username) and username.lower().endswith("bot")


@pytest.mark.parametrize(
    "username",
    [
        "kafeine_bot",
        "kafeine_abc12_bot",
        "kafeine_abc1234_bot",
        "kafeine_abc123_robot",
        "Kafeine_abc123_bot",
        "kafeine_ab-123_bot",
    ],
)
def test_t17_malformed_usernames_are_refused(
    run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any], username: str
) -> None:
    """T17: the guard enforces the convention before any write."""
    assert_fails_quietly(validate(run_tasks, group_vars, [resolved(cafe) | {"telegram_bot_username": username}]))


# --- T18 outils ---------------------------------------------------------------


def test_t18_tool_lists_are_known_disjoint_and_least_privilege(cafe: dict[str, Any]) -> None:
    """T18/D5: known names only, allow and deny disjoint, every sensitive toolset denied."""
    allowed = set(cafe["config"]["platform_toolsets.telegram"]) - {"no_mcp"}
    denied = set(cafe["config"]["agent.disabled_toolsets"])
    assert allowed == {"web", "skills", "memory", "session_search", "todo", "clarify"}
    assert (allowed | denied) <= HERMES_TOOLSETS
    assert not allowed & denied
    assert SENSITIVE <= denied
    for platform in ("cron", "api_server"):
        assert cafe["config"][f"platform_toolsets.{platform}"] == cafe["config"]["platform_toolsets.telegram"]


def test_t18_skill_writes_need_approval(cafe: dict[str, Any]) -> None:
    """T18: `skills` cannot drop skill_manage alone, so every skill write is staged for approval."""
    assert "skills" in cafe["config"]["platform_toolsets.telegram"]
    assert cafe["config"]["skills.write_approval"] is True


def test_t18_toolset_verdicts() -> None:
    """T18: anything beyond the allowlist, or denied, is reported per platform."""
    allowed, denied = {"web", "memory"}, {"terminal", "file"}
    assert hc.toolset_errors({"telegram": {"web"}, "cli": {"memory"}}, allowed, denied, set(), True) == []
    errors = hc.toolset_errors(
        {"telegram": {"web", "terminal"}, "api_server": {"browser"}}, allowed, denied, set(), True
    )
    assert errors == [
        "api_server: toolsets beyond the allowlist: browser",
        "telegram: toolsets beyond the allowlist: terminal",
        "telegram: denied toolsets enabled: terminal",
    ]


def test_t18_restrictions_are_checked_before_the_gateway_starts() -> None:
    """Order in profile.yml: identity, API key and tools verified before `gateway start`."""
    names = task_names(TASKS / "profile.yml")
    start = next(i for i, n in enumerate(names) if n.startswith("Start the gateway"))
    for prefix in ("Verify that the token belongs", "Verify that API_SERVER_KEY", "Verify that the declared tool"):
        assert next(i for i, n in enumerate(names) if n.startswith(prefix)) < start, prefix
    after = next(i for i, n in enumerate(names) if "listens on loopback" in n)
    assert after > start


# --- T19 / T20 supervision et Telegram --------------------------------------


def svstat_state(pid: int = 4242, start: float = 1.5) -> dict[str, Any]:
    """A gateway_state.json of profile cafe-ia, connected, written by `pid`."""
    entry = {"state": "connected", "writer_pid": pid, "writer_start_time": start}
    return {"pid": pid, "start_time": start, "gateway_state": "running", "platforms": {"telegram": entry}}


@pytest.mark.parametrize(
    ("status", "state", "expected"),
    [
        ("up (pid 4242) 12 seconds", svstat_state(), "telegram connected (gateway pid 4242)"),
        ("down (exitcode 78) 3 seconds, normally up", svstat_state(), "level 2"),
        ("up (pid 9999) 2 seconds", svstat_state(), "written by pid 4242, s6 runs 9999"),
        (
            "up (pid 4242) 2 seconds",
            svstat_state()
            | {"platforms": {"telegram": {"state": "disconnected", "writer_pid": 4242, "writer_start_time": 1.5}}},
            "telegram state is 'disconnected'",
        ),
        ("up (pid 4242) 2 seconds", svstat_state() | {"platforms": {}}, "token missing?"),
        ("up (pid 4242) 2 seconds", None, "absent or malformed"),
    ],
    ids=["connected", "s6-down", "stale-process", "disconnected", "no-config", "no-state"],
)
def test_t19_t20_gateway_and_telegram_states(status: str, state: Any, expected: str) -> None:
    """T19/T20: the existing level 2-3 verdict, on cafe-ia shaped states."""
    ok, message = hc.telegram_verdict(state, status, lambda _s: True)
    assert ok == expected.startswith("telegram connected")
    assert expected in message


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ({"ok": True, "result": {"is_bot": True, "username": "kafeine_r64gnb_bot"}}, None),
        ({"ok": True, "result": {"is_bot": True, "username": "Kafeine_R64GNB_bot"}}, None),
        ({"ok": True, "result": {"is_bot": True, "username": "alex_x1y2z3_bot"}}, "token belongs to @alex_x1y2z3_bot"),
        ({"ok": False, "error_code": 401, "description": "Unauthorized"}, "getMe refused the token (error_code=401)"),
        ({"ok": True, "result": {"is_bot": False, "username": "kafeine_r64gnb_bot"}}, "not a bot"),
        ("garbage", "getMe refused the token"),
    ],
    ids=["match", "case-insensitive", "other-bot", "invalid-token", "not-a-bot", "malformed"],
)
def test_t20_bot_identity(reply: Any, error: str | None) -> None:
    """T20: invalid token and wrong bot are refused; the message never carries the token."""
    errors = hc.bot_identity_errors(reply, "kafeine_r64gnb_bot")
    assert (errors == []) if error is None else (error in errors[0])


def test_t20_default_is_rechecked_after_the_profiles() -> None:
    """--replace risk: default's level 2-3 is re-proved, same pid, once the profiles run."""
    names = task_names(TASKS / "main.yml")
    assert names.index("Verify that the default gateway survived the profiles (levels 2-3)") > names.index(
        "Deploy the additional Hermes profiles"
    )
    task = yaml.safe_load((TASKS / "main.yml").read_text())[
        names.index("Verify that the default gateway survived the profiles (levels 2-3)")
    ]
    assert "hermes_default_telegram.stdout" in task["failed_when"]


# --- T21 rollback (vrai profile_rollback.yml, faux docker) -------------------

FAKE_DOCKER = r'''#!/usr/bin/env python3
"""Fake `docker`/`ss`: simulates s6 and `gateway stop`, logs every call."""
import json, os, sys
from pathlib import Path
state_file = Path(os.environ["FAKE_STATE"])
state = json.loads(state_file.read_text())
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]][:12]) + "\n")
if Path(sys.argv[0]).name == "ss":
    print(state.get("listen", ""), end="")
    sys.exit(0)
if sys.argv[1] == "stats":
    print("hermes mem=359MiB / 4GiB cpu=1.0% pids=31")
    sys.exit(0)
args = sys.argv[2:]
while args and args[0] in ("-u", "-e"):
    args = args[2:]
cmd = args[1:]
if cmd[:1] == ["test"]:
    sys.exit(0 if cmd[-1].rsplit("/", 1)[-1] in state["svstat"] else 1)
if cmd[:1] == ["ps"]:
    print("PID RSS COMMAND\n162 360380 hermes gateway run --replace")
    sys.exit(0)
if cmd[:1] == ["/command/s6-svstat"]:
    print(state["svstat"].get(cmd[1].rsplit("/", 1)[-1], "s6-svstat: fatal: unable to read status"))
elif cmd[:3] == ["hermes", "-p", cmd[2] if len(cmd) > 2 else ""] and cmd[3:] == ["gateway", "stop"]:
    name = cmd[2]
    if not state.get("stop_fails"):
        state["svstat"]["gateway-" + name] = "down (exitcode 0) 1 seconds, normally up"
        state["listen"] = ""
        gs = Path(os.environ["FAKE_DATA"]) / "profiles" / name / "gateway_state.json"
        gs.write_text(json.dumps({"desired_state": "stopped", "gateway_state": "stopped"}))
    state_file.write_text(json.dumps(state))
    print("stopped")
elif cmd[:1] == ["python3"]:
    print("telegram connected (gateway pid 162)")
else:
    sys.exit(f"unexpected: {cmd}")
'''


@pytest.fixture
def fake_host(tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Put a fake docker and ss first on PATH, pointed at a simulated container state."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("docker", "ss"):
        (bindir / name).write_text(FAKE_DOCKER.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        (bindir / name).chmod(0o755)
    paths = {"state": tmp_path / "state.json", "log": tmp_path / "calls.log", "data": data_dir}
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(paths["state"]))
    monkeypatch.setenv("FAKE_LOG", str(paths["log"]))
    monkeypatch.setenv("FAKE_DATA", str(data_dir))
    return paths


def set_state(
    host: dict[str, Path], svstat: str, desired: str | None, listen: str = "", stop_fails: bool = False
) -> None:
    """Describe the simulated container before the rollback."""
    host["state"].write_text(
        json.dumps(
            {
                "svstat": {"gateway-cafe-ia": svstat, "gateway-default": "up (pid 162) 99 seconds"},
                "listen": listen,
                "stop_fails": stop_fails,
            }
        )
    )
    gs = host["data"] / "profiles/cafe-ia/gateway_state.json"
    if desired is not None:
        gs.write_text(json.dumps({"desired_state": desired, "gateway_state": "running"}))


def rollback(
    run: RunTasks, group_vars: dict[str, Any], host: dict[str, Path], name: str = "cafe-ia", stop_retries: int = 2
) -> Any:
    """Run the real profile_rollback.yml against the fake host."""
    return run(
        "profile_rollback.yml",
        {
            "hermes_rb_profile_name": name,
            "hermes_rb_stop_retries": stop_retries,
            "hermes_rb_stop_delay": 1,
            "hermes_data_dir": str(host["data"]),
            "hermes_profile_reserved_ports": group_vars["hermes_profile_reserved_ports"],
            "hermes_profiles": [],
            "hermes_telegram_enabled": True,
        },
    )


def calls(host: dict[str, Path]) -> list[list[str]]:
    """Every fake docker/ss invocation."""
    return [json.loads(line) for line in host["log"].read_text().splitlines()] if host["log"].exists() else []


def test_t21_rollback_stops_cafe_ia_only_and_keeps_data(
    run_tasks: RunTasks, group_vars: dict[str, Any], fake_host: dict[str, Path]
) -> None:
    """T21: a running cafe-ia is stopped (desired_state=stopped); default is only read; no file removed."""
    set_state(fake_host, "up (pid 4242) 60 seconds", "running", listen="LISTEN 0 128 127.0.0.1:8646 0.0.0.0:*")
    before = {k for k in snapshot(fake_host["data"])}
    result = rollback(run_tasks, group_vars, fake_host)
    assert result.returncode == 0, result.stdout
    mutating = [c for c in calls(fake_host) if "stop" in c]
    assert len(mutating) == 1 and mutating[0][-4:] == ["-p", "cafe-ia", "gateway", "stop"]
    assert not any("default" in arg and "stop" in c for c in calls(fake_host) for arg in c)
    assert (
        json.loads((fake_host["data"] / "profiles/cafe-ia/gateway_state.json").read_text())["desired_state"]
        == "stopped"
    )
    assert before <= set(snapshot(fake_host["data"]))
    assert "telegram connected (gateway pid 162)" in result.stdout


def test_t21_rollback_also_clears_a_persisted_running_intent(
    run_tasks: RunTasks, group_vars: dict[str, Any], fake_host: dict[str, Path]
) -> None:
    """§16: a slot already down but desired_state=running would restart at boot: stop it anyway."""
    set_state(fake_host, "down (exitcode 1) 5 seconds, normally up", "running")
    assert rollback(run_tasks, group_vars, fake_host).returncode == 0
    assert [c for c in calls(fake_host) if "stop" in c]


def test_t21_rollback_is_idempotent(
    run_tasks: RunTasks, group_vars: dict[str, Any], fake_host: dict[str, Path]
) -> None:
    """Already stopped: nothing to do, nothing changed."""
    set_state(fake_host, "down (exitcode 0) 60 seconds", "stopped")
    result = rollback(run_tasks, group_vars, fake_host)
    assert result.returncode == 0
    assert recap(result)["changed"] == 0
    assert not [c for c in calls(fake_host) if "stop" in c]


def test_t21_rollback_fails_when_the_gateway_stays_up(
    run_tasks: RunTasks, group_vars: dict[str, Any], fake_host: dict[str, Path]
) -> None:
    """A stop that does not take is a failure, not a green run."""
    set_state(fake_host, "up (pid 4242) 60 seconds", "running", stop_fails=True)
    result = rollback(run_tasks, group_vars, fake_host, stop_retries=0)
    assert result.returncode != 0


@pytest.mark.parametrize("name", ["default", "../default", "unknown-profile"])
def test_t21_rollback_refuses_default_and_unknown_names(
    run_tasks: RunTasks, group_vars: dict[str, Any], fake_host: dict[str, Path], name: str
) -> None:
    """The rollback never acts on default nor on a name off the reservation table."""
    set_state(fake_host, "up (pid 162) 60 seconds", None)
    assert rollback(run_tasks, group_vars, fake_host, name).returncode != 0
    assert calls(fake_host) == []


def test_t21_m2_operations_destroy_nothing() -> None:
    """§16: no deletion, no token revocation, no container restart in the M2 operations."""
    for path in (
        TASKS / "profile_rollback.yml",
        TASKS / "profile_preflight.yml",
        HERMES / "ansible/m2-rollback.yml",
        HERMES / "ansible/m2-preflight.yml",
    ):
        text = path.read_text()
        body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert not re.search(
            r"state:\s*(absent|restarted)|\brm\b|profile\s+delete|- restart$|revoke|docker_compose", body, re.MULTILINE
        ), path.name


def test_preflight_m2_is_read_only() -> None:
    """B2: the candidate-profile preflight only reads."""
    write_modules = {
        "ansible.builtin.copy",
        "ansible.builtin.template",
        "ansible.builtin.file",
        "ansible.builtin.lineinfile",
        "community.docker.docker_compose_v2",
    }
    for path in ("profile_preflight.yml", "memory_preflight.yml"):
        for task in yaml.safe_load((TASKS / path).read_text()):
            assert not write_modules & task.keys(), task["name"]
            if "ansible.builtin.command" in task:
                assert task["changed_when"] is False and task["check_mode"] is False, task["name"]
            if "ansible.builtin.uri" in task:
                assert task["ansible.builtin.uri"].get("method", "GET") == "GET", task["name"]
                assert task["no_log"] is True and task["delegate_to"] == "localhost", task["name"]


# --- T22 réseau ---------------------------------------------------------------

SS_LOOPBACK = (
    "LISTEN 0 128 127.0.0.1:8646 0.0.0.0:*\nLISTEN 0 128 127.0.0.1:8642 0.0.0.0:*\nLISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\n"
)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (SS_LOOPBACK, []),
        ("LISTEN 0 128 [::1]:8646 [::]:*\n", []),
        ("LISTEN 0 128 0.0.0.0:8646 0.0.0.0:*\n", ["port 8646 listens beyond loopback: 0.0.0.0:8646"]),
        ("LISTEN 0 128 [::]:8646 [::]:*\n", ["port 8646 listens beyond loopback: [::]:8646"]),
        ("LISTEN 0 128 192.168.10.30:8646 0.0.0.0:*\n", ["port 8646 listens beyond loopback: 192.168.10.30:8646"]),
        ("LISTEN 0 128 127.0.0.1:18646 0.0.0.0:*\n", ["nothing listens on port 8646"]),
    ],
    ids=["loopback", "ipv6-loopback", "any-v4", "any-v6", "lan", "absent"],
)
def test_t22_listen_verdict(output: str, expected: list[str]) -> None:
    """T22: the API must listen, and on loopback only."""
    assert hc.listen_errors(output, 8646) == expected


def test_t22_no_exposure_added(group_vars: dict[str, Any], cafe: dict[str, Any]) -> None:
    """T22: no host override, no UFW rule for 8646; the Hermes default bind (127.0.0.1) applies."""
    assert "API_SERVER_HOST" not in json.dumps(cafe)
    assert not any("host" in key for key in cafe["config"])
    assert all(rule["port"] in (22, 9119) for rule in group_vars["security_open_ports"])


# --- T23 coexistence ----------------------------------------------------------


def test_t23_three_gateways_coexist_in_the_inventory(
    run_tasks: RunTasks, group_vars: dict[str, Any], cafe: dict[str, Any]
) -> None:
    """T23: default + cafe-ia (+ the prepared tech-watch) pass together: names, ports, tokens distinct."""
    alex = group_vars["hermes_profile_tech_watch"] | {
        "telegram_bot_token": FAKE_TOKEN_3,
        "env": {"TAVILY_API_KEY": "x"},
    }
    result = validate(run_tasks, group_vars, [resolved(cafe), alex])
    assert result.returncode == 0, result.stdout


def test_t23_cafe_ia_is_isolated_by_home(cafe: dict[str, Any]) -> None:
    """T23: every path the role writes for cafe-ia lives under profiles/cafe-ia/."""
    text = (TASKS / "profile.yml").read_text()
    assert set(re.findall(r'hermes_data_dir \}\}/([^"]+)"', text)) == {
        "profiles/{{ hermes_profile.name }}",
        "profiles/{{ hermes_profile.name }}/SOUL.md",
        "profiles/{{ hermes_profile.name }}/.env",
    }
    assert set(re.findall(r"HERMES_HOME=([^\"]+)\"", text)) == {"/opt/data/profiles/{{ hermes_profile.name }}"}


# --- B2 preflight du profil candidat (vrai profile_preflight.yml, faux docker)


def preflight(run: RunTasks, group_vars: dict[str, Any], host: dict[str, Path], candidate: dict[str, Any]) -> Any:
    """Run the real profile_preflight.yml; hermes_profiles comes from the role default ([])."""
    return run(
        "profile_preflight.yml",
        {
            "hermes_pf_profile": candidate,
            "hermes_data_dir": str(host["data"]),
            "hermes_telegram_enabled": True,
            "hermes_telegram_bot_token": FAKE_TOKEN,
            "hermes_telegram_allowed_users": "1111111111",
            "hermes_profile_reserved_ports": group_vars["hermes_profile_reserved_ports"],
            "hermes_pf_meminfo_path": str(host["meminfo"]),
        },
    )


FAKE_PVE_SECRET = "FAKE-pve-secret-for-tests-only"
MIB = 1048576


def meminfo(total_mib: int, available_mib: int) -> str:
    """A /proc/meminfo excerpt with the two lines the verdict reads."""
    return f"MemTotal:       {total_mib * 1024} kB\nMemFree:  1 kB\nMemAvailable:   {available_mib * 1024} kB\n"


@pytest.fixture
def fake_pve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A local fake of the three Proxmox API reads; GET only, every request recorded."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    pve: dict[str, Any] = {"vm_name": "localhost", "memory": "8192", "balloon": 3584, "actual": 3584, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Answer the three reads the gate makes; 404 for anything else."""
            pve["requests"].append((self.command, self.path, self.headers.get("Authorization")))
            routes = {
                "/api2/json/cluster/resources?type=vm": [
                    {"type": "lxc", "name": pve["vm_name"], "node": "pve", "vmid": 1070},
                    {"type": "qemu", "name": pve["vm_name"], "node": "pve", "vmid": 9030},
                ],
                "/api2/json/nodes/pve/qemu/9030/config": {"memory": pve["memory"]}
                | ({} if pve["balloon"] is None else {"balloon": pve["balloon"]}),
                "/api2/json/nodes/pve/qemu/9030/status/current": {"ballooninfo": {"actual": pve["actual"] * MIB}},
            }
            body = json.dumps({"data": routes[self.path]}).encode() if self.path in routes else b"{}"
            self.send_response(200 if self.path in routes else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            """Keep the test output quiet."""

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("TF_VAR_pm_api_url", f"http://127.0.0.1:{server.server_port}/api2/json/")
    monkeypatch.setenv("TF_VAR_pm_api_token_id", "terraform@pve!tests")
    monkeypatch.setenv("TF_VAR_pm_api_token_secret", FAKE_PVE_SECRET)
    yield pve
    server.shutdown()


@pytest.fixture
def blank_host(fake_host: dict[str, Path], fake_pve: dict[str, Any], tmp_path: Path) -> dict[str, Path]:
    """No cafe-ia yet: no directory, no s6 slot, port free; floor 3584 MiB, 2 GiB available."""
    import shutil

    shutil.rmtree(fake_host["data"] / "profiles")
    fake_host["state"].write_text(json.dumps({"svstat": {"gateway-default": "up (pid 162) 9 seconds"}, "listen": ""}))
    fake_host["meminfo"] = tmp_path / "meminfo"
    fake_host["meminfo"].write_text(meminfo(3333, 2123))
    return fake_host


def test_b2_preflight_go_on_a_blank_page(
    run_tasks: RunTasks, group_vars: dict[str, Any], blank_host: dict[str, Path], cafe: dict[str, Any]
) -> None:
    """B2: valid declaration, no profile, no slot, free port -> GO; writes nothing; prints no secret."""
    before = snapshot(blank_host["data"])
    result = preflight(run_tasks, group_vars, blank_host, resolved(cafe))
    assert result.returncode == 0, result.stdout
    assert snapshot(blank_host["data"]) == before
    assert "port                   : libre" in result.stdout
    for secret in (FAKE_TOKEN, FAKE_TOKEN_2, FAKE_TAVILY):
        assert secret not in result.stdout + result.stderr


def test_b2_preflight_no_go_when_vault_keys_are_missing(
    run_tasks: RunTasks, group_vars: dict[str, Any], blank_host: dict[str, Path], cafe: dict[str, Any]
) -> None:
    """B2/T09: the raw declaration (vault keys not created) is a NO-GO."""
    result = preflight(run_tasks, group_vars, blank_host, cafe)
    assert result.returncode != 0
    assert "vault_hermes_cafe_ia_" in result.stdout + result.stderr


def test_b2_preflight_really_validates_the_candidate(
    run_tasks: RunTasks, group_vars: dict[str, Any], blank_host: dict[str, Path], cafe: dict[str, Any]
) -> None:
    """B2/T08: the candidate goes through validate.yml (default's token reused -> NO-GO)."""
    assert_fails_quietly(preflight(run_tasks, group_vars, blank_host, resolved(cafe, FAKE_TOKEN)))


def test_b2_preflight_no_go_when_cafe_ia_already_exists(
    run_tasks: RunTasks, group_vars: dict[str, Any], blank_host: dict[str, Path], cafe: dict[str, Any]
) -> None:
    """B2: an existing directory, s6 slot or listener stops the deployment."""
    (blank_host["data"] / "profiles/cafe-ia").mkdir(parents=True)
    assert_fails_quietly(preflight(run_tasks, group_vars, blank_host, resolved(cafe)))


def test_b2_preflight_no_go_when_the_port_is_taken(
    run_tasks: RunTasks, group_vars: dict[str, Any], blank_host: dict[str, Path], cafe: dict[str, Any]
) -> None:
    """B2: something already on 8646 is a NO-GO."""
    blank_host["state"].write_text(json.dumps({"svstat": {}, "listen": "LISTEN 0 5 127.0.0.1:8646 0.0.0.0:*\n"}))
    assert_fails_quietly(preflight(run_tasks, group_vars, blank_host, resolved(cafe)))


# --- B2 memoire : plancher du ballooning Proxmox (memory_preflight.yml) -------

# Mesures de hermes-30, 2026-10-16 : ballon au plancher de 2048 MiB.
PROD_2026_10_16 = "MemTotal:        1840316 kB\nMemAvailable:     629392 kB\n"


@pytest.mark.parametrize(
    ("memory", "balloon", "floor"),
    [("8192", "2048", 2048), ("current=8192", "3584", 3584), ("8192", "", 8192), ("8192", "0", None)],
    ids=["floor", "pve9-memory-string", "balloon-absent-equals-memory", "device-off"],
)
def test_b2_balloon_floor(memory: str, balloon: str, floor: int | None) -> None:
    """B2: the floor is read from the effective Proxmox configuration, in every form it takes."""
    assert hc.balloon_floor_mib(memory, balloon) == floor


def test_b2_memory_no_go_on_the_2026_10_16_measurements() -> None:
    """B2: today's hermes-30 (629 MiB available, at a 2048 MiB floor) is a NO-GO, now and at the floor."""
    errors, summary = hc.memory_verdict(PROD_2026_10_16, 2048, 2048, 1536)
    assert errors == [
        "MemAvailable 614 MiB < 1536 MiB required now",
        "at the balloon floor ~614 MiB would remain < 1536 MiB required (estimate)",
    ]
    assert "unseen by the guest ~251" in summary


def test_b2_memory_go_with_a_3584_floor() -> None:
    """B2: at a 3584 MiB floor with today's usage, ~2 GiB remain: GO."""
    errors, summary = hc.memory_verdict(meminfo(3333, 2123), 3584, 3584, 1536)
    assert errors == []
    assert "worst case ~2123 MiB" in summary


def test_b2_memory_a_good_reading_is_not_a_guarantee() -> None:
    """B2: plenty available NOW (balloon inflated to 8 GiB) but a 2048 floor: NO-GO on the floor alone."""
    errors, _ = hc.memory_verdict(meminfo(7946, 6700), 2048, 8192, 1536)
    assert errors == ["at the balloon floor ~556 MiB would remain < 1536 MiB required (estimate)"]


def test_b2_memory_without_ballooning_only_now_counts() -> None:
    """B2: no balloon device, nothing can be reclaimed: the current reading is the worst case."""
    assert hc.memory_verdict(meminfo(9945, 6211), None, None, 1536)[0] == []
    assert hc.memory_verdict(meminfo(9945, 1000), None, None, 1536)[0] == [
        "MemAvailable 1000 MiB < 1536 MiB required now"
    ]


def test_b2_memory_unknown_balloon_size_is_a_no_go() -> None:
    """B2: without ballooninfo the worst case cannot be estimated: refuse rather than guess."""
    errors, _ = hc.memory_verdict(meminfo(3333, 2123), 3584, None, 1536)
    assert errors == ["balloon size unknown: the worst case cannot be estimated"]


def test_b2_memory_cli(tmp_path: Path) -> None:
    """B2: the CLI mode reads a meminfo file and Proxmox's raw values (balloon size in bytes)."""
    path = tmp_path / "meminfo"
    path.write_text(meminfo(3333, 2123))
    script = ROLE / "files/hermes_checks.py"
    ok = subprocess.run(
        [sys.executable, str(script), "memory", "8192", "3584", str(3584 * MIB), "1536", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0 and "GO: memory headroom" in ok.stdout
    path.write_text(PROD_2026_10_16)
    ko = subprocess.run(
        [sys.executable, str(script), "memory", "8192", "2048", str(2048 * MIB), "1536", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ko.returncode == 1 and "1536 MiB required" in ko.stdout


def test_b2_preflight_reads_proxmox_and_hides_the_token(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    blank_host: dict[str, Path],
    cafe: dict[str, Any],
    fake_pve: dict[str, Any],
) -> None:
    """B2: GO at a 3584 floor; three GETs with the Terraform token, which is never printed."""
    result = preflight(run_tasks, group_vars, blank_host, resolved(cafe))
    assert result.returncode == 0, result.stdout
    assert "GO: memory headroom for one more gateway" in result.stdout
    assert [(method, path) for method, path, _ in fake_pve["requests"]] == [
        ("GET", "/api2/json/cluster/resources?type=vm"),
        ("GET", "/api2/json/nodes/pve/qemu/9030/config"),
        ("GET", "/api2/json/nodes/pve/qemu/9030/status/current"),
    ]
    assert all(auth == f"PVEAPIToken=terraform@pve!tests={FAKE_PVE_SECRET}" for *_, auth in fake_pve["requests"])
    assert FAKE_PVE_SECRET not in result.stdout + result.stderr


def test_b2_preflight_no_go_at_a_2048_floor(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    blank_host: dict[str, Path],
    cafe: dict[str, Any],
    fake_pve: dict[str, Any],
) -> None:
    """B2: same guest reading, but Proxmox may take it back to 2048 MiB: NO-GO."""
    fake_pve.update(balloon=2048, actual=8192)
    blank_host["meminfo"].write_text(meminfo(7946, 6700))
    result = preflight(run_tasks, group_vars, blank_host, resolved(cafe))
    assert result.returncode != 0
    assert "at the balloon floor ~556 MiB would remain" in result.stdout
    assert FAKE_PVE_SECRET not in result.stdout + result.stderr


def test_b2_preflight_no_go_without_proxmox_credentials(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    blank_host: dict[str, Path],
    cafe: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B2: no API token in the environment, the floor cannot be checked: NO-GO."""
    monkeypatch.delenv("TF_VAR_pm_api_token_secret")
    result = preflight(run_tasks, group_vars, blank_host, resolved(cafe))
    assert result.returncode != 0
    assert "TF_VAR_pm_api_token_secret absent" in result.stdout


def test_b2_preflight_no_go_when_the_vm_is_not_in_proxmox(
    run_tasks: RunTasks,
    group_vars: dict[str, Any],
    blank_host: dict[str, Path],
    cafe: dict[str, Any],
    fake_pve: dict[str, Any],
) -> None:
    """B2: the inventory name must match exactly one Proxmox VM (an LXC of the same name does not count)."""
    fake_pve["vm_name"] = "another-vm"
    result = preflight(run_tasks, group_vars, blank_host, resolved(cafe))
    assert result.returncode != 0
    assert "0 VM nommee localhost" in result.stdout
