"""Run the real hermes_agent host-side task files against a fake HERMES_HOME.

Covers the .env key management (T01, T04, T07, T18, T20), the SOUL.md seed
(T05-T07), the owned-content copy (T14, T17) and the inventory guards
(T08-T11). Run from the repo root:
    uv run pytest hermes/tests -q
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from conftest import FAKE_TOKEN, FAKE_TOKEN_2, ROLE, RunTasks, recap

ENV_BEFORE = (
    "# Per-profile secrets for this Hermes profile.\n"
    "MY_CUSTOM_VAR=keep me\n"
    "TELEGRAM_HOME_CHANNEL=1111111111\n"
    "\n"
    "HERMES_SOMETHING=agent-written\n"
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A stand-in for /opt/hermes/data with agent-owned files around."""
    data = tmp_path / "data"
    (data / "memories").mkdir(parents=True)
    (data / "memories" / "MEMORY.md").write_text("fact the agent learned\n")
    (data / "sessions").mkdir()
    (data / "sessions" / "s1.json").write_text("{}\n")
    return data


def snapshot(root: Path, exclude: set[str] = frozenset()) -> dict[str, bytes]:
    """Map every file under `root` (minus `exclude`) to its content."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and str(p.relative_to(root)) not in exclude
    }


def env_keys(run: RunTasks, path: Path, keys: dict[str, str], *args: str) -> Any:
    """Run env_keys.yml on `path` with `keys`."""
    return run("env_keys.yml", {"hermes_env_path": str(path), "hermes_env_keys": keys}, *args)


# --- .env keys --------------------------------------------------------------


def test_t01_creates_default_env_with_the_token_only(run_tasks: RunTasks, data_dir: Path) -> None:
    """T01: absent .env is created, 0600, with TELEGRAM_BOT_TOKEN and nothing else."""
    env = data_dir / ".env"
    result = env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN})
    assert result.returncode == 0, result.stdout
    assert env.read_text() == f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert env.stat().st_uid == os.getuid()


def test_t04_preserves_other_variables(run_tasks: RunTasks, data_dir: Path) -> None:
    """T04: only the managed key changes; custom and Hermes variables stay intact."""
    env = data_dir / ".env"
    env.write_text(ENV_BEFORE)
    assert env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}).returncode == 0
    assert env.read_text() == ENV_BEFORE + f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}\n"

    # A rotated token replaces the line in place, nothing else moves.
    assert env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN_2}).returncode == 0
    assert env.read_text() == ENV_BEFORE + f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN_2}\n"


def test_t04_replaces_an_export_form_in_place(run_tasks: RunTasks, data_dir: Path) -> None:
    """T04: `export KEY=` (valid dotenv) is rewritten, not duplicated."""
    env = data_dir / ".env"
    env.write_text(f"A=1\nexport TELEGRAM_BOT_TOKEN={FAKE_TOKEN_2}\nB=2\n")
    assert env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}).returncode == 0
    assert env.read_text() == f"A=1\nTELEGRAM_BOT_TOKEN={FAKE_TOKEN}\nB=2\n"


def test_t04_refuses_duplicated_keys_without_touching_the_file(run_tasks: RunTasks, data_dir: Path) -> None:
    """T04: a duplicated managed key fails closed; the file is left as is, no value shown."""
    env = data_dir / ".env"
    content = f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN_2}\nX=1\nTELEGRAM_BOT_TOKEN={FAKE_TOKEN_2}\n"
    env.write_text(content)
    result = env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN})
    assert result.returncode != 0
    assert "plusieurs fois" in result.stdout
    assert env.read_text() == content
    assert FAKE_TOKEN not in result.stdout + result.stderr
    assert FAKE_TOKEN_2 not in result.stdout + result.stderr


def test_t07_env_keys_second_run_changes_nothing(run_tasks: RunTasks, data_dir: Path) -> None:
    """T07: second pass reports 0 changed and leaves the bytes and inode alone."""
    env = data_dir / ".env"
    env.write_text(ENV_BEFORE)
    assert env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}).returncode == 0
    before = (env.read_bytes(), env.stat().st_ino, env.stat().st_mtime_ns)
    second = env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN})
    assert second.returncode == 0
    assert recap(second)["changed"] == 0
    assert (env.read_bytes(), env.stat().st_ino, env.stat().st_mtime_ns) == before


def test_t18_tokens_never_appear_in_ansible_output(run_tasks: RunTasks, data_dir: Path) -> None:
    """T18: even with --diff and -v, the token value is never printed."""
    env = data_dir / ".env"
    env.write_text(ENV_BEFORE)
    result = env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}, "--diff", "-v")
    assert result.returncode == 0
    assert FAKE_TOKEN not in result.stdout + result.stderr
    assert "censored" in result.stdout


def test_t20_rollback_removes_only_the_token(run_tasks: RunTasks, data_dir: Path) -> None:
    """T20: the targeted rollback (empty value -> key removed) restores the original bytes."""
    env = data_dir / ".env"
    env.write_text(ENV_BEFORE)
    assert env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}).returncode == 0
    rollback = env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": ""})
    assert rollback.returncode == 0
    assert env.read_text() == ENV_BEFORE
    assert FAKE_TOKEN not in rollback.stdout + rollback.stderr


def test_env_keys_check_mode_writes_nothing(run_tasks: RunTasks, data_dir: Path) -> None:
    """`--check --diff` (deployment preflight) succeeds, writes nothing, shows no token."""
    env = data_dir / ".env"
    env.write_text(ENV_BEFORE)
    result = env_keys(run_tasks, env, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}, "--check", "--diff")
    assert result.returncode == 0, result.stdout
    assert env.read_text() == ENV_BEFORE
    assert FAKE_TOKEN not in result.stdout + result.stderr
    absent = env_keys(run_tasks, data_dir / "missing.env", {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}, "--check")
    assert absent.returncode == 0, absent.stdout
    assert not (data_dir / "missing.env").exists()


# --- SOUL.md seed -----------------------------------------------------------

SEED = "Tu es **Alex**.\n"
STOCK = "You are Hermes Agent, an intelligent AI assistant created by Nous Research."


def seed(run: RunTasks, tmp_path: Path, dest: Path, content: str = SEED, data_dir: Path | None = None) -> Any:
    """Run soul_seed.yml with a delivered SOUL.md and the fixture stock checksum.

    `dest` is normally <data>/profiles/<name>/SOUL.md, so <data> defaults to
    its third parent.
    """
    src = tmp_path / "SOUL.seed.md"
    src.write_text(content)
    return run(
        "soul_seed.yml",
        {
            "hermes_soul_src": str(src),
            "hermes_soul_dest": str(dest),
            "hermes_soul_stock_sha256": [hashlib.sha256(STOCK.encode()).hexdigest()],
            "hermes_data_dir": str(data_dir or dest.parents[2]),
        },
    )


@pytest.fixture
def profile_soul(data_dir: Path) -> Path:
    """Path of an additional profile's SOUL.md, its directory created."""
    path = data_dir / "profiles" / "tech-watch" / "SOUL.md"
    path.parent.mkdir(parents=True)
    return path


def test_t05_customised_soul_is_never_touched(run_tasks: RunTasks, tmp_path: Path, profile_soul: Path) -> None:
    """T05: a SOUL.md edited by the user keeps its content, mode and mtime."""
    dest = profile_soul
    dest.write_text("Tu es Alex, version retouchee depuis le dashboard.\n")
    dest.chmod(0o640)
    before = (dest.read_bytes(), dest.stat().st_mode, dest.stat().st_mtime_ns)
    result = seed(run_tasks, tmp_path, dest)
    assert result.returncode == 0, result.stdout
    assert recap(result)["changed"] == 0
    assert (dest.read_bytes(), dest.stat().st_mode, dest.stat().st_mtime_ns) == before


def test_t06_absent_soul_is_seeded(run_tasks: RunTasks, tmp_path: Path, profile_soul: Path) -> None:
    """T06: no SOUL.md -> the delivered one is installed, 0644."""
    dest = profile_soul
    result = seed(run_tasks, tmp_path, dest)
    assert result.returncode == 0, result.stdout
    assert dest.read_text() == SEED
    assert stat.S_IMODE(dest.stat().st_mode) == 0o644


def test_t06_stock_soul_from_profile_create_is_replaced(run_tasks: RunTasks, tmp_path: Path, profile_soul: Path) -> None:
    """T06: `hermes profile create` writes the stock text first; the seed still lands."""
    dest = profile_soul
    dest.write_text(STOCK)
    assert seed(run_tasks, tmp_path, dest).returncode == 0
    assert dest.read_text() == SEED


def test_t07_seed_second_run_changes_nothing(run_tasks: RunTasks, tmp_path: Path, profile_soul: Path) -> None:
    """T07: once seeded, the next run is a no-op, even if the repo version changes."""
    dest = profile_soul
    assert seed(run_tasks, tmp_path, dest).returncode == 0
    second = seed(run_tasks, tmp_path, dest, content="new repo version\n")
    assert recap(second)["changed"] == 0
    assert dest.read_text() == SEED


@pytest.mark.parametrize("current", [STOCK, "Tu es Hermes, l'assistant de Xavier.\n"], ids=["stock", "custom"])
def test_default_soul_is_never_seeded(run_tasks: RunTasks, tmp_path: Path, data_dir: Path, current: str) -> None:
    """M1 review §2: default's SOUL.md is refused as a target, even when it is the stock text."""
    dest = data_dir / "SOUL.md"
    dest.write_text(current)
    before = (dest.read_bytes(), dest.stat().st_mode, dest.stat().st_mtime_ns, dest.stat().st_ino)
    result = seed(run_tasks, tmp_path, dest, data_dir=data_dir)
    assert result.returncode != 0
    assert "jamais le SOUL.md de default" in result.stdout
    assert (dest.read_bytes(), dest.stat().st_mode, dest.stat().st_mtime_ns, dest.stat().st_ino) == before


@pytest.mark.parametrize("target", ["profiles/default/SOUL.md", "profiles/tech-watch/../../SOUL.md", "profiles/a/b/SOUL.md"])
def test_soul_seed_refuses_paths_outside_a_profile(run_tasks: RunTasks, tmp_path: Path, data_dir: Path, target: str) -> None:
    """The seed target must be exactly <data>/profiles/<name>/SOUL.md, never default."""
    result = seed(run_tasks, tmp_path, data_dir / target, data_dir=data_dir)
    assert result.returncode != 0
    assert not (data_dir / "SOUL.md").exists()


# --- owned content ----------------------------------------------------------


def test_t14_bytecode_is_not_deployed(run_tasks: RunTasks, tmp_path: Path, data_dir: Path) -> None:
    """T14: __pycache__, *.pyc, *.pyo and SOUL.md stay out; sources are copied."""
    src = tmp_path / "profile-src"
    (src / "scripts" / "__pycache__").mkdir(parents=True)
    (src / "scripts" / "collect.py").write_text("print('ok')\n")
    (src / "scripts" / "sources.yaml").write_text("sources: []\n")
    (src / "scripts" / "__pycache__" / "collect.cpython-312.pyc").write_bytes(b"\x00")
    (src / "scripts" / "stray.pyo").write_bytes(b"\x00")
    (src / "SOUL.md").write_text(SEED)
    dest = data_dir / "profiles" / "tech-watch"
    dest.mkdir(parents=True)

    result = run_tasks("profile_content.yml", {"hermes_content_src": str(src), "hermes_content_dest": str(dest)})
    assert result.returncode == 0, result.stdout
    deployed = sorted(str(p.relative_to(dest)) for p in dest.rglob("*"))
    assert deployed == ["scripts", "scripts/collect.py", "scripts/sources.yaml"]

    second = run_tasks("profile_content.yml", {"hermes_content_src": str(src), "hermes_content_dest": str(dest)})
    assert recap(second)["changed"] == 0


def test_t14_real_tech_watch_payload_has_no_cache(run_tasks: RunTasks, data_dir: Path) -> None:
    """T14: the shipped tech-watch content deploys its scripts but no bytecode."""
    dest = data_dir / "profiles" / "tech-watch"
    dest.mkdir(parents=True)
    src = ROLE / "files" / "profiles" / "tech-watch"
    result = run_tasks("profile_content.yml", {"hermes_content_src": str(src), "hermes_content_dest": str(dest)})
    assert result.returncode == 0, result.stdout
    deployed = {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()}
    assert "scripts/tech_watch_collect.py" in deployed
    assert "SOUL.md" not in deployed
    assert not any("__pycache__" in p or p.endswith((".pyc", ".pyo")) for p in deployed)


def test_t17_host_tasks_leave_agent_data_alone(run_tasks: RunTasks, tmp_path: Path, data_dir: Path) -> None:
    """T17: env, seed and content tasks never modify or delete agent-owned files."""
    profile = data_dir / "profiles" / "tech-watch"
    (profile / "memories").mkdir(parents=True)
    (profile / "memories" / "USER.md").write_text("user facts\n")
    (profile / ".env").write_text(ENV_BEFORE)
    before = snapshot(data_dir, exclude={"profiles/tech-watch/.env", "profiles/tech-watch/SOUL.md"})

    assert env_keys(run_tasks, profile / ".env", {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}).returncode == 0
    assert seed(run_tasks, tmp_path, profile / "SOUL.md").returncode == 0
    src = ROLE / "files" / "profiles" / "tech-watch"
    content = run_tasks("profile_content.yml", {"hermes_content_src": str(src), "hermes_content_dest": str(profile)})
    assert content.returncode == 0

    after = snapshot(data_dir, exclude={"profiles/tech-watch/.env", "profiles/tech-watch/SOUL.md"})
    assert {k: v for k, v in after.items() if not k.startswith("profiles/tech-watch/scripts/")} == before


# --- inventory guards (validate.yml) ----------------------------------------

RESERVED = {"tech-watch": 8643, "daily-life": 8644, "job-search": 8645, "cafe-ia": 8646}


def validate(run: RunTasks, profiles: list[dict[str, Any]], **overrides: Any) -> Any:
    """Run validate.yml with a sane baseline inventory plus `overrides`."""
    variables = {
        "hermes_telegram_enabled": True,
        "hermes_telegram_bot_token": FAKE_TOKEN,
        "hermes_telegram_allowed_users": "1111111111",
        "hermes_profile_reserved_ports": RESERVED,
        "hermes_profiles": profiles,
        **overrides,
    }
    return run("validate.yml", variables)


def profile(name: str, token: str, port: int | None = None, **extra: Any) -> dict[str, Any]:
    """Build a profile definition."""
    return {"name": name, "telegram_bot_token": token, "api_server_port": port or RESERVED[name], **extra}


def assert_fails_quietly(result: Any) -> None:
    """The guard failed, and no token leaked into the output."""
    assert result.returncode != 0, result.stdout
    assert FAKE_TOKEN not in result.stdout + result.stderr
    assert FAKE_TOKEN_2 not in result.stdout + result.stderr


def test_validate_accepts_m1_and_a_good_profile(run_tasks: RunTasks) -> None:
    """Baseline: empty list (M1) and one well-formed profile both pass."""
    assert validate(run_tasks, []).returncode == 0
    ok = validate(run_tasks, [profile("tech-watch", FAKE_TOKEN_2)])
    assert ok.returncode == 0, ok.stdout


def test_t08_duplicate_tokens_fail_without_display(run_tasks: RunTasks) -> None:
    """T08: two profiles on one token, or a profile reusing default's token."""
    assert_fails_quietly(validate(run_tasks, [profile("tech-watch", FAKE_TOKEN_2), profile("cafe-ia", FAKE_TOKEN_2)]))
    assert_fails_quietly(validate(run_tasks, [profile("tech-watch", FAKE_TOKEN)]))


def test_t09_duplicate_or_unreserved_ports_fail(run_tasks: RunTasks) -> None:
    """T09: same port twice, default's port, or a port off the reservation table."""
    assert_fails_quietly(validate(run_tasks, [profile("tech-watch", FAKE_TOKEN_2, 8642)]))
    assert_fails_quietly(validate(run_tasks, [profile("tech-watch", FAKE_TOKEN_2, 8646)]))
    clash = {**RESERVED, "cafe-ia": 8643}
    assert_fails_quietly(
        validate(
            run_tasks,
            [profile("tech-watch", FAKE_TOKEN_2), profile("cafe-ia", "111:other-fake", 8643)],
            hermes_profile_reserved_ports=clash,
        )
    )


def test_t10_missing_tokens_fail(run_tasks: RunTasks) -> None:
    """T10: a profile without token, or default enabled without token."""
    assert_fails_quietly(validate(run_tasks, [profile("tech-watch", "")]))
    no_key = {"name": "tech-watch", "api_server_port": 8643}
    assert_fails_quietly(validate(run_tasks, [no_key]))
    assert_fails_quietly(validate(run_tasks, [], hermes_telegram_bot_token=""))


def test_t11_missing_or_malformed_allowlist_fails(run_tasks: RunTasks) -> None:
    """T11: empty, blank or non-numeric allowlist is refused before any write."""
    for allowlist in ("", "   ", "@someone", "1111111111,"):
        assert_fails_quietly(validate(run_tasks, [], hermes_telegram_allowed_users=allowlist))


def test_validate_rejects_per_profile_allowlist_and_reserved_env(run_tasks: RunTasks) -> None:
    """D3: the allowlist is global; a profile cannot carry or bypass it."""
    assert_fails_quietly(validate(run_tasks, [profile("tech-watch", FAKE_TOKEN_2, telegram_allowed_users="1")]))
    for key in ("TELEGRAM_ALLOW_ALL_USERS", "TELEGRAM_BOT_TOKEN", "API_SERVER_PORT", "GATEWAY_ALLOW_ALL_USERS"):
        bad = profile("tech-watch", FAKE_TOKEN_2, env={key: "true"})
        assert_fails_quietly(validate(run_tasks, [bad]))


def test_validate_rejects_unknown_or_reserved_names(run_tasks: RunTasks) -> None:
    """B3: only the definitive ids from the reservation table are accepted."""
    assert_fails_quietly(validate(run_tasks, [profile("tech-watch", FAKE_TOKEN_2) | {"name": "veille"}]))
    assert_fails_quietly(validate(run_tasks, [profile("tech-watch", FAKE_TOKEN_2) | {"name": "default"}]))
