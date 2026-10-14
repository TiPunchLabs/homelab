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
    schedule-window <minutes>

`schedule-window` is read-only: it reads the profile's jobs.json and prints
names, schedules and timestamps only, never a prompt.
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
) -> tuple[bool, str]:
    """Decide whether Telegram is connected for the CURRENT gateway process.

    gateway_state.json is not a heartbeat: it is only rewritten on transitions
    and survives restarts. A `connected` entry is trusted only if it was
    written by the process s6 supervises right now, identified by (pid,
    start_time). Otherwise a bot that died at restart would still read
    `connected` from the previous life.
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
    entry = platforms.get("telegram") if isinstance(platforms, Mapping) else None
    if not isinstance(entry, Mapping):
        return False, "level 3: no telegram entry (adapter not started: token missing?)"
    if (entry.get("writer_pid"), entry.get("writer_start_time")) != (state.get("pid"), state.get("start_time")):
        return False, "level 3: telegram entry left over from a previous gateway process"
    if entry.get("state") != "connected":
        return False, f"level 3: telegram state is {entry.get('state')!r}"
    return True, f"telegram connected (gateway pid {s6_pid})"


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
    if mode == "telegram" and len(argv) == 3:
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
        ok, message = telegram_verdict(state, svstat.stdout or svstat.stderr, runtime_status_pid_is_live)
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
    print(f"usage error: {argv!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
