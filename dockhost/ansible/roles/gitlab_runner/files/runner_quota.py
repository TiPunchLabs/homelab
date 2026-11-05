#!/usr/bin/env python3
"""Route GitLab CI jobs to GitLab.com or the homelab runner from the compute quota.

The controller writes a single project CI/CD variable (RUNNER_ROUTE = gitlab |
homelab). .gitlab-ci.yml maps it to the runner tag of every job when a pipeline
is created. Standard library only: it runs from a systemd timer on dockhost.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MODES = ("auto", "gitlab", "homelab")
ROUTES = ("gitlab", "homelab")
EXIT_OK = 0
EXIT_ALERT = 1
EXIT_CONFIG = 2
# A latch taken on these first days of a month may stem from a previous-month
# value that GitLab has not reset yet (the volume here is far below 85 % in 48 h).
EARLY_DAYS = 2


class ConfigError(Exception):
    """Invalid or missing controller configuration."""


class ApiError(Exception):
    """GitLab API call that failed or returned unusable data."""

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass(frozen=True)
class Config:
    """Validated controller settings (no secret)."""

    gitlab_url: str
    namespace_id: int
    project_id: int
    expected_plan: str
    monthly_limit_minutes: int
    threshold_percent: float
    variable_key: str
    homelab_runner_tag: str
    saas_runner_tag: str
    token_file: str
    state_file: str
    lock_file: str
    timeout_seconds: float = 15.0


def load_config(path: str) -> Config:
    """Read and validate the JSON configuration file."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        cfg = Config(**raw)
    except TypeError as exc:
        raise ConfigError(f"invalid config keys: {exc}") from exc
    for name in ("namespace_id", "project_id", "monthly_limit_minutes"):
        value = getattr(cfg, name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigError(f"{name} must be a positive integer")
    if not isinstance(cfg.threshold_percent, (int, float)) or not 0 < cfg.threshold_percent <= 100:
        raise ConfigError("threshold_percent must be in ]0, 100]")
    for name in ("gitlab_url", "expected_plan", "variable_key", "homelab_runner_tag", "saas_runner_tag"):
        if not isinstance(getattr(cfg, name), str) or not getattr(cfg, name):
            raise ConfigError(f"{name} must be a non-empty string")
    if cfg.homelab_runner_tag == cfg.saas_runner_tag:
        raise ConfigError("homelab_runner_tag and saas_runner_tag must differ")
    return cfg


def read_token(path: str) -> str:
    """Return the API token from its file; the value is never logged."""
    try:
        token = Path(path).read_text().strip()
    except OSError as exc:
        raise ConfigError(f"cannot read token file {path}: {exc.strerror}") from exc
    if not token:
        raise ConfigError(f"token file {path} is empty")
    return token


class GitLabApi:
    """Minimal GitLab REST client with bounded retries."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = 2,
    ) -> None:
        self._base = base_url.rstrip("/") + "/api/v4"
        self._token = token
        self._timeout = timeout
        self._sleep = sleep
        self._attempts = attempts

    def request(
        self, method: str, path: str, params: dict[str, str] | None = None, data: dict[str, str] | None = None
    ) -> Any:
        """Call the API and return decoded JSON; retry network, 429 and 5xx errors."""
        url = self._base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        last: ApiError | None = None
        for attempt in range(self._attempts):
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("PRIVATE-TOKEN", self._token)
            req.add_header("User-Agent", "homelab-runner-quota")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    payload = resp.read()
                try:
                    return json.loads(payload) if payload else None
                except ValueError as exc:
                    raise ApiError("invalid", f"{method} {path}: response is not JSON") from exc
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise ApiError("auth", f"{method} {path}: HTTP {exc.code}", exc.code) from None
                if exc.code == 404:
                    raise ApiError("not_found", f"{method} {path}: HTTP 404", 404) from None
                last = ApiError("http", f"{method} {path}: HTTP {exc.code}", exc.code)
                if exc.code != 429 and exc.code < 500:
                    raise last from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                last = ApiError("network", f"{method} {path}: {reason}")
            if attempt + 1 < self._attempts:
                self._sleep(2 * (attempt + 1))
        assert last is not None
        raise last


@dataclass(frozen=True)
class Usage:
    """Compute minutes consumed in the current GitLab.com period."""

    monthly_used: int
    purchased_used: int
    plan: str


@dataclass
class Observation:
    """Everything read from GitLab during one run. None means unknown."""

    usage: Usage | None = None
    usage_error: str | None = None
    homelab_online: bool | None = None
    saas_online: bool | None = None
    variable_value: str | None = None
    errors: list[str] = field(default_factory=list)


def read_usage(api: GitLabApi, cfg: Config) -> Usage:
    """Read the namespace usage and refuse incomplete or unexpected data."""
    ns = api.request("GET", f"/namespaces/{cfg.namespace_id}")
    if not isinstance(ns, dict):
        raise ApiError("invalid", "namespace response is not an object")
    plan = ns.get("plan")
    usage = ns.get("ci_minutes_usage")
    if not isinstance(plan, str) or not isinstance(usage, dict):
        raise ApiError("invalid", "namespace response lacks plan or ci_minutes_usage (token not Owner?)")
    if plan != cfg.expected_plan:
        raise ApiError(
            "invalid",
            f"namespace plan is {plan!r}, expected {cfg.expected_plan!r}: "
            "monthly limit unknown, update the configuration",
        )
    monthly = usage.get("monthly_minutes_used")
    purchased = usage.get("purchased_minutes_used", 0)
    for name, value in (("monthly_minutes_used", monthly), ("purchased_minutes_used", purchased)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ApiError("invalid", f"ci_minutes_usage.{name} is missing or invalid")
    assert isinstance(monthly, int) and isinstance(purchased, int)
    return Usage(monthly_used=monthly, purchased_used=purchased, plan=plan)


def homelab_runner_online(api: GitLabApi, cfg: Config) -> bool:
    """True when exactly one project runner carries the homelab tag and it is online and active."""
    runners = api.request(
        "GET",
        f"/projects/{cfg.project_id}/runners",
        {"type": "project_type", "tag_list": cfg.homelab_runner_tag, "per_page": "100"},
    )
    if not isinstance(runners, list):
        raise ApiError("invalid", "project runner list response is not a list")
    if len(runners) != 1:
        raise ApiError(
            "invalid", f"expected one project runner tagged {cfg.homelab_runner_tag}, found {len(runners)}"
        )
    runner = runners[0]
    return isinstance(runner, dict) and runner.get("online") is True and runner.get("paused") is False


def saas_runner_online(api: GitLabApi, cfg: Config) -> bool:
    """True when at least one GitLab.com instance runner with the SaaS tag is online."""
    runners = api.request(
        "GET",
        f"/projects/{cfg.project_id}/runners",
        {"type": "instance_type", "tag_list": cfg.saas_runner_tag, "per_page": "100"},
    )
    if not isinstance(runners, list):
        raise ApiError("invalid", "runner list response is not a list")
    return any(isinstance(r, dict) and r.get("online") is True and r.get("paused") is False for r in runners)


def read_variable(api: GitLabApi, cfg: Config) -> str:
    """Return the route variable, checking it is visible to every pipeline."""
    var = api.request(
        "GET", f"/projects/{cfg.project_id}/variables/{cfg.variable_key}", {"filter[environment_scope]": "*"}
    )
    if not isinstance(var, dict) or not isinstance(var.get("value"), str):
        raise ApiError("invalid", f"variable {cfg.variable_key} response is invalid")
    if (
        var.get("protected") is not False
        or var.get("environment_scope") != "*"
        or var.get("variable_type") != "env_var"
    ):
        raise ApiError("invalid", f"variable {cfg.variable_key} must be unprotected, env_var, scope '*'")
    value: str = var["value"]
    return value


def write_variable(api: GitLabApi, cfg: Config, value: str) -> None:
    """Update the route variable, then read it back."""
    api.request(
        "PUT",
        f"/projects/{cfg.project_id}/variables/{cfg.variable_key}",
        {"filter[environment_scope]": "*"},
        {"value": value},
    )
    after = read_variable(api, cfg)
    if after != value:
        raise ApiError("invalid", f"variable {cfg.variable_key} reads {after!r} after writing {value!r}")


def observe(api: GitLabApi, cfg: Config) -> Observation:
    """Collect all inputs; each failure is recorded instead of raised."""
    obs = Observation()
    try:
        obs.usage = read_usage(api, cfg)
    except ApiError as exc:
        obs.usage_error = str(exc)
        obs.errors.append(f"usage: {exc}")
    for attr, probe in (("homelab_online", homelab_runner_online), ("saas_online", saas_runner_online)):
        try:
            setattr(obs, attr, probe(api, cfg))
        except ApiError as exc:
            obs.errors.append(f"{attr}: {exc}")
    try:
        obs.variable_value = read_variable(api, cfg)
    except ApiError as exc:
        obs.errors.append(f"variable: {exc}")
    return obs


@dataclass(frozen=True)
class Decision:
    """Target route (None = keep current) and the latch to persist."""

    route: str | None
    latch: dict[str, Any] | None
    reason: str
    alert: bool = False


def quota_renewed(latch: dict[str, Any], used: int, pct: float, cfg: Config, month: str) -> bool:
    """True when the reported usage proves a new quota period, not a date change alone.

    Always required: usage below the latched value and below the threshold, with
    the limit unchanged since the latch (checked by decide()).
    Then either the month changed since the latch, or the latch was taken in the
    first EARLY_DAYS of its month (possibly on a stale previous-month value) and
    usage dropped below half the threshold, as a real reset does.
    """
    if not (used < int(latch.get("used", 0)) and pct < cfg.threshold_percent):
        return False
    if month != latch.get("month"):
        return True
    return bool(latch.get("early")) and pct < cfg.threshold_percent / 2


def decide(
    mode: str, latch: dict[str, Any] | None, obs: Observation, cfg: Config, month: str, day: int = 15
) -> Decision:
    """Pure routing policy.

    In AUTO, reaching the threshold latches HOMELAB. The latch is released only
    once quota_renewed() holds and a GitLab.com runner is online.
    """
    if mode == "gitlab":
        return Decision("gitlab", latch, "manual mode GITLAB")
    if mode == "homelab":
        return Decision("homelab", latch, "manual mode HOMELAB", alert=obs.homelab_online is not True)
    if obs.usage is None:
        return Decision(None, latch, f"usage unavailable, route kept: {obs.usage_error}", alert=True)

    used = obs.usage.monthly_used
    pct = used * 100.0 / cfg.monthly_limit_minutes
    if latch is not None:
        if latch.get("limit") != cfg.monthly_limit_minutes:
            return Decision(
                "homelab",
                latch,
                f"monthly limit changed since the latch ({latch.get('limit')} -> {cfg.monthly_limit_minutes}), "
                "HOMELAB kept: check, then run set-mode auto --clear-latch",
                alert=True,
            )
        renewed = quota_renewed(latch, used, pct, cfg, month)
        if renewed and obs.saas_online is True:
            return Decision("gitlab", None, f"quota renewed ({pct:.1f} % in {month}), back to GitLab.com")
        if renewed:
            return Decision(
                "homelab", latch, "quota renewed but no GitLab.com runner online, HOMELAB kept", alert=True
            )
        return Decision(
            "homelab",
            latch,
            f"latched since {latch.get('month')} at {latch.get('used')} min ({pct:.1f} % now)",
            alert=obs.homelab_online is not True,
        )
    if pct >= cfg.threshold_percent:
        if obs.homelab_online is True:
            new_latch = {
                "month": month,
                "used": used,
                "limit": cfg.monthly_limit_minutes,
                "early": day <= EARLY_DAYS,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            return Decision(
                "homelab", new_latch, f"threshold reached ({pct:.1f} % >= {cfg.threshold_percent} %)"
            )
        return Decision(
            None,
            None,
            f"threshold reached ({pct:.1f} %) but homelab runner not online, no switch",
            alert=True,
        )
    return Decision("gitlab", None, f"below threshold ({pct:.1f} % < {cfg.threshold_percent} %)")


def load_state(path: str) -> dict[str, Any]:
    """Read the persisted state; a missing file means a fresh AUTO controller."""
    try:
        state = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {"mode": "auto", "latch": None}
    except (OSError, ValueError) as exc:
        raise ConfigError(f"state file {path} is unreadable: {exc}") from exc
    if not isinstance(state, dict) or state.get("mode") not in MODES:
        raise ConfigError(f"state file {path} has an invalid mode")
    result: dict[str, Any] = state
    return result


def save_state(path: str, state: dict[str, Any]) -> None:
    """Write the state atomically."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class Lock:
    """Non-blocking exclusive lock so two runs never interleave."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._fh: Any = None

    def __enter__(self) -> bool:
        self._fh = open(self._path, "a")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def __exit__(self, *exc: object) -> None:
        self._fh.close()


def utc_now() -> datetime:
    """Current time in UTC (GitLab.com resets quotas on the 1st, UTC)."""
    return datetime.now(UTC)


def run_check(
    api: GitLabApi,
    cfg: Config,
    state: dict[str, Any],
    *,
    dry_run: bool,
    month: str,
    day: int = 15,
    simulate_used: int | None = None,
    persist: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """One controller cycle: observe, decide, apply. Returns (new_state, report, exit_code).

    The new latch is persisted before the variable is written, so a crash after
    the write can never forget a HOMELAB latch; a failed write is retried by the
    next run from the persisted latch.
    """
    obs = observe(api, cfg)
    if simulate_used is not None:
        obs.usage = Usage(simulate_used, 0, cfg.expected_plan)
        obs.usage_error = None
    decision = decide(state["mode"], state.get("latch"), obs, cfg, month, day)
    applied = "none"
    errors = list(obs.errors)
    new_state = dict(state)
    # A latch being set is saved before the write; a latch being released is
    # dropped only once the return to GitLab.com is confirmed (below).
    if not dry_run and decision.latch is not None:
        new_state["latch"] = decision.latch
        if persist is not None:
            persist(new_state)
    if decision.route is not None:
        if obs.variable_value is None:
            errors.append("route variable unreadable, nothing written")
        elif obs.variable_value == decision.route:
            applied = "unchanged"
        elif dry_run:
            applied = f"would set {cfg.variable_key}={decision.route}"
        else:
            try:
                write_variable(api, cfg, decision.route)
                applied = f"set {cfg.variable_key}={decision.route}"
            except ApiError as exc:
                errors.append(f"write: {exc}")
    if obs.variable_value is not None and obs.variable_value not in ROUTES and not applied.startswith("set"):
        errors.append(f"{cfg.variable_key} holds an unknown value; pipelines fall back to GitLab.com")

    usage = obs.usage
    report = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "simulated_used": simulate_used,
        "mode": state["mode"],
        "month": month,
        "used_minutes": usage.monthly_used if usage else None,
        "purchased_used_minutes": usage.purchased_used if usage else None,
        "limit_minutes": cfg.monthly_limit_minutes,
        "percent": round(usage.monthly_used * 100.0 / cfg.monthly_limit_minutes, 1) if usage else None,
        "threshold_percent": cfg.threshold_percent,
        "homelab_runner_online": obs.homelab_online,
        "saas_runner_online": obs.saas_online,
        "route_before": obs.variable_value,
        "decision": decision.route or "keep",
        "reason": decision.reason,
        "applied": applied,
        "latch": decision.latch,
        "errors": errors,
    }
    if not dry_run and decision.latch is None and applied in ("unchanged", f"set {cfg.variable_key}=gitlab"):
        new_state["latch"] = None
    new_state["last_check"] = report
    alert = decision.alert or bool(errors)
    return new_state, report, EXIT_ALERT if alert else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: status, check, set-mode."""
    parser = argparse.ArgumentParser(prog="runner-quota", description=__doc__)
    parser.add_argument("--config", default="/etc/runner-quota/config.json")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show quota, mode, route and last decision (read-only)")
    chk = sub.add_parser("check", help="evaluate and apply the route")
    chk.add_argument("--dry-run", action="store_true", help="never write to GitLab nor to the state")
    chk.add_argument(
        "--simulate-used", type=int, help="pretend this many minutes are used (implies --dry-run)"
    )
    chk.add_argument("--simulate-month", help="pretend the current month is YYYY-MM (implies --dry-run)")
    sm = sub.add_parser("set-mode", help="choose AUTO, or force GITLAB / HOMELAB, then apply")
    sm.add_argument("mode", choices=MODES)
    sm.add_argument("--clear-latch", action="store_true", help="AUTO only: forget this month's HOMELAB latch")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
        api = GitLabApi(cfg.gitlab_url, read_token(cfg.token_file), cfg.timeout_seconds)
    except ConfigError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return EXIT_CONFIG

    with Lock(cfg.lock_file) as locked:
        if not locked:
            print(json.dumps({"skipped": "another runner-quota run holds the lock"}))
            return EXIT_OK
        try:
            state = load_state(cfg.state_file)
        except ConfigError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return EXIT_CONFIG

        if args.cmd == "status":
            _, report, code = run_check(
                api, cfg, state, dry_run=True, month=utc_now().strftime("%Y-%m"), day=utc_now().day
            )
            print(
                json.dumps(
                    {"configured_mode": state["mode"], "live": report, "last_check": state.get("last_check")},
                    indent=2,
                )
            )
            return code

        if args.cmd == "set-mode":
            if args.clear_latch and args.mode != "auto":
                print(json.dumps({"error": "--clear-latch is only valid with auto"}), file=sys.stderr)
                return EXIT_CONFIG
            state["mode"] = args.mode
            if args.clear_latch:
                state["latch"] = None
            save_state(cfg.state_file, state)

        simulate = args.cmd == "check" and (args.simulate_used is not None or args.simulate_month)
        dry_run = bool(getattr(args, "dry_run", False) or simulate)
        now = utc_now()
        month, day = now.strftime("%Y-%m"), now.day
        if args.cmd == "check" and args.simulate_month:
            month, day = args.simulate_month, 15
        new_state, report, code = run_check(
            api,
            cfg,
            state,
            dry_run=dry_run,
            month=month,
            day=day,
            simulate_used=getattr(args, "simulate_used", None),
            persist=lambda st: save_state(cfg.state_file, st),
        )
        if not dry_run:
            save_state(cfg.state_file, new_state)
        print(json.dumps(report, sort_keys=True))
        return code


if __name__ == "__main__":
    sys.exit(main())
