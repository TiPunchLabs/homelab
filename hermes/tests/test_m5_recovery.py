"""M5.3.B1 — Nora: preflight, backup and rollback of default, on disposable data.

The real m5_preflight.yml, m5_backup.yml and m5_rollback.yml run with
ansible-playbook against a throwaway directory standing in for
/opt/hermes/data, a real WAL SQLite database with commits still in its -wal,
and a fake `docker` on PATH. Nothing reaches hermes-30; every secret is fake.
Production restoration is NOT proven here.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import test_m2_cafe_ia as m2
import yaml
from conftest import FAKE_TOKEN, ROLE, RunTasks, recap
from test_m2_cafe_ia import GROUP_VARS, HERMES, TASKS, snapshot

sys.path.insert(0, str(ROLE / "files"))
sys.path.insert(0, str(ROLE / "filter_plugins"))

import hermes_checks as hc
import hermes_profiles as hp

data_dir = m2.data_dir

BACKUP_ID = "20261025T1400"
CONFIRM = f"ROLLBACK {BACKUP_ID}"
FAKE_TAVILY = "tvly-FAKE-nora-recovery-only"
FAKE_MANAGED = "DEEPSEEK_API_KEY=sk-FAKE-managed-only\nTELEGRAM_ALLOWED_USERS=1\n"
NORA_SOUL = (ROLE / "files/default/SOUL.md").read_text()
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
IMAGE = f"{DEFAULTS['hermes_image']}:{DEFAULTS['hermes_image_tag']}"
SECRETS = (FAKE_TOKEN, FAKE_TAVILY, "sk-FAKE-managed-only", "default-generated-1")
M5_TASKS = ("m5_preflight.yml", "m5_backup.yml", "m5_rollback.yml")
# Shape of /opt/hermes/data/gateway_state.json on hermes-30, 2026-10-24 (Hermes
# v0.20.4): same keys and types, fake values. active_agents is the int written by
# gateway/status.py write_runtime_status -> parse_active_agents, never a list.
GATEWAY_STATE: dict[str, Any] = {
    "gateway_state": "running",
    "desired_state": "running",
    "timestamp": 1761000000,
    "migrated_from": "gateway.pid",
    "updated_at": "2026-10-24T18:59:00+00:00",
    "platforms": {
        "api_server": {"state": "connected", "writer_pid": 160, "writer_start_time": 1714},
        "telegram": {"state": "connected", "writer_pid": 160, "writer_start_time": 1714},
    },
    "kind": "hermes-gateway",
    "pid": 160,
    "argv": ["/opt/hermes/.venv/bin/hermes", "gateway", "run", "--replace"],
    "start_time": 1714,
    "exit_reason": None,
    "restart_requested": False,
    "active_agents": 0,
}


# --- disposable host ------------------------------------------------------------


def make_db(path: Path, committed_in_main: int, committed_in_wal: int) -> sqlite3.Connection:
    """Create a WAL database shaped like state.db; return the open writer holding the -wal.

    Autocheckpoint is off, so the last `committed_in_wal` sessions live only in
    the -wal file while the connection stays open, as on hermes-30.
    """
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.executescript(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT);"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, content TEXT);"
        "CREATE TABLE system_prompts (hash TEXT PRIMARY KEY, prompt TEXT);"
    )
    for i in range(committed_in_main):
        conn.execute("INSERT INTO sessions VALUES (?, 'telegram')", (f"s{i}",))
        conn.execute("INSERT INTO messages (session_id, content) VALUES (?, 'contenu prive')", (f"s{i}",))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    for i in range(committed_in_main, committed_in_main + committed_in_wal):
        conn.execute("INSERT INTO sessions VALUES (?, 'cron')", (f"s{i}",))
    conn.commit()
    return conn


FAKE_DOCKER = r'''#!/usr/bin/env python3
"""Fake `docker`: container inspect and s6-svstat from a state file; logs every call."""
import json, os, sys
from pathlib import Path
state = json.loads(Path(os.environ["FAKE_STATE"]).read_text())
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
argv = sys.argv[1:]
if argv[:2] == ["container", "inspect"]:
    fmt = argv[3]
    print(state["image"] + (" sha256:fake 2026-10-20T16:06:11Z" if "StartedAt" in fmt else ""))
elif argv[:1] == ["exec"] and "/command/s6-svstat" in argv:
    print(state["svstat"].get(argv[-1].rsplit("/", 1)[-1], "s6-svstat: fatal: unable to read status"))
else:
    sys.exit(f"unexpected: {argv}")
'''


@pytest.fixture
def host(tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """default as hermes-30 shows it on 2026-10-24, plus a fake docker, managed layer and Compose file."""
    (data_dir / "config.yaml").write_text(
        "_config_version: 37\nmcp_servers:\n  kandidat:\n    url: https://kandidat.internal/mcp\n"
        "    connect_timeout: 20.0\n    enabled: true\n"
    )
    (data_dir / ".env").write_text(f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}\nAPI_SERVER_KEY=default-generated-1\n")
    (data_dir / ".env").chmod(0o600)
    (data_dir / "memories/MEMORY.md").chmod(0o600)
    (data_dir / "gateway_state.json").write_text(json.dumps(GATEWAY_STATE))
    for rel in ("workspace/lettres/lettre.md", "workspace/prospection/p.md", ".cache/huggingface/blob", "atr.html"):
        (data_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (data_dir / rel).write_text(f"historique {rel}\n")
    (data_dir / "skills/productivity/job-search-veille").mkdir(parents=True)
    (data_dir / "skills/productivity/job-search-veille/SKILL.md").write_text("# skill\n")
    writer = make_db(data_dir / "state.db", committed_in_main=3, committed_in_wal=2)
    (data_dir / "profiles/cafe-ia/state.db").write_bytes(b"not a database, never read")
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / ".env").write_text(FAKE_MANAGED)
    (managed / "config.yaml").write_text("model:\n  provider: deepseek\n")
    install = tmp_path / "install"
    install.mkdir()
    (install / "docker-compose.yml").write_text("services: {}\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
    (bindir / "docker").chmod(0o755)
    state = tmp_path / "docker-state.json"
    state.write_text(
        json.dumps(
            {
                "image": IMAGE,
                "svstat": {
                    f"gateway-{name}": f"up (pid {pid} pgid {pid}) 99 seconds{suffix}"
                    for name, pid, suffix in (
                        ("default", 160, ""),
                        ("cafe-ia", 5012, ", normally down"),
                        ("tech-watch", 5203, ", normally down"),
                        ("job-search", 7992, ", normally down"),
                    )
                },
            }
        )
    )
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:        3937472 kB\nMemAvailable:    1919872 kB\n")
    log = tmp_path / "docker.log"
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(state))
    monkeypatch.setenv("FAKE_LOG", str(log))
    try:
        yield {
            "data": data_dir,
            "backups": tmp_path / "backups",
            "archive": tmp_path / "archive",
            "state": state,
            "log": log,
            "writer": writer,
            "vars": {
                "hermes_data_dir": str(data_dir),
                "hermes_managed_dir": str(managed),
                "hermes_install_dir": str(install),
                "hermes_m5_backup_root": str(tmp_path / "backups"),
                "hermes_m5_archive_root": str(tmp_path / "archive"),
                "hermes_m5_db_reader": ["env"],
                "hermes_m5_min_free_mib": 1,
                "hermes_m5_max_disk_pcent": 100,
                "hermes_meminfo_path": str(meminfo),
                "hermes_default_profile": {},
            },
        }
    finally:
        writer.close()


def run_m5(run: RunTasks, host: dict[str, Any], tasks: str, *extra: str, **overrides: Any) -> Any:
    """Run one of the real M5 task files against the disposable host."""
    return run(tasks, {**DEFAULTS_M5, **host["vars"], **overrides}, *extra)


# Role defaults the task files read, as the role would provide them.
DEFAULTS_M5 = {
    k: v
    for k, v in DEFAULTS.items()
    if k.startswith("hermes_m5_") and k not in ("hermes_m5_db_reader",) or k in ("hermes_image", "hermes_image_tag")
}


def backup(run: RunTasks, host: dict[str, Any], *extra: str, **overrides: Any) -> Any:
    """Run m5_backup.yml with the test backup id."""
    return run_m5(run, host, "m5_backup.yml", *extra, hermes_m5_backup_id=BACKUP_ID, **overrides)


def rollback(run: RunTasks, host: dict[str, Any], *extra: str, **overrides: Any) -> Any:
    """Run m5_rollback.yml, confirmed, unless overridden."""
    variables = {"hermes_m5_backup_id": BACKUP_ID, "hermes_m5_rollback_confirm": CONFIRM, **overrides}
    return run_m5(run, host, "m5_rollback.yml", *extra, **variables)


def assert_no_secret(result: Any) -> None:
    """No fake secret, and no private row content, in the Ansible output."""
    out = result.stdout + result.stderr
    for secret in (*SECRETS, "contenu prive"):
        assert secret not in out, secret


def calls(host: dict[str, Any]) -> list[list[str]]:
    """The docker calls logged by the fake."""
    return [json.loads(x) for x in host["log"].read_text().splitlines()] if host["log"].exists() else []


def volume(host: dict[str, Any]) -> dict[str, bytes]:
    """Every file of the data volume except SQLite shared-memory files (a reader may touch them)."""
    return {k: v for k, v in snapshot(host["data"]).items() if not k.endswith("-shm")}


def apply_nora_by_hand(host: dict[str, Any]) -> None:
    """What M5.4 changes in default: SOUL, config keys, Tavily, a memory edited, history archived."""
    data = host["data"]
    (data / "SOUL.md").write_text(NORA_SOUL)
    cfg = yaml.safe_load((data / "config.yaml").read_text())
    cfg["mcp_servers"]["kandidat"]["enabled"] = False
    cfg["memory"] = {"write_approval": True}
    (data / "config.yaml").write_text(yaml.safe_dump(cfg))
    with (data / ".env").open("a") as env:
        env.write(f"TAVILY_API_KEY={FAKE_TAVILY}\n")
    (data / "memories/MEMORY.md").write_text("Préférence approuvée par l'utilisateur.\n")
    archive = host["archive"] / BACKUP_ID
    items = ["memories/USER.md", "workspace/lettres", "atr.html"]
    for rel in items:
        (archive / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(data / rel, archive / "data" / rel)
    (archive / "manifest.json").write_text(json.dumps({"items": items}))


# --- SQLite snapshot and report (pure) -----------------------------------------------


def test_b01_snapshot_keeps_commits_still_in_the_wal(tmp_path: Path) -> None:
    """The online backup reads through the -wal; a copy of the main file alone loses those commits."""
    writer = make_db(tmp_path / "state.db", committed_in_main=3, committed_in_wal=2)
    try:
        assert (tmp_path / "state.db-wal").stat().st_size > 0
        image = tmp_path / "image.db"
        image.write_bytes(hc.sqlite_snapshot(str(tmp_path / "state.db")))
        report = hc.sqlite_report(str(image))
        # The image keeps the WAL header: restored, it opens in the mode Hermes uses.
        assert report["ok"] and report["counts"]["sessions"] == 5 and report["wal"] is True
        naive = tmp_path / "naive.db"
        shutil.copyfile(tmp_path / "state.db", naive)
        assert hc.sqlite_report(str(naive))["counts"]["sessions"] == 3
    finally:
        writer.close()


def test_b01_snapshot_is_one_committed_state(tmp_path: Path) -> None:
    """An open, uncommitted write transaction is not in the image: no torn state."""
    writer = make_db(tmp_path / "state.db", committed_in_main=1, committed_in_wal=1)
    try:
        writer.execute("BEGIN")
        writer.execute("INSERT INTO sessions VALUES ('pending', 'telegram')")
        image = tmp_path / "image.db"
        image.write_bytes(hc.sqlite_snapshot(str(tmp_path / "state.db")))
        assert hc.sqlite_report(str(image))["counts"]["sessions"] == 2
    finally:
        writer.rollback()
        writer.close()


def test_b01_report_flags_damaged_copies(tmp_path: Path) -> None:
    """A truncated or foreign file is reported not ok, without a row of content."""
    writer = make_db(tmp_path / "state.db", committed_in_main=50, committed_in_wal=0)
    writer.close()
    truncated = tmp_path / "truncated.db"
    truncated.write_bytes((tmp_path / "state.db").read_bytes()[:5000])
    foreign = tmp_path / "foreign.db"
    foreign.write_text("pas une base")
    for path in (truncated, foreign):
        report = hc.sqlite_report(str(path))
        assert report["ok"] is False
        assert "contenu prive" not in json.dumps(report)


def test_b01_report_never_touches_the_file(tmp_path: Path) -> None:
    """immutable=1: no -wal or -shm created next to a copy at rest, bytes unchanged."""
    writer = make_db(tmp_path / "state.db", committed_in_main=2, committed_in_wal=0)
    writer.close()
    copy = tmp_path / "copy" / "state.db"
    copy.parent.mkdir()
    shutil.copyfile(tmp_path / "state.db", copy)
    before = copy.read_bytes()
    assert hc.sqlite_report(str(copy))["ok"]
    assert sorted(p.name for p in copy.parent.iterdir()) == ["state.db"]
    assert copy.read_bytes() == before


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("A=1\nTAVILY_API_KEY=x\n", "x"),
        ("export TAVILY_API_KEY = y \n", "y"),
        ("TAVILY_API_KEY=a\nTAVILY_API_KEY=b\n", "b"),
        ("TAVILY_API_KEY_OLD=z\n", ""),
        ("", ""),
    ],
)
def test_b01_dotenv_value(content: str, expected: str) -> None:
    """The rollback reads a key like dotenv; absent means "remove it"."""
    assert hp.hermes_dotenv_value("TAVILY_API_KEY", content) == expected


# --- m5_backup.yml ------------------------------------------------------------------


@pytest.mark.parametrize("backup_id", [None, "latest", "2026-10-25", "20261025T14001", "../x"])
def test_b02_backup_needs_an_explicit_id(run_tasks: RunTasks, host: dict[str, Any], backup_id: str | None) -> None:
    """No id, or a malformed one: refused before anything is written."""
    overrides = {} if backup_id is None else {"hermes_m5_backup_id": backup_id}
    result = run_m5(run_tasks, host, "m5_backup.yml", **overrides)
    assert result.returncode != 0
    assert "hermes_m5_backup_id" in result.stdout
    assert not host["backups"].exists()


def test_b03_backup_is_complete_private_and_verified(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """Files 0600 under a 0700 directory, SHA256SUMS valid, predecessor checksum recorded, no secret printed."""
    before = volume(host)
    result = backup(run_tasks, host)
    assert result.returncode == 0, result.stdout
    assert_no_secret(result)
    root = host["backups"] / BACKUP_ID
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    files = [p for p in root.rglob("*") if p.is_file()]
    assert files and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in files)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in root.rglob("*") if p.is_dir())
    check = subprocess.run(
        ["sha256sum", "--check", "--strict", "SHA256SUMS"], check=False, cwd=root, capture_output=True, text=True
    )
    assert check.returncode == 0, check.stdout
    listed = {line.split("  ", 1)[1] for line in (root / "SHA256SUMS").read_text().splitlines()}
    assert listed == {str(p.relative_to(root)) for p in files} - {"SHA256SUMS"}
    manifest = json.loads((root / "manifest.json").read_text())
    soul_sha = hashlib.sha256((host["data"] / "SOUL.md").read_bytes()).hexdigest()
    assert manifest["soul_predecessor_sha256"] == soul_sha
    assert manifest["identity_files"]["SOUL.md"]["sha256"] == soul_sha
    assert manifest["identity_files"][".env"]["mode"] == "0600"
    assert manifest["data_env_keys"] == ["TELEGRAM_BOT_TOKEN", "API_SERVER_KEY"]
    assert manifest["gateways"]["job-search"].startswith("up (pid 7992")
    assert manifest["container"].startswith(IMAGE)
    assert volume(host) == before


def test_b03_databases_are_consistent_images(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """state.db is copied with its -wal commits, verified, and the profiles' databases are left out."""
    assert backup(run_tasks, host).returncode == 0
    root = host["backups"] / BACKUP_ID
    manifest = json.loads((root / "manifest.json").read_text())
    assert list(manifest["databases"]) == ["state.db"]
    entry = manifest["databases"]["state.db"]
    assert entry["copy"] == "db/state.db"
    assert entry["report"]["ok"] is True and entry["report"]["counts"]["sessions"] == 5
    assert hc.sqlite_report(str(root / "db/state.db"))["counts"] == {"sessions": 5, "messages": 3, "system_prompts": 0}
    assert not list(root.glob("db/*-wal")) and not list(root.glob("db/*-shm"))


def test_b03_archive_keeps_modes_owners_and_excludes(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """data.tar.gz holds default's files with their modes and numeric owner; no profile, live DB or cache."""
    assert backup(run_tasks, host).returncode == 0
    with tarfile.open(host["backups"] / BACKUP_ID / "data.tar.gz") as tar:
        members = {m.name: m for m in tar.getmembers()}
    for name in ("./SOUL.md", "./memories/USER.md", "./workspace/lettres/lettre.md", "./atr.html", "./config.yaml"):
        assert name in members, name
    assert members["./.env"].mode == 0o600 and members["./.env"].uid == os.getuid()
    for name in members:
        assert not name.startswith("./profiles"), name
        assert not name.startswith("./.cache"), name
        assert not name.endswith((".db", ".db-wal", ".db-shm")), name


def test_b04_existing_backup_is_never_overwritten(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """A second backup under the same id fails and leaves the first byte-identical."""
    assert backup(run_tasks, host).returncode == 0
    first = snapshot(host["backups"])
    again = backup(run_tasks, host)
    assert again.returncode != 0
    assert "jamais ecrasee" in again.stdout
    assert snapshot(host["backups"]) == first


def test_b05_backup_check_mode_writes_nothing(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """--check: no backup directory, no database read, the volume unchanged."""
    before = volume(host)
    result = backup(run_tasks, host, "--check")
    assert result.returncode == 0, result.stdout
    assert not host["backups"].exists()
    assert volume(host) == before


def test_b06_backup_never_restarts_or_drives_hermes(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """Only `container inspect` and s6-svstat reach docker: no restart, no stop, no hermes CLI."""
    assert backup(run_tasks, host).returncode == 0
    for call in calls(host):
        assert call[:2] == ["container", "inspect"] or "/command/s6-svstat" in call, call


# --- m5_rollback.yml ----------------------------------------------------------------


@pytest.fixture
def after_nora(run_tasks: RunTasks, host: dict[str, Any]) -> dict[str, Any]:
    """A verified backup, then default changed as M5.4 would change it."""
    assert backup(run_tasks, host).returncode == 0
    host["before"] = volume(host)
    apply_nora_by_hand(host)
    host["nora"] = volume(host)
    return host


@pytest.mark.parametrize(
    "overrides",
    [
        {"hermes_m5_rollback_confirm": ""},
        {"hermes_m5_rollback_confirm": "ROLLBACK"},
        {"hermes_m5_rollback_confirm": "ROLLBACK 20261025T1401"},
        {"hermes_m5_rollback_confirm": "yes"},
        {"hermes_default_profile": {"soul_predecessor_sha256": "a" * 64}},
    ],
    ids=["empty", "no-id", "other-id", "yes", "nora-still-declared"],
)
def test_r01_rollback_needs_confirmation_and_nora_gone(
    run_tasks: RunTasks, after_nora: dict[str, Any], overrides: dict[str, Any]
) -> None:
    """Without the exact confirmation, or with Nora still in the inventory, nothing moves."""
    result = rollback(run_tasks, after_nora, **overrides)
    assert result.returncode != 0
    assert "Rien n'a ete modifie" in result.stdout
    assert volume(after_nora) == after_nora["nora"]
    assert not (after_nora["backups"] / BACKUP_ID / "rollback-saves").exists()


def test_r02_tampered_backup_is_refused(run_tasks: RunTasks, after_nora: dict[str, Any]) -> None:
    """A backup that no longer matches its SHA256SUMS is never restored from."""
    target = after_nora["backups"] / BACKUP_ID / "files/SOUL.md"
    target.chmod(0o600)
    target.write_text("altere\n")
    result = rollback(run_tasks, after_nora)
    assert result.returncode != 0
    assert volume(after_nora) == after_nora["nora"]


def test_r03_rollback_restores_default_and_saves_what_it_replaces(
    run_tasks: RunTasks, after_nora: dict[str, Any]
) -> None:
    """Byte-identical pre-Nora files and modes, Tavily removed, history back, Nora's state kept aside."""
    result = rollback(run_tasks, after_nora)
    assert result.returncode == 0, result.stdout
    assert_no_secret(result)
    assert volume(after_nora) == after_nora["before"]
    data = after_nora["data"]
    assert stat.S_IMODE((data / ".env").stat().st_mode) == 0o600
    assert stat.S_IMODE((data / "memories/MEMORY.md").stat().st_mode) == 0o600
    saves = list((after_nora["backups"] / BACKUP_ID / "rollback-saves").iterdir())
    assert len(saves) == 1
    assert (saves[0] / "SOUL.md").read_text() == NORA_SOUL
    assert (saves[0] / "memories/MEMORY.md").read_text() == "Préférence approuvée par l'utilisateur.\n"
    assert "kandidat" in (saves[0] / "config.yaml").read_text()
    assert not (after_nora["archive"] / BACKUP_ID / "data/atr.html").exists()
    assert (after_nora["archive"] / BACKUP_ID / "manifest.json").exists()
    assert "gateway restart" in result.stdout
    assert calls(after_nora) == [
        c for c in calls(after_nora) if c[:2] == ["container", "inspect"] or "/command/s6-svstat" in c
    ]


def test_r04_second_rollback_changes_nothing(run_tasks: RunTasks, after_nora: dict[str, Any]) -> None:
    """Replayable: once restored, a second confirmed run reports 0 changed and saves nothing new."""
    assert rollback(run_tasks, after_nora).returncode == 0
    restored = volume(after_nora)
    backups = snapshot(after_nora["backups"])
    second = rollback(run_tasks, after_nora)
    assert second.returncode == 0, second.stdout
    assert recap(second)["changed"] == 0
    assert volume(after_nora) == restored
    assert snapshot(after_nora["backups"]) == backups


def test_r05_archive_conflict_stops_before_any_write(run_tasks: RunTasks, after_nora: dict[str, Any]) -> None:
    """An archived item that is ALSO back in place: refuse, change nothing."""
    (after_nora["data"] / "atr.html").write_text("recree entre-temps\n")
    state = volume(after_nora)
    result = rollback(run_tasks, after_nora)
    assert result.returncode != 0
    assert "atr.html" in result.stdout
    assert volume(after_nora) == state


def test_r06_profiles_are_never_touched(run_tasks: RunTasks, after_nora: dict[str, Any]) -> None:
    """Kaféine's directory is byte-identical after a rollback."""
    profiles = snapshot(after_nora["data"] / "profiles")
    assert rollback(run_tasks, after_nora).returncode == 0
    assert snapshot(after_nora["data"] / "profiles") == profiles


def test_r07_rollback_check_mode_writes_nothing(run_tasks: RunTasks, after_nora: dict[str, Any]) -> None:
    """--check: the plan is computed, nothing is written or moved."""
    backups = snapshot(after_nora["backups"])
    result = rollback(run_tasks, after_nora, "--check")
    assert result.returncode == 0, result.stdout
    assert volume(after_nora) == after_nora["nora"]
    assert snapshot(after_nora["backups"]) == backups


def test_r08_databases_are_left_alone_by_default(run_tasks: RunTasks, after_nora: dict[str, Any]) -> None:
    """Without the explicit flag, a database that moved on after the backup stays as it is."""
    after_nora["writer"].execute("INSERT INTO sessions VALUES ('nora-1', 'telegram')")
    after_nora["writer"].commit()
    live = (after_nora["data"] / "state.db-wal").read_bytes()
    assert rollback(run_tasks, after_nora).returncode == 0
    assert (after_nora["data"] / "state.db-wal").read_bytes() == live


def test_r09_open_database_is_never_replaced(run_tasks: RunTasks, after_nora: dict[str, Any]) -> None:
    """With the flag, a database still open by a process (here: the test's writer) stops the rollback."""
    result = rollback(run_tasks, after_nora, hermes_m5_rollback_restore_databases=True)
    assert result.returncode != 0
    assert (after_nora["data"] / "state.db").exists()
    assert hc.sqlite_report(str(after_nora["backups"] / BACKUP_ID / "db/state.db"))["ok"]


def test_r10_closed_database_is_restored_with_its_sidecars_set_aside(
    run_tasks: RunTasks, after_nora: dict[str, Any]
) -> None:
    """Flag set, nothing holds the file: image restored, old main file and -wal moved aside together."""
    writer = after_nora["writer"]
    writer.execute("INSERT INTO sessions VALUES ('nora-1', 'telegram')")
    writer.commit()
    writer.close()  # last connection: checkpoints and removes the -wal
    # A sidecar left behind (crash, copy): it must leave together with the main file.
    (after_nora["data"] / "state.db-wal").write_bytes(b"stale sidecar")
    result = rollback(run_tasks, after_nora, hermes_m5_rollback_restore_databases=True)
    assert result.returncode == 0, result.stdout
    data = after_nora["data"]
    assert not (data / "state.db-wal").exists()
    report = hc.sqlite_report(str(data / "state.db"))
    assert report["ok"] and report["counts"]["sessions"] == 5
    saves = next((after_nora["backups"] / BACKUP_ID / "rollback-saves").iterdir())
    assert sorted(p.name for p in (saves / "db").iterdir())[:2] == ["state.db", "state.db-wal"]
    second = rollback(run_tasks, after_nora, hermes_m5_rollback_restore_databases=True)
    assert second.returncode == 0 and recap(second)["changed"] == 0


# --- m5_preflight.yml -----------------------------------------------------------------


def preflight(run: RunTasks, host: dict[str, Any], **overrides: Any) -> Any:
    """Run m5_preflight.yml with the real (unresolved) Nora declaration in scope."""
    nora = yaml.safe_load(GROUP_VARS.read_text())["hermes_default_nora"]
    return run_m5(run, host, "m5_preflight.yml", hermes_default_nora=nora, **overrides)


def test_p01_preflight_go_on_the_observed_state(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """The 2026-10-24 state is GO; Nora's vault references are never resolved; nothing written."""
    before = volume(host)
    result = preflight(run_tasks, host)
    assert result.returncode == 0, result.stdout
    assert "PREREQUIS" not in result.stdout
    assert "cle Tavily: ABSENTE" in result.stdout
    assert "job-search-veille" in result.stdout
    assert "kandidat.internal" not in result.stdout
    assert_no_secret(result)
    assert volume(host) == before
    assert not host["backups"].exists()


def mutate_state(host: dict[str, Any], **changes: Any) -> None:
    """Change the fake container state."""
    state = json.loads(host["state"].read_text())
    state.update(changes)
    host["state"].write_text(json.dumps(state))


@pytest.mark.parametrize(
    "case",
    ["nora-active", "gateway-down", "busy", "low-memory", "soul-mismatch", "id-taken", "image", "disk"],
)
def test_p02_preflight_no_go(run_tasks: RunTasks, host: dict[str, Any], case: str) -> None:
    """Each NO-GO condition fails the preflight on its own."""
    overrides: dict[str, Any] = {}
    if case == "nora-active":
        overrides["hermes_default_profile"] = {"soul_predecessor_sha256": "a" * 64}
    elif case == "gateway-down":
        svstat = json.loads(host["state"].read_text())["svstat"]
        svstat["gateway-tech-watch"] = "down (exitcode 1) 3 seconds, normally down"
        mutate_state(host, svstat=svstat)
    elif case == "busy":
        (host["data"] / "gateway_state.json").write_text(json.dumps({**GATEWAY_STATE, "active_agents": 1}))
    elif case == "low-memory":
        overrides["hermes_m5_min_available_mib"] = 4000
    elif case == "soul-mismatch":
        overrides["hermes_default_soul_predecessor_sha256"] = "0" * 64
    elif case == "id-taken":
        (host["backups"] / BACKUP_ID).mkdir(parents=True)
        overrides["hermes_m5_backup_id"] = BACKUP_ID
    elif case == "image":
        mutate_state(host, image="nousresearch/hermes-agent:latest")
    elif case == "disk":
        overrides["hermes_m5_max_disk_pcent"] = 0
    result = preflight(run_tasks, host, **overrides)
    assert result.returncode != 0, result.stdout
    assert_no_secret(result)


@pytest.mark.parametrize("count", [1, 2])
def test_p04_conversation_in_progress_is_no_go(run_tasks: RunTasks, host: dict[str, Any], count: int) -> None:
    """A valid active_agents above 0 reaches the GO gate and fails there, as NO-GO."""
    (host["data"] / "gateway_state.json").write_text(json.dumps({**GATEWAY_STATE, "active_agents": count}))
    result = preflight(run_tasks, host)
    assert result.returncode != 0, result.stdout
    assert f"active_agents {count}" in result.stdout
    assert "NO-GO M5" in result.stdout
    assert "active_agents illisible" not in result.stdout


# [] and [obj] fail too: Hermes v0.20.4 never writes a list (no compatibility kept).
@pytest.mark.parametrize(
    "raw",
    [-1, True, False, None, 1.5, 0.0, "0", "abc", [], [{"session": "x"}], {"n": 0}, "ABSENT", "NOT-JSON"],
)
def test_p05_unreadable_active_agents_fails_instead_of_counting_as_zero(
    run_tasks: RunTasks, host: dict[str, Any], raw: Any
) -> None:
    """Anything but a non-negative int stops the preflight as FAIL before the GO gate."""
    state = {k: v for k, v in GATEWAY_STATE.items() if k != "active_agents"}
    if raw == "NOT-JSON":
        content = '{"active_agents": 0,'
    elif raw == "ABSENT":
        content = json.dumps(state)
    else:
        content = json.dumps({**state, "active_agents": raw})
    (host["data"] / "gateway_state.json").write_text(content)
    result = preflight(run_tasks, host)
    assert result.returncode != 0, result.stdout
    assert "NO-GO M5" not in result.stdout
    assert "Report the M5 preflight state" not in result.stdout
    if raw != "NOT-JSON":
        assert "FAIL M5 : active_agents illisible" in result.stdout
    assert_no_secret(result)


def test_p06_preflight_go_reaches_and_passes_the_gate(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """active_agents 0 (int) lets every later check run; the GO gate itself is evaluated and passes."""
    result = preflight(run_tasks, host)
    assert result.returncode == 0, result.stdout
    assert "default active_agents : 0" in result.stdout
    gate = result.stdout.split("TASK [hermes_agent : Assert the M5 GO conditions]", 1)
    assert len(gate) == 2 and gate[1].lstrip("*\n ").startswith("ok: [localhost]"), result.stdout


def test_p03_declared_predecessor_matching_is_go(run_tasks: RunTasks, host: dict[str, Any]) -> None:
    """Once hermes_default_soul_predecessor_sha256 is set to the live checksum, the preflight stays GO."""
    sha = hashlib.sha256((host["data"] / "SOUL.md").read_bytes()).hexdigest()
    result = preflight(run_tasks, host, hermes_default_soul_predecessor_sha256=sha)
    assert result.returncode == 0, result.stdout
    assert "empreinte : declaree" in result.stdout


# --- Static guards ----------------------------------------------------------------------


def test_s01_m5_tasks_are_never_part_of_a_deployment() -> None:
    """deploy.yml and main.yml never reach the M5 task files; only the m5-*.yml playbooks do."""
    for path in (HERMES / "ansible/deploy.yml", TASKS / "main.yml", TASKS / "profiles.yml", TASKS / "profile.yml"):
        text = path.read_text()
        for name in M5_TASKS:
            assert name not in text, (path.name, name)
    for play, tasks in (
        ("m5-preflight.yml", "m5_preflight.yml"),
        ("m5-backup.yml", "m5_backup.yml"),
        ("m5-rollback.yml", "m5_rollback.yml"),
    ):
        assert f"tasks_from: {tasks}" in (HERMES / "ansible" / play).read_text()


def test_s02_backup_and_rollback_start_with_their_guard() -> None:
    """The first task of the backup checks its id, the first of the rollback its confirmation."""
    first_backup = yaml.safe_load((TASKS / "m5_backup.yml").read_text())[0]
    assert "hermes_m5_backup_id is defined" in first_backup["ansible.builtin.assert"]["that"]
    first_rollback = yaml.safe_load((TASKS / "m5_rollback.yml").read_text())[0]
    assert any("hermes_m5_rollback_confirm" in c for c in first_rollback["ansible.builtin.assert"]["that"])
    assert (
        yaml.safe_load((HERMES / "ansible/m5-backup.yml").read_text())[0]["tasks"][0]["ansible.builtin.include_role"][
            "tasks_from"
        ]
        == "m5_preflight.yml"
    )


def test_s03_no_restart_no_deletion_no_hermes_cli() -> None:
    """No handler, compose, `hermes` command, `state: absent` or rm in the M5 task files."""
    for name in M5_TASKS:
        text = (TASKS / name).read_text()
        for task in yaml.safe_load(text):
            assert "notify" not in task, (name, task.get("name"))
            argv = (task.get("ansible.builtin.command") or {}).get("argv", [])
            if isinstance(argv, list) and argv[:1] == ["docker"]:
                assert "hermes" not in argv[argv.index("hermes") + 1 :], (name, task["name"])
            assert not (isinstance(argv, list) and argv[:1] == ["rm"])
            assert (task.get("ansible.builtin.file") or {}).get("state") != "absent"
        assert "docker_compose" not in text and "flush_handlers" not in text
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert "rm -" not in code and "trash" not in code
    # The only restart in M5 is the one the operator types, printed by the rollback report.
    report = yaml.safe_load((TASKS / "m5_rollback.yml").read_text())[-1]
    assert any("gateway restart" in line for line in report["ansible.builtin.debug"]["msg"])


def test_s04_profiles_and_previous_backups_are_out_of_reach() -> None:
    """The archive excludes profiles; the M1 backup and the M5 root are distinct; no retention cleanup."""
    assert "./profiles" in DEFAULTS["hermes_m5_tar_excludes"]
    assert DEFAULTS["hermes_m5_backup_root"] != DEFAULTS["hermes_m1_backup_dir"]
    for name in M5_TASKS:
        text = (TASKS / name).read_text()
        assert "hermes_m1_backup_dir" not in text
        assert "-mtime" not in text and "retention" not in text.lower()


def test_s05_db_reader_drops_to_the_agent_uid() -> None:
    """In production the snapshot runs as the agent UID, so no root-owned -shm can appear."""
    reader = DEFAULTS["hermes_m5_db_reader"]
    assert reader[0] == "setpriv"
    assert "--reuid={{ hermes_puid }}" in reader and "--regid={{ hermes_pgid }}" in reader
    assert "--clear-groups" in reader
