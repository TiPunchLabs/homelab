"""Post-deploy checks run INSIDE the hermes container by the hermes_agent role.

Ansible passes this file to `python3 -c` (docker exec), so it must stay a
single self-contained script. The verdict logic lives in pure functions that
take plain data: hermes/tests feeds them fixtures, the container feeds them
what Hermes itself reads. Hermes modules are imported in `main()` only.

Nothing here ever prints a value read from a .env file: messages carry key
names, states and PIDs only.

Usage (argv after `-c`):
    managed <expected_allowlist>
    env-key <dotenv_path> <KEY>
    telegram <gateway_state.json> <s6 service name, e.g. gateway-default>
             [<platform key, e.g. cafe-ia:telegram (multiplexed profile)>]
    multiplex <root gateway_state.json> <profiles,csv incl. default>
    schedule-window <minutes>
    api-key <profile .env>                       (HERMES_HOME = the profile)
    toolsets <allowed,csv> <denied,csv> <no_mcp> (HERMES_HOME = the profile):
        toolset names AND the tools the model really receives
    bot-identity <profile .env | -> <expected bot username>
                                                 (`-`: token on stdin, for a
                                                 profile not created yet)
    listen <port>                                (on the HOST: reads `ss`)
    memory <memory> <balloon> <balloon bytes> <required MiB> [meminfo]
                                                 (on the HOST: Proxmox values)
    sqlite-snapshot <db>                         (on the HOST, as the agent UID):
                                                 consistent image on stdout
    sqlite-report <db copy>                      integrity + row counts, JSON

`schedule-window` is read-only: it reads the profile's jobs.json and prints
names, schedules and timestamps only, never a prompt. `bot-identity` calls
Telegram `getMe` (identity only: unlike getUpdates it steals no message) and
never prints the token, the URL that carries it, or an exception text.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Keys the managed layer must NEVER carry: it applies to every profile, last
# and with override. One bot token for all profiles makes `gateway run
# --replace` kill the other holder; one API port makes every gateway bind the
# same socket.
FORBIDDEN_MANAGED_ENV = ("TELEGRAM_BOT_TOKEN", "API_SERVER_PORT", "API_SERVER_HOST")

# Opt-ins that bypass TELEGRAM_ALLOWED_USERS (gateway/authz_mixin.py). Pinned
# to false in managed so no profile .env can open a bot.
ALLOW_ALL_FLAGS = ("TELEGRAM_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS")

_TRUTHY = {"true", "1", "yes"}
_S6_UP = re.compile(r"^up \(pid (\d+)\b")


def _id_set(raw: str) -> set[str]:
    """Normalize a comma-separated allowlist into a set of ids."""
    return {part.strip() for part in raw.split(",") if part.strip()}


def managed_errors(
    env: Mapping[str, str],
    config_keys: set[str],
    expected_allowlist: str,
) -> list[str]:
    """Return what is wrong with the managed layer as Hermes loaded it.

    `env` and `config_keys` come from hermes_cli.managed_scope, so this judges
    the layer actually mounted, not the template Ansible thinks it rendered.
    An empty `expected_allowlist` is itself an error: fail closed.
    """
    errors: list[str] = []
    if "model.provider" not in config_keys:
        errors.append("managed config not applied (model.provider not pinned)")
    errors += [f"{key} must not be in managed .env" for key in FORBIDDEN_MANAGED_ENV if key in env]

    expected = _id_set(expected_allowlist)
    actual = _id_set(env.get("TELEGRAM_ALLOWED_USERS", ""))
    if not expected:
        errors.append("no expected TELEGRAM_ALLOWED_USERS given")
    elif not actual:
        errors.append("TELEGRAM_ALLOWED_USERS missing or empty in managed .env")
    elif actual != expected:
        errors.append("TELEGRAM_ALLOWED_USERS in managed .env differs from inventory")

    for flag in ALLOW_ALL_FLAGS:
        if flag not in env:
            errors.append(f"{flag} not pinned in managed .env")
        elif env[flag].strip().lower() in _TRUTHY:
            errors.append(f"{flag} is enabled in managed .env")
    return errors


def env_key_errors(values: Mapping[str, str | None], key: str) -> list[str]:
    """Return an error unless `key` is defined with a non-empty value."""
    if not (values.get(key) or "").strip():
        return [f"{key} missing or empty"]
    return []


def telegram_verdict(
    state: Any,
    s6_status: str,
    pid_is_live: Callable[[Mapping[str, Any]], bool],
    platform: str = "telegram",
) -> tuple[bool, str]:
    """Decide whether Telegram is connected for the CURRENT gateway process.

    gateway_state.json is not a heartbeat: it is only rewritten on transitions
    and survives restarts. A `connected` entry is trusted only if it was
    written by the process s6 supervises right now, identified by (pid,
    start_time). Otherwise a bot that died at restart would still read
    `connected` from the previous life.

    `platform` is the entry key: `telegram` for the profile that owns the
    state file, `<profile>:telegram` for a profile served by the multiplexed
    root gateway (Hermes v0.22, gateway/run_adapters.py).
    """
    match = _S6_UP.match(s6_status.strip())
    if not match:
        return False, f"level 2: gateway not up under s6 ({s6_status.strip() or 'no output'})"
    s6_pid = int(match.group(1))

    if not isinstance(state, Mapping):
        return False, "level 3: gateway_state.json absent or malformed"
    if state.get("pid") != s6_pid:
        return False, f"level 3: gateway_state.json written by pid {state.get('pid')}, s6 runs {s6_pid}"
    if not pid_is_live(state):
        return False, "level 3: gateway_state.json belongs to a dead process"
    if state.get("gateway_state") != "running":
        return False, f"level 3: gateway_state is {state.get('gateway_state')!r}"

    platforms = state.get("platforms")
    entry = platforms.get(platform) if isinstance(platforms, Mapping) else None
    if not isinstance(entry, Mapping):
        return False, f"level 3: no {platform} entry (adapter not started: token missing?)"
    if (entry.get("writer_pid"), entry.get("writer_start_time")) != (state.get("pid"), state.get("start_time")):
        return False, f"level 3: {platform} entry left over from a previous gateway process"
    if entry.get("state") != "connected":
        return False, f"level 3: {platform} state is {entry.get('state')!r}"
    return True, f"{platform} connected (gateway pid {s6_pid})"


def multiplex_verdict(
    state: Any,
    s6_statuses: Mapping[str, str],
    expected_profiles: set[str],
    pid_is_live: Callable[[Mapping[str, Any]], bool],
) -> tuple[bool, str]:
    """Decide whether ONE multiplexed gateway serves exactly `expected_profiles`.

    Hermes v0.22: the root slot gateway-default is the only gateway process;
    named slots stay registered but down, and the served set is published as
    `served_profiles` in the root gateway_state.json by that same process.
    `s6_statuses` maps a slot name (gateway-<profile>) to its s6-svstat line.
    """
    match = _S6_UP.match((s6_statuses.get("gateway-default") or "").strip())
    if not match:
        return False, f"gateway-default not up under s6 ({(s6_statuses.get('gateway-default') or 'no output').strip()})"
    s6_pid = int(match.group(1))
    second = sorted(slot for slot, status in s6_statuses.items() if slot != "gateway-default" and _S6_UP.match(status.strip()))
    if second:
        return False, f"named gateway slot(s) up beside the multiplexer: {', '.join(second)}"
    if not isinstance(state, Mapping):
        return False, "gateway_state.json absent or malformed"
    if state.get("pid") != s6_pid:
        return False, f"gateway_state.json written by pid {state.get('pid')}, s6 runs {s6_pid}"
    if not pid_is_live(state):
        return False, "gateway_state.json belongs to a dead process"
    served = state.get("served_profiles")
    if not isinstance(served, list) or {str(p) for p in served} != expected_profiles:
        return False, f"served profiles {served!r}, expected {sorted(expected_profiles)}"
    return True, f"one multiplexed gateway (pid {s6_pid}) serves: {', '.join(sorted(expected_profiles))}"


def _parse_instant(value: Any, now: datetime) -> datetime | None:
    """Parse an ISO timestamp from jobs.json; naive values take now's zone."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=now.tzinfo)


def schedule_window_verdict(
    jobs: Sequence[Mapping[str, Any]],
    now: datetime,
    window: timedelta,
) -> tuple[list[str], list[str]]:
    """Decide whether the gateway may restart now without firing a job.

    Mirrors Hermes v0.20.4 cron/jobs.py (_get_due_jobs_locked): on the first
    tick after a restart, ANY enabled job whose next_run_at is already past
    fires once — within its grace window or beyond it (fast-forward + one
    catch-up run). A recurring `interval` job in `error` is re-armed to now.
    A non-null fire_claim/run_claim means a run is in flight: a restart kills
    it (at-most-once, the run is lost, not repeated).

    Returns (blocking reasons, one report line per job). Prompts are never read.
    """
    blocking: list[str] = []
    lines: list[str] = []
    for job in jobs:
        schedule = job.get("schedule") if isinstance(job.get("schedule"), Mapping) else {}
        kind = schedule.get("kind", "?")
        label = f"{job.get('name', '?')} ({job.get('id', '?')}, {kind} {schedule.get('expr') or schedule.get('run_at') or ''})"
        if not job.get("enabled", True) or job.get("state") == "paused":
            lines.append(f"{label}: disabled ({job.get('state')}), cannot fire")
            continue

        reasons: list[str] = []
        if job.get("fire_claim") or job.get("run_claim"):
            reasons.append("run in flight (claim held)")
        next_run = _parse_instant(job.get("next_run_at"), now)
        if next_run is None:
            if kind == "once":
                reasons.append("one-shot without a readable next_run_at")
        elif next_run <= now:
            reasons.append(f"overdue since {job.get('next_run_at')}: would fire on the first tick")
        elif next_run - now < window:
            reasons.append(f"due at {job.get('next_run_at')}, inside the {window} safety window")
        if kind == "interval" and job.get("last_status") == "error":
            reasons.append("interval job in error: Hermes re-arms it to now")

        status = (
            f"next_run_at={job.get('next_run_at')} last_run_at={job.get('last_run_at')} "
            f"last_status={job.get('last_status')}"
        )
        if next_run is not None and next_run > now:
            status += f" (in {next_run - now})"
        if reasons:
            blocking += [f"{job.get('name', '?')}: {reason}" for reason in reasons]
            lines.append(f"{label}: NO-GO, {'; '.join(reasons)} | {status}")
        else:
            lines.append(f"{label}: ok | {status}")
    return blocking, lines


def api_key_errors(profile_env_keys: set[str], effective_matches_managed: bool, managed_has_key: bool) -> list[str]:
    """Judge whether a profile gateway gets API_SERVER_KEY deterministically.

    The image's stage2 hook appends a random key to $HERMES_HOME/.env only,
    i.e. /opt/data/.env, never to profiles/<name>/.env. The managed .env is
    loaded last with override, so every gateway must end up with the managed
    key. A key in the profile .env would be dead weight at best, a second
    secret to leak at worst: refused. Booleans only, never a value.
    """
    errors: list[str] = []
    if not managed_has_key:
        errors.append("API_SERVER_KEY missing from managed .env")
    if "API_SERVER_KEY" in profile_env_keys:
        errors.append("API_SERVER_KEY present in the profile .env (must come from managed only)")
    if managed_has_key and not effective_matches_managed:
        errors.append("effective API_SERVER_KEY differs from the managed one")
    return errors


def toolset_errors(
    effective: Mapping[str, set[str]],
    allowed: set[str],
    denied: set[str],
    mcp_servers: set[str],
    require_no_mcp: bool,
) -> list[str]:
    """Judge the toolsets Hermes resolves for each platform of a profile.

    `effective` maps a platform to what hermes_cli.tools_config resolves for
    it (the gateway's own code path). Any toolset outside `allowed`, any
    `denied` one, and any MCP server when `require_no_mcp` is an error.
    """
    errors: list[str] = []
    for platform, toolsets in sorted(effective.items()):
        extra = sorted(toolsets - allowed)
        if extra:
            errors.append(f"{platform}: toolsets beyond the allowlist: {', '.join(extra)}")
        forbidden = sorted(toolsets & denied)
        if forbidden:
            errors.append(f"{platform}: denied toolsets enabled: {', '.join(forbidden)}")
    if require_no_mcp and mcp_servers:
        errors.append(f"MCP servers configured: {', '.join(sorted(mcp_servers))}")
    return errors


_MCP_OFF = {"false", "0", "no", "off"}


def enabled_mcp_servers(servers: Any) -> set[str]:
    """Return the MCP servers Hermes would connect, from config `mcp_servers`.

    Mirrors tools/mcp_tool.py v0.20.4 (`_parse_boolish(v.get("enabled", True),
    default=True)`): only an explicit false-ish `enabled` turns a server off;
    an absent, unknown or malformed value keeps it on, so the check fails
    closed. A disabled server (Kandidat on Nora) keeps its url in config.yaml.
    """
    if not isinstance(servers, Mapping):
        return set()
    enabled = set()
    for name, spec in servers.items():
        flag = spec.get("enabled", True) if isinstance(spec, Mapping) else True
        if flag is False or (isinstance(flag, str) and flag.strip().lower() in _MCP_OFF):
            continue
        enabled.add(str(name))
    return enabled


def tool_errors(exposed: Mapping[str, set[str]], expected: set[str]) -> list[str]:
    """Judge the tools the model really receives on each platform of a profile.

    `expected` is every tool of the allowed toolsets. Toolset names are not
    enough: a disabled toolset strips its tools from the allowed ones too (the
    `browser` toolset carries `web_search`), and a tool whose check_fn fails
    drops out of the registry. Not a key check: with `web.backend: tavily` the
    web tools register even without TAVILY_API_KEY (validate.yml covers it).
    """
    errors: list[str] = []
    for platform, tools in sorted(exposed.items()):
        extra = sorted(tools - expected)
        if extra:
            errors.append(f"{platform}: tools beyond the allowlist: {', '.join(extra)}")
        missing = sorted(expected - tools)
        if missing:
            errors.append(f"{platform}: allowed tools not exposed: {', '.join(missing)}")
    return errors


def bot_identity_errors(reply: Any, expected_username: str) -> list[str]:
    """Judge a Telegram getMe reply against the bot username declared in Git.

    Catches a valid token that belongs to ANOTHER bot (pasted in the wrong
    vault key): duplicates are caught by validate.yml, this is not.
    """
    if not isinstance(reply, Mapping) or reply.get("ok") is not True:
        code = reply.get("error_code") if isinstance(reply, Mapping) else None
        return [f"getMe refused the token (error_code={code})"]
    result = reply.get("result") if isinstance(reply.get("result"), Mapping) else {}
    if result.get("is_bot") is not True:
        return ["getMe: not a bot account"]
    actual = str(result.get("username") or "")
    if actual.lower() != expected_username.lower():
        return [f"token belongs to @{actual or '?'}, expected @{expected_username}"]
    return []


_LOOPBACK = ("127.", "[::1]", "::1")


def listen_errors(ss_output: str, port: int) -> list[str]:
    """Judge `ss -Hltn` output: `port` must listen, and on loopback only.

    The container runs with network_mode: host, so a non-loopback bind would
    be on the VM's LAN interface; UFW denies it, but the intent is that it
    never listens there in the first place.
    """
    locals_ = []
    for line in ss_output.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[3].rsplit(":", 1)[-1] == str(port):
            locals_.append(fields[3])
    if not locals_:
        return [f"nothing listens on port {port}"]
    exposed = sorted(addr for addr in locals_ if not addr.startswith(_LOOPBACK))
    if exposed:
        return [f"port {port} listens beyond loopback: {', '.join(exposed)}"]
    return []


def _meminfo_mib(text: str) -> dict[str, int]:
    """Parse /proc/meminfo into MiB per key (kB lines only)."""
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if len(fields) == 2 and fields[1] == "kB" and fields[0].isdigit():
            values[key] = int(fields[0]) // 1024
    return values


def balloon_floor_mib(memory_cfg: str, balloon_cfg: str) -> int | None:
    """Return the Proxmox ballooning floor in MiB, or None when the device is off.

    `memory` reads "8192" or "current=8192"; an absent `balloon` means "equal
    to memory" (device on, nothing reclaimed); 0 removes the device, so the
    guest keeps all its memory and nothing can be taken back.
    """
    memory = int(memory_cfg.split(",")[0].removeprefix("current="))
    if not balloon_cfg:
        return memory
    balloon = int(balloon_cfg)
    return None if balloon == 0 else balloon


def memory_verdict(
    meminfo: str, floor_mib: int | None, balloon_mib: int | None, required_mib: int
) -> tuple[list[str], str]:
    """Judge the memory headroom for one more gateway, now and at the balloon floor.

    The worst case is an ESTIMATE: Proxmox only guarantees the floor on the
    host side. The memory the guest never sees (kernel, balloon driver) is
    measured now as balloon size minus MemTotal, and assumed constant; the
    used memory is assumed not to grow. Returns (errors, summary).
    """
    info = _meminfo_mib(meminfo)
    total, available = info["MemTotal"], info["MemAvailable"]
    used = total - available
    errors = []
    if available < required_mib:
        errors.append(f"MemAvailable {available} MiB < {required_mib} MiB required now")
    if floor_mib is None:
        worst: int | None = available
        detail = "ballooning off, nothing can be reclaimed"
    elif balloon_mib is None or balloon_mib < total:
        worst, detail = None, "balloon size unknown"
        errors.append("balloon size unknown: the worst case cannot be estimated")
    else:
        unseen = balloon_mib - total
        worst = floor_mib - unseen - used
        detail = f"floor {floor_mib}, balloon now {balloon_mib}, unseen by the guest ~{unseen}, used {used}"
        if worst < required_mib:
            errors.append(f"at the balloon floor ~{worst} MiB would remain < {required_mib} MiB required (estimate)")
    summary = f"MemAvailable {available} MiB; worst case ~{worst} MiB ({detail}, MiB); required {required_mib} MiB"
    return errors, summary


def sqlite_snapshot(src: str, timeout_seconds: float = 10.0) -> bytes:
    """Return a consistent image of a live SQLite database, WAL content included.

    Same method as hermes_cli/backup.py (_safe_copy_db, v0.20.4): the online
    backup API from a read-only connection, here into memory, then
    serialized. Writers keep going; a page changed mid-copy restarts the
    step, so the image is one committed state. Copying the main file alone
    would drop every commit still in the -wal. Fails closed on a lock held
    longer than `timeout_seconds`.
    """
    import sqlite3
    import time

    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=0.0)
    memory = sqlite3.connect(":memory:")
    deadline = time.monotonic() + timeout_seconds

    def progress(status: int, _remaining: int, _total: int) -> None:
        """Abort when the source stays locked past the deadline."""
        nonlocal deadline
        now = time.monotonic()
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            if now >= deadline:
                raise TimeoutError(f"{src} locked for {timeout_seconds:g} s")
        else:
            deadline = now + timeout_seconds

    try:
        source.backup(memory, pages=256, progress=progress, sleep=0.1)
        return memory.serialize()
    finally:
        memory.close()
        source.close()


# Row counts recorded for the tables that matter to a rollback decision.
SQLITE_COUNTED_TABLES = ("sessions", "messages", "system_prompts")


def sqlite_report(path: str) -> dict[str, Any]:
    """Judge a database file without touching it: integrity and a few row counts.

    `immutable=1`: no lock, no -wal or -shm read or created. Meant for a copy
    at rest (a backup), not for a live database. Never returns row content.
    """
    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
        try:
            integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            counts = {
                t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                for t in SQLITE_COUNTED_TABLES
                if t in tables
            }
            with open(path, "rb") as handle:
                wal = handle.read(20)[18:20] == b"\x02\x02"
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "integrity": [f"{type(exc).__name__}: {exc}"], "counts": {}, "tables": 0, "wal": None}
    return {"ok": integrity == ["ok"], "integrity": integrity[:5], "counts": counts, "tables": len(tables), "wal": wal}


def _report(errors: list[str], ok_message: str) -> int:
    """Print the outcome and return the process exit code."""
    if errors:
        print("; ".join(errors))
        return 1
    print(ok_message)
    return 0


def main(argv: list[str]) -> int:
    """Dispatch a check against the live container state."""
    mode = argv[0] if argv else ""
    if mode == "managed" and len(argv) == 2:
        from hermes_cli import managed_scope as ms

        ms.invalidate_managed_cache()
        errors = managed_errors(ms.load_managed_env(), ms.managed_config_keys(), argv[1])
        return _report(errors, "managed scope applied: allowlist pinned, no token, no API port")
    if mode == "env-key" and len(argv) == 3:
        from dotenv import dotenv_values

        return _report(env_key_errors(dotenv_values(argv[1]), argv[2]), f"{argv[2]} present in {argv[1]}")
    if mode == "telegram" and len(argv) in (3, 4):
        import subprocess

        from gateway.status import runtime_status_pid_is_live

        svstat = subprocess.run(
            ["/command/s6-svstat", f"/run/service/{argv[2]}"],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            with open(argv[1], encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            state = None
        ok, message = telegram_verdict(
            state, svstat.stdout or svstat.stderr, runtime_status_pid_is_live, *argv[3:]
        )
        print(message)
        return 0 if ok else 1
    if mode == "multiplex" and len(argv) == 3:
        import subprocess

        from gateway.status import runtime_status_pid_is_live

        expected = {p for p in argv[2].split(",") if p}
        statuses = {}
        for profile in sorted(expected | {"default"}):
            svstat = subprocess.run(
                ["/command/s6-svstat", f"/run/service/gateway-{profile}"],
                capture_output=True,
                text=True,
                check=False,
            )
            statuses[f"gateway-{profile}"] = svstat.stdout or svstat.stderr
        try:
            with open(argv[1], encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            state = None
        ok, message = multiplex_verdict(state, statuses, expected, runtime_status_pid_is_live)
        print(message)
        return 0 if ok else 1
    if mode == "schedule-window" and len(argv) == 2:
        import hermes_time

        try:
            from hermes_constants import get_hermes_home

            home = Path(get_hermes_home())
        except ImportError:
            home = Path(os.environ.get("HERMES_HOME", "/opt/data"))
        jobs_file = home / "cron" / "jobs.json"
        try:
            with open(jobs_file, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            data = {"jobs": []}
        jobs = data.get("jobs", []) if isinstance(data, Mapping) else data
        now = hermes_time.now()
        blocking, lines = schedule_window_verdict(jobs, now, timedelta(minutes=int(argv[1])))
        estop = (home / "ESTOP").exists()
        print(f"now={now.isoformat()} jobs={jobs_file} ESTOP={'present' if estop else 'absent'}")
        print("\n".join(lines))
        print("NO-GO: " + "; ".join(blocking) if blocking else "GO: no job can fire across a restart now")
        return 1 if blocking else 0
    if mode == "api-key" and len(argv) == 2:
        import hmac

        from dotenv import dotenv_values
        from hermes_cli import managed_scope as ms
        from hermes_cli.env_loader import load_hermes_dotenv

        ms.invalidate_managed_cache()
        managed_key = ms.load_managed_env().get("API_SERVER_KEY") or ""
        load_hermes_dotenv()
        effective = os.environ.get("API_SERVER_KEY") or ""
        errors = api_key_errors(
            set(dotenv_values(argv[1])),
            hmac.compare_digest(effective, managed_key),
            bool(managed_key),
        )
        return _report(errors, "API_SERVER_KEY comes from managed only (deterministic)")
    if mode == "toolsets" and len(argv) == 4:
        import logging

        from hermes_cli.config import load_config
        from hermes_cli.env_loader import load_hermes_dotenv
        from hermes_cli.tools_config import _get_platform_tools

        # Same order as the gateway: the profile .env first, then the tools.
        load_hermes_dotenv()
        logging.disable(logging.CRITICAL)
        import model_tools
        from toolsets import resolve_toolset

        cfg = load_config()
        allowed = {t for t in argv[1].split(",") if t}
        effective = {p: set(_get_platform_tools(cfg, p)) for p in ("telegram", "cron", "api_server", "cli")}
        disabled = (cfg.get("agent") or {}).get("disabled_toolsets") or None
        exposed = {
            p: {
                d["function"]["name"]
                for d in model_tools.get_tool_definitions(
                    enabled_toolsets=sorted(ts), disabled_toolsets=disabled, quiet_mode=True
                )
            }
            for p, ts in effective.items()
        }
        errors = toolset_errors(
            effective,
            allowed,
            {t for t in argv[2].split(",") if t},
            enabled_mcp_servers(cfg.get("mcp_servers")),
            argv[3] == "true",
        ) + tool_errors(exposed, set().union(*(resolve_toolset(t) for t in allowed)))
        return _report(
            errors,
            f"toolsets restricted to: {', '.join(sorted(set().union(*effective.values())))}"
            f" | tools: {', '.join(sorted(set().union(*exposed.values())))}",
        )
    if mode == "bot-identity" and len(argv) == 3:
        import urllib.error
        import urllib.request

        if argv[1] == "-":
            token = sys.stdin.readline().strip()
        else:
            from dotenv import dotenv_values

            token = (dotenv_values(argv[1]).get("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            return _report(["TELEGRAM_BOT_TOKEN missing or empty"], "")
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=15) as resp:
                reply = json.load(resp)
        except urllib.error.HTTPError as exc:
            try:
                reply = json.load(exc)
            except ValueError:
                reply = {"ok": False, "error_code": exc.code}
        except (urllib.error.URLError, OSError) as exc:
            # The exception text could carry the URL, hence the token.
            return _report([f"api.telegram.org unreachable ({type(exc).__name__})"], "")
        return _report(bot_identity_errors(reply, argv[2]), f"token belongs to @{argv[2]}")
    if mode == "listen" and len(argv) == 2:
        import subprocess

        ss = subprocess.run(["ss", "-Hltn"], capture_output=True, text=True, check=False)
        return _report(listen_errors(ss.stdout, int(argv[1])), f"port {argv[1]} listens on loopback only")
    if mode == "memory" and len(argv) in (5, 6):
        meminfo = Path(argv[5] if len(argv) == 6 else "/proc/meminfo").read_text()
        floor = balloon_floor_mib(argv[1], argv[2])
        balloon = int(argv[3]) // 1048576 if argv[3] else None
        errors, summary = memory_verdict(meminfo, floor, balloon, int(argv[4]))
        print(summary)
        return _report(errors, "GO: memory headroom for one more gateway")
    if mode == "sqlite-snapshot" and len(argv) == 2:
        sys.stdout.buffer.write(sqlite_snapshot(argv[1]))
        return 0
    if mode == "sqlite-report" and len(argv) == 2:
        report = sqlite_report(argv[1])
        print(json.dumps(report, sort_keys=True))
        return 0 if report["ok"] else 1
    print(f"usage error: {argv!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
