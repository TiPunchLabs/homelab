"""M1 deployment operations: preflight, backup, rollback, --check of deploy.yml.

The backup and rollback task files run for real against a throwaway tree that
mimics hermes-30 before M1; nothing reaches the host. Tokens are fakes.
"""

from __future__ import annotations

import getpass
import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import FAKE_TOKEN, FAKE_TOKEN_2, REPO, ROLE, RunTasks, recap

sys.path.insert(0, str(ROLE / "files"))
from hermes_checks import schedule_window_verdict

DEPLOY = REPO / "hermes/ansible/deploy.yml"

MANAGED_ENV_PRE_M1 = (
    "# Ansible managed\n"
    "DEEPSEEK_API_KEY=sk-fake-not-a-key\n"
    f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}\n"
    "TELEGRAM_ALLOWED_USERS=8854358938\n"
)
MANAGED_ENV_M1 = (
    "# Ansible managed\n"
    "DEEPSEEK_API_KEY=sk-fake-not-a-key\n"
    "TELEGRAM_ALLOWED_USERS=8854358938\n"
    "TELEGRAM_ALLOW_ALL_USERS=false\n"
    "GATEWAY_ALLOW_ALL_USERS=false\n"
)
CONFIG = "model:\n  provider: deepseek\n"
COMPOSE = "services:\n  hermes:\n    network_mode: host\n"


# --- schedule window (cron catch-up) -----------------------------------------

NOW = datetime(2026, 10, 14, 1, 30, tzinfo=UTC)
WINDOW = timedelta(minutes=120)


def job(name: str = "veille-emploi", **fields: Any) -> dict[str, Any]:
    """A recurring weekly job shaped like hermes-30's jobs.json."""
    base: dict[str, Any] = {
        "id": "97fede01ad07",
        "name": name,
        "enabled": True,
        "state": "scheduled",
        "schedule": {"kind": "cron", "expr": "0 7 * * 1"},
        "next_run_at": "2026-10-19T07:00:00+00:00",
        "last_run_at": "2026-10-12T07:18:58+00:00",
        "last_status": "ok",
        "fire_claim": None,
        "prompt": "SECRET-PROMPT-TEXT",
    }
    return {**base, **fields}


def test_schedule_window_go_when_every_job_is_far() -> None:
    """The real hermes-30 shape at 01:30 UTC on Wednesday: GO with a 2 h window."""
    jobs = [
        job(),
        job("prospection-entreprises", next_run_at="2026-10-14T07:00:00+00:00"),
        job("ai-coffee-scout", next_run_at="2026-10-17T08:00:00+00:00"),
        job("rappel", enabled=False, state="completed", schedule={"kind": "once"}, next_run_at=None),
    ]
    blocking, lines = schedule_window_verdict(jobs, NOW, WINDOW)
    assert blocking == []
    assert len(lines) == 4
    assert "SECRET-PROMPT-TEXT" not in "\n".join(lines)


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"next_run_at": "2026-10-14T03:00:00+00:00"}, "inside the"),
        ({"next_run_at": "2026-10-14T01:00:00+00:00"}, "overdue"),
        ({"next_run_at": "2026-10-13T07:00:00+00:00"}, "overdue"),
        ({"fire_claim": {"at": "2026-10-14T01:20:00+00:00", "by": "x"}}, "in flight"),
        ({"schedule": {"kind": "interval", "minutes": 30}, "last_status": "error"}, "re-arms it to now"),
        ({"schedule": {"kind": "once", "run_at": "x"}, "next_run_at": None}, "one-shot"),
    ],
    ids=["due-soon", "just-missed", "missed-beyond-grace", "running", "interval-error", "oneshot-unknown"],
)
def test_schedule_window_blocks_what_a_restart_could_fire(fields: dict[str, Any], reason: str) -> None:
    """Anything Hermes v0.20.4 would run on the first tick after restart is a NO-GO."""
    blocking, lines = schedule_window_verdict([job(**fields)], NOW, WINDOW)
    assert len(blocking) == 1
    assert reason in blocking[0]
    assert "NO-GO" in lines[0]


def test_schedule_window_ignores_paused_jobs() -> None:
    """A disabled or paused job cannot fire, even if overdue."""
    overdue = "2026-10-13T07:00:00+00:00"
    jobs = [job(enabled=False, next_run_at=overdue), job(state="paused", next_run_at=overdue)]
    assert schedule_window_verdict(jobs, NOW, WINDOW)[0] == []


def test_schedule_window_cron_in_error_is_reported_not_blocking() -> None:
    """A cron-kind job in error is re-armed to its next LEGAL slot, never to now."""
    blocking, lines = schedule_window_verdict([job(last_status="error")], NOW, WINDOW)
    assert blocking == []
    assert "last_status=error" in lines[0]


# --- deploy.yml timezone pre_task under --check -------------------------------


def pre_tasks() -> list[dict[str, Any]]:
    """The deploy.yml pre_tasks, tags stripped."""
    tasks = yaml.safe_load(DEPLOY.read_text())[0]["pre_tasks"]
    return [{k: v for k, v in task.items() if k != "tags"} for task in tasks]


def test_timezone_read_runs_in_check_mode() -> None:
    """The read is check_mode: false; the write still never runs under --check."""
    read, write = pre_tasks()
    assert read["check_mode"] is False
    assert read["ansible.builtin.command"].startswith("timedatectl show")
    assert "check_mode" not in write
    assert write["when"] == "hermes_current_timezone.stdout != hermes_timezone"


@pytest.mark.parametrize("timezone", ["same", "other"])
def test_timezone_pre_tasks_pass_check_mode_without_changing_anything(tmp_path: Path, timezone: str) -> None:
    """`--check` gets through the pre_tasks whatever the host timezone (no become, no write)."""
    timedatectl = subprocess.run(
        ["timedatectl", "show", "-p", "Timezone", "--value"], capture_output=True, text=True, check=False
    )
    if timedatectl.returncode != 0:
        pytest.skip("timedatectl unavailable here")
    current = timedatectl.stdout.strip()
    wanted = current if timezone == "same" else ("Etc/UTC" if current != "Etc/UTC" else "America/Guadeloupe")
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False, "tasks": pre_tasks()}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", "play.yml", "--check",
         "-e", f"hermes_timezone={wanted}", "-e", f"ansible_python_interpreter={sys.executable}"],
        cwd=tmp_path,
        env={**os.environ, "ANSIBLE_CONFIG": str(tmp_path / "ansible.cfg"), "ANSIBLE_NOCOLOR": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert recap(result)["failed"] == 0
    assert recap(result)["changed"] == 0
    after = subprocess.run(
        ["timedatectl", "show", "-p", "Timezone", "--value"], capture_output=True, text=True, check=False
    )
    assert after.stdout.strip() == current


# --- preflight is read-only ----------------------------------------------------

WRITE_MODULES = {
    "ansible.builtin.copy", "ansible.builtin.template", "ansible.builtin.file", "ansible.builtin.lineinfile",
    "ansible.builtin.include_tasks", "ansible.builtin.import_tasks", "community.docker.docker_compose_v2",
}


def test_preflight_is_read_only() -> None:
    """No write module; every command is a read that also runs under --check."""
    for task in yaml.safe_load((ROLE / "tasks/preflight.yml").read_text()):
        assert not WRITE_MODULES & task.keys(), task["name"]
        if "ansible.builtin.command" in task:
            assert task["changed_when"] is False, task["name"]
            assert task["check_mode"] is False, task["name"]


# --- backup and rollback ------------------------------------------------------


@pytest.fixture
def host(tmp_path: Path) -> dict[str, Path]:
    """A pre-M1 hermes-30 tree: token in managed, no default .env."""
    install = tmp_path / "opt-hermes"
    managed, data = install / "managed", install / "data"
    (data / "cron").mkdir(parents=True)
    managed.mkdir()
    (managed / ".env").write_text(MANAGED_ENV_PRE_M1)
    (managed / "config.yaml").write_text(CONFIG)
    (install / "docker-compose.yml").write_text(COMPOSE)
    (data / "cron" / "jobs.json").write_text('{"jobs": []}\n')
    (data / "SOUL.md").write_text("identity\n")
    return {"install": install, "managed": managed, "data": data, "backup": tmp_path / "backup"}


def ops_vars(host: dict[str, Path]) -> dict[str, Any]:
    """Variables pointing the role at the throwaway tree."""
    return {
        "hermes_install_dir": str(host["install"]),
        "hermes_managed_dir": str(host["managed"]),
        "hermes_data_dir": str(host["data"]),
        "hermes_m1_backup_dir": str(host["backup"]),
        "hermes_managed_owner": getpass.getuser(),
        "hermes_m1_rollback_restart": False,
    }


def apply_m1(host: dict[str, Path], default_env_token: str = FAKE_TOKEN) -> None:
    """What the M1 deployment does to the files: token leaves managed, lands in data/.env."""
    (host["managed"] / ".env").write_text(MANAGED_ENV_M1)
    env = host["data"] / ".env"
    content = env.read_text() if env.exists() else ""
    line = f"TELEGRAM_BOT_TOKEN={default_env_token}\n"
    lines = [line if old.startswith("TELEGRAM_BOT_TOKEN=") else old for old in content.splitlines(keepends=True)]
    env.write_text("".join(lines) if line in lines else content + line)
    env.chmod(0o600)


def assert_no_token(result: Any) -> None:
    """No fake token in Ansible's output."""
    assert FAKE_TOKEN not in result.stdout + result.stderr
    assert FAKE_TOKEN_2 not in result.stdout + result.stderr


def test_backup_records_the_absent_default_env_and_protects_copies(run_tasks: RunTasks, host: dict[str, Path]) -> None:
    """data/.env absent -> absence recorded; dir 0700, every copy 0600, no secret printed."""
    result = run_tasks("m1_backup.yml", ops_vars(host), "--diff", "-v")
    assert result.returncode == 0, result.stdout
    assert_no_token(result)
    backup = host["backup"]
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    manifest = json.loads((backup / "manifest.json").read_text())
    assert manifest["data_env_present"] is False
    assert "data.env" not in manifest["files"]
    assert set(manifest["files"]) == {"managed.env", "managed.config.yaml", "docker-compose.yml", "jobs.json"}
    for path in backup.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name
    assert (backup / "managed.env").read_text() == MANAGED_ENV_PRE_M1


def test_backup_never_overwrites_an_existing_backup(run_tasks: RunTasks, host: dict[str, Path]) -> None:
    """A second backup run fails before writing; the first backup stays intact."""
    assert run_tasks("m1_backup.yml", ops_vars(host)).returncode == 0
    (host["managed"] / ".env").write_text(MANAGED_ENV_M1)
    second = run_tasks("m1_backup.yml", ops_vars(host))
    assert second.returncode != 0
    assert (host["backup"] / "managed.env").read_text() == MANAGED_ENV_PRE_M1


def test_rollback_when_default_env_was_absent(run_tasks: RunTasks, host: dict[str, Path]) -> None:
    """Managed regains the token; data/.env loses ONLY the token, keeps what the agent wrote since."""
    assert run_tasks("m1_backup.yml", ops_vars(host)).returncode == 0
    apply_m1(host)
    env = host["data"] / ".env"
    env.write_text("HERMES_WRITTEN_AFTER_M1=1\n" + env.read_text())

    result = run_tasks("m1_rollback.yml", ops_vars(host), "--diff", "-v")
    assert result.returncode == 0, result.stdout
    assert_no_token(result)
    assert (host["managed"] / ".env").read_text() == MANAGED_ENV_PRE_M1
    assert stat.S_IMODE((host["managed"] / ".env").stat().st_mode) == 0o640
    assert env.read_text() == "HERMES_WRITTEN_AFTER_M1=1\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert (host["data"] / "SOUL.md").read_text() == "identity\n"

    again = run_tasks("m1_rollback.yml", ops_vars(host))
    assert again.returncode == 0
    assert recap(again)["changed"] == 0


def test_rollback_restores_the_original_token_line_value(run_tasks: RunTasks, host: dict[str, Path]) -> None:
    """data/.env existed with its own token: that value comes back, other lines untouched."""
    env = host["data"] / ".env"
    env.write_text(f"A=1\nTELEGRAM_BOT_TOKEN={FAKE_TOKEN_2}\nB=2\n")
    env.chmod(0o600)
    assert run_tasks("m1_backup.yml", ops_vars(host)).returncode == 0
    assert json.loads((host["backup"] / "manifest.json").read_text())["data_env_present"] is True
    apply_m1(host, default_env_token=FAKE_TOKEN)

    result = run_tasks("m1_rollback.yml", ops_vars(host))
    assert result.returncode == 0, result.stdout
    assert_no_token(result)
    assert env.read_text() == f"A=1\nTELEGRAM_BOT_TOKEN={FAKE_TOKEN_2}\nB=2\n"
    assert (host["managed"] / ".env").read_text() == MANAGED_ENV_PRE_M1


def test_rollback_removes_the_key_when_default_env_had_none(run_tasks: RunTasks, host: dict[str, Path]) -> None:
    """data/.env existed WITHOUT a token: the key M1 added is removed, nothing else."""
    env = host["data"] / ".env"
    env.write_text("A=1\n")
    assert run_tasks("m1_backup.yml", ops_vars(host)).returncode == 0
    apply_m1(host)
    assert run_tasks("m1_rollback.yml", ops_vars(host)).returncode == 0
    assert env.read_text() == "A=1\n"


def test_rollback_refuses_a_post_m1_backup(run_tasks: RunTasks, host: dict[str, Path]) -> None:
    """A backup without the managed token would strand default without a bot: nothing is written."""
    apply_m1(host)
    assert run_tasks("m1_backup.yml", ops_vars(host)).returncode == 0
    before = {p: p.read_bytes() for p in (host["managed"] / ".env", host["data"] / ".env")}
    result = run_tasks("m1_rollback.yml", ops_vars(host))
    assert result.returncode != 0
    assert "pas un etat pre-M1" in result.stdout
    assert {p: p.read_bytes() for p in before} == before
    assert_no_token(result)
