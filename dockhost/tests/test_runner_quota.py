"""Behaviour tests for the runner-quota controller (offline, fake GitLab API)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any, Self

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "dockhost/ansible/roles/gitlab_runner/files/runner_quota.py"
_spec = importlib.util.spec_from_file_location("runner_quota", SRC)
assert _spec and _spec.loader
rq = importlib.util.module_from_spec(_spec)
sys.modules["runner_quota"] = rq
_spec.loader.exec_module(rq)

PROJECT = 80082616
NAMESPACE = 125854366


class FakeApi:
    """In-memory GitLab: namespace, runners and one project variable."""

    def __init__(self, used: int = 0, plan: str = "free") -> None:
        self.namespace: Any = {
            "plan": plan,
            "ci_minutes_usage": {"monthly_minutes_used": used, "purchased_minutes_used": 0},
        }
        self.homelab: Any = [{"online": True, "paused": False}]
        self.saas: Any = [{"online": True, "paused": False}]
        self.variable: Any = {
            "value": "gitlab",
            "protected": False,
            "environment_scope": "*",
            "variable_type": "env_var",
        }
        self.fail: dict[str, rq.ApiError] = {}
        self.writes: list[str] = []
        self.ignore_write = False

    def request(self, method: str, path: str, params: Any = None, data: Any = None) -> Any:
        key = f"{method} {path}"
        for prefix, err in self.fail.items():
            if key.startswith(prefix):
                raise err
        if key == f"GET /namespaces/{NAMESPACE}":
            return self.namespace
        if key == f"GET /projects/{PROJECT}/runners":
            if params["type"] != "project_type":
                return self.saas
            if isinstance(self.homelab, rq.ApiError):
                raise self.homelab
            return self.homelab
        if key == f"GET /projects/{PROJECT}/variables/RUNNER_ROUTE":
            return self.variable
        if key == f"PUT /projects/{PROJECT}/variables/RUNNER_ROUTE":
            self.writes.append(data["value"])
            if not self.ignore_write:
                self.variable = dict(self.variable, value=data["value"])
            return self.variable
        raise AssertionError(f"unexpected call {key}")


def make_cfg(tmp_path: Path, **over: Any) -> Any:
    raw = {
        "gitlab_url": "https://gitlab.com",
        "namespace_id": NAMESPACE,
        "project_id": PROJECT,
        "expected_plan": "free",
        "monthly_limit_minutes": 400,
        "threshold_percent": 85,
        "variable_key": "RUNNER_ROUTE",
        "homelab_runner_tag": "homelab-dockhost",
        "saas_runner_tag": "saas-linux-small-amd64",
        "token_file": str(tmp_path / "token"),
        "state_file": str(tmp_path / "state.json"),
        "lock_file": str(tmp_path / "lock"),
    }
    raw.update(over)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    (tmp_path / "token").write_text("glpat-test-not-a-secret\n")
    return rq.load_config(str(path))


def check(
    api: FakeApi,
    cfg: Any,
    state: dict[str, Any] | None = None,
    month: str = "2026-11",
    dry_run: bool = False,
    simulate_used: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    return rq.run_check(
        api,
        cfg,
        state or {"mode": "auto", "latch": None},
        dry_run=dry_run,
        month=month,
        simulate_used=simulate_used,
    )


# --- quota thresholds -------------------------------------------------------


@pytest.mark.parametrize(
    ("used", "route"),
    [
        (0, "gitlab"),
        (200, "gitlab"),
        (336, "gitlab"),
        (340, "homelab"),
        (396, "homelab"),
        (400, "homelab"),
        (450, "homelab"),
    ],
)
def test_threshold(tmp_path: Path, used: int, route: str) -> None:
    api = FakeApi(used)
    state, report, code = check(api, make_cfg(tmp_path))
    assert api.variable["value"] == route
    assert code == 0
    assert (state["latch"] is not None) == (route == "homelab")
    assert report["percent"] == round(used / 4, 1)


def test_threshold_is_configurable(tmp_path: Path) -> None:
    api = FakeApi(200)
    check(api, make_cfg(tmp_path, threshold_percent=50))
    assert api.variable["value"] == "homelab"


@pytest.mark.parametrize(
    "over",
    [
        {"threshold_percent": 0},
        {"threshold_percent": 101},
        {"monthly_limit_minutes": 0},
        {"monthly_limit_minutes": -1},
        {"homelab_runner_tag": "saas-linux-small-amd64"},
        {"unknown": 1},
    ],
)
def test_invalid_config_rejected(tmp_path: Path, over: dict[str, Any]) -> None:
    with pytest.raises(rq.ConfigError):
        make_cfg(tmp_path, **over)


def test_unknown_plan_keeps_route(tmp_path: Path) -> None:
    api = FakeApi(390, plan="premium")
    state, report, code = check(api, make_cfg(tmp_path))
    assert api.writes == [] and code == 1
    assert report["decision"] == "keep" and "plan" in report["reason"]
    assert state["latch"] is None


@pytest.mark.parametrize(
    "namespace",
    [
        {"plan": "free"},
        {"plan": "free", "ci_minutes_usage": {}},
        {"plan": "free", "ci_minutes_usage": {"monthly_minutes_used": "12"}},
        {"plan": "free", "ci_minutes_usage": {"monthly_minutes_used": -3}},
        [],
    ],
)
def test_incomplete_usage_keeps_route(tmp_path: Path, namespace: Any) -> None:
    api = FakeApi()
    api.namespace = namespace
    api.variable["value"] = "homelab"
    _, report, code = check(api, make_cfg(tmp_path))
    assert api.writes == [] and code == 1 and report["decision"] == "keep"


@pytest.mark.parametrize("kind", ["network", "auth", "http"])
def test_api_errors_keep_route(tmp_path: Path, kind: str) -> None:
    api = FakeApi(390)
    api.fail[f"GET /namespaces/{NAMESPACE}"] = rq.ApiError(kind, "boom")
    _, report, code = check(api, make_cfg(tmp_path))
    assert api.writes == [] and code == 1 and report["decision"] == "keep"


def test_quota_limit_raised_mid_month_keeps_latch(tmp_path: Path) -> None:
    api = FakeApi(345)
    state, _, _ = check(api, make_cfg(tmp_path))
    state, report, _ = check(api, make_cfg(tmp_path, monthly_limit_minutes=1000), state)
    assert api.variable["value"] == "homelab" and "limit changed" in report["reason"]


# --- switching and monthly return -------------------------------------------


def test_gitlab_to_homelab_then_renewal(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(345)
    state, _, _ = check(api, cfg, month="2026-11")
    assert api.variable["value"] == "homelab" and state["latch"]["month"] == "2026-11"
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 3
    state, report, code = check(api, cfg, state, month="2026-12")
    assert api.variable["value"] == "gitlab" and state["latch"] is None and code == 0
    assert "renewed" in report["reason"]


def test_new_month_without_reset_stays_homelab(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(345)
    state, _, _ = check(api, cfg, month="2026-11")
    state, _report, _ = check(api, cfg, state, month="2026-12")
    assert api.variable["value"] == "homelab" and state["latch"] is not None


def test_stale_lower_value_same_month_stays_homelab(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(345)
    state, _, _ = check(api, cfg)
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 10
    state, _, _ = check(api, cfg, state)
    assert api.variable["value"] == "homelab" and state["latch"] is not None


def test_renewal_waits_for_saas_runner(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(345)
    state, _, _ = check(api, cfg, month="2026-11")
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 0
    api.saas = [{"online": False, "paused": False}]
    state, _, code = check(api, cfg, state, month="2026-12")
    assert api.variable["value"] == "homelab" and code == 1 and state["latch"] is not None


def test_no_write_when_route_already_correct(tmp_path: Path) -> None:
    api = FakeApi(10)
    _, report, code = check(api, make_cfg(tmp_path))
    assert api.writes == [] and report["applied"] == "unchanged" and code == 0


def test_manual_modes(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(10)
    check(api, cfg, {"mode": "homelab", "latch": None})
    assert api.variable["value"] == "homelab"
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 399
    check(api, cfg, {"mode": "gitlab", "latch": None})
    assert api.variable["value"] == "gitlab"


def test_manual_homelab_with_runner_offline_alerts(tmp_path: Path) -> None:
    api = FakeApi(10)
    api.homelab = [{"online": False, "paused": False}]
    _, _, code = check(api, make_cfg(tmp_path), {"mode": "homelab", "latch": None})
    assert api.variable["value"] == "homelab" and code == 1


@pytest.mark.parametrize(
    "homelab",
    [
        [{"online": False, "paused": False}],
        [{"online": True, "paused": True}],
        [],
        [{"online": True, "paused": False}, {"online": True, "paused": False}],
    ],
)
def test_no_switch_to_unusable_homelab_runner(tmp_path: Path, homelab: Any) -> None:
    api = FakeApi(390)
    api.homelab = homelab
    state, report, code = check(api, make_cfg(tmp_path))
    assert api.writes == [] and code == 1 and state["latch"] is None and report["decision"] == "keep"


def test_homelab_runner_lookup_error_blocks_switch(tmp_path: Path) -> None:
    api = FakeApi(390)
    api.homelab = rq.ApiError("network", "down")
    _, _, code = check(api, make_cfg(tmp_path))
    assert api.writes == [] and code == 1


def test_write_error_keeps_latch_and_next_run_retries(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(390)
    api.fail[f"PUT /projects/{PROJECT}/variables"] = rq.ApiError("http", "HTTP 500", 500)
    state, report, code = check(api, cfg)
    assert code == 1 and state["latch"] is not None
    assert any(e.startswith("write:") for e in report["errors"])
    api.fail.clear()
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 300
    _, _, code = check(api, cfg, state)
    assert code == 0 and api.variable["value"] == "homelab"


def test_write_not_persisted_is_detected(tmp_path: Path) -> None:
    api = FakeApi(390)
    api.ignore_write = True
    state, _, code = check(api, make_cfg(tmp_path))
    assert code == 1 and state["latch"] is not None


@pytest.mark.parametrize(
    "var",
    [
        {"value": "gitlab", "protected": True, "environment_scope": "*", "variable_type": "env_var"},
        {"value": "gitlab", "protected": False, "environment_scope": "prod", "variable_type": "env_var"},
    ],
)
def test_badly_scoped_variable_never_written(tmp_path: Path, var: Any) -> None:
    api = FakeApi(390)
    api.variable = var
    _, _, code = check(api, make_cfg(tmp_path))
    assert api.writes == [] and code == 1


def test_missing_variable_not_created(tmp_path: Path) -> None:
    api = FakeApi(390)
    api.fail[f"GET /projects/{PROJECT}/variables"] = rq.ApiError("not_found", "HTTP 404", 404)
    _, _, code = check(api, make_cfg(tmp_path))
    assert api.writes == [] and code == 1


def test_unknown_variable_value_is_repaired(tmp_path: Path) -> None:
    api = FakeApi(10)
    api.variable["value"] = "typo"
    _, _, code = check(api, make_cfg(tmp_path))
    assert api.variable["value"] == "gitlab" and code == 0


# --- dry-run, simulation, state, lock ----------------------------------------


def test_dry_run_and_simulation_never_write(tmp_path: Path) -> None:
    api = FakeApi(10)
    state, report, _ = check(api, make_cfg(tmp_path), dry_run=True, simulate_used=340)
    assert api.writes == [] and report["applied"] == "would set RUNNER_ROUTE=homelab"
    assert state["latch"] is None


def run_main(tmp_path: Path, api: FakeApi, monkeypatch: pytest.MonkeyPatch, *args: str) -> tuple[int, Any]:
    make_cfg(tmp_path)
    monkeypatch.setattr(rq, "GitLabApi", lambda *a, **k: api)
    monkeypatch.setattr(rq, "utc_now", lambda: rq.datetime(2026, 11, 20, tzinfo=rq.UTC))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    code = rq.main(["--config", str(tmp_path / "config.json"), *args])
    text = out.getvalue()
    return code, json.loads(text) if text.strip() else None


def test_state_survives_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(345)
    run_main(tmp_path, api, monkeypatch, "check")
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["latch"]["used"] == 345
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 5
    run_main(tmp_path, api, monkeypatch, "check")
    assert api.variable["value"] == "homelab"


def test_cli_set_mode_and_clear_latch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(345)
    run_main(tmp_path, api, monkeypatch, "check")
    code, _ = run_main(tmp_path, api, monkeypatch, "set-mode", "gitlab")
    assert code == 0 and api.variable["value"] == "gitlab"
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 100
    run_main(tmp_path, api, monkeypatch, "set-mode", "auto")
    assert api.variable["value"] == "homelab"
    run_main(tmp_path, api, monkeypatch, "set-mode", "auto", "--clear-latch")
    assert api.variable["value"] == "gitlab"
    assert json.loads((tmp_path / "state.json").read_text())["mode"] == "auto"


def test_cli_simulation_leaves_no_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(10)
    _code, report = run_main(
        tmp_path, api, monkeypatch, "check", "--simulate-used", "350", "--simulate-month", "2026-12"
    )
    assert api.writes == [] and report["dry_run"] is True and report["decision"] == "homelab"
    assert not (tmp_path / "state.json").exists()


def test_status_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(390)
    _code, out = run_main(tmp_path, api, monkeypatch, "status")
    assert api.writes == [] and out["live"]["decision"] == "homelab"
    assert not (tmp_path / "state.json").exists()


def test_concurrent_run_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(390)
    with rq.Lock(cfg.lock_file) as held:
        assert held
        code, out = run_main(tmp_path, api, monkeypatch, "check")
    assert code == 0 and "skipped" in out and api.writes == []


def test_missing_token_is_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_cfg(tmp_path)
    (tmp_path / "token").write_text("")
    assert rq.main(["--config", str(tmp_path / "config.json"), "status"]) == rq.EXIT_CONFIG


def test_corrupt_state_is_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "state.json").write_text("{not json")
    code, _ = run_main(tmp_path, FakeApi(), monkeypatch, "check")
    assert code == rq.EXIT_CONFIG


# --- HTTP client ---------------------------------------------------------------


class _Resp(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def test_client_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_urlopen(req: Any, timeout: float) -> Any:
        calls.append(req.get_header("Private-token"))
        if len(calls) < 2:
            raise urllib.error.URLError("temporary")
        return _Resp(b'{"ok": true}')

    monkeypatch.setattr(rq.urllib.request, "urlopen", fake_urlopen)
    api = rq.GitLabApi("https://gitlab.com", "tok", 1, sleep=lambda s: None)
    assert api.request("GET", "/x") == {"ok": True} and len(calls) == 2


@pytest.mark.parametrize(
    ("code", "kind", "attempts"),
    [
        (401, "auth", 1),
        (403, "auth", 1),
        (404, "not_found", 1),
        (400, "http", 1),
        (503, "http", 2),
        (429, "http", 2),
    ],
)
def test_client_http_errors(monkeypatch: pytest.MonkeyPatch, code: int, kind: str, attempts: int) -> None:
    calls = []

    def fake_urlopen(req: Any, timeout: float) -> Any:
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(rq.urllib.request, "urlopen", fake_urlopen)
    api = rq.GitLabApi("https://gitlab.com", "secret-token", 1, sleep=lambda s: None)
    with pytest.raises(rq.ApiError) as err:
        api.request("GET", "/x")
    assert err.value.kind == kind and len(calls) == attempts
    assert "secret-token" not in str(err.value)


@pytest.mark.parametrize("content", ["[1]", '{"mode": "fast"}'])
def test_malformed_state_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    (tmp_path / "state.json").write_text(content)
    code, _ = run_main(tmp_path, FakeApi(), monkeypatch, "check")
    assert code == rq.EXIT_CONFIG


# --- review round 1: month boundary and crash consistency ----------------------


def test_latch_on_day_one_with_stale_value_released_same_month(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(345)
    state, _, _ = rq.run_check(
        api, cfg, {"mode": "auto", "latch": None}, dry_run=False, month="2026-12", day=1
    )
    assert state["latch"]["early"] is True and api.variable["value"] == "homelab"
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 4
    state, _report, code = rq.run_check(api, cfg, state, dry_run=False, month="2026-12", day=1)
    assert api.variable["value"] == "gitlab" and state["latch"] is None and code == 0


def test_early_latch_ignores_small_drop(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(345)
    state, _, _ = rq.run_check(
        api, cfg, {"mode": "auto", "latch": None}, dry_run=False, month="2026-12", day=2
    )
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 339
    state, _, _ = rq.run_check(api, cfg, state, dry_run=False, month="2026-12", day=2)
    assert api.variable["value"] == "homelab" and state["latch"] is not None


def test_mid_month_latch_never_released_same_month(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(345)
    state, _, _ = rq.run_check(
        api, cfg, {"mode": "auto", "latch": None}, dry_run=False, month="2026-11", day=20
    )
    assert state["latch"]["early"] is False
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 0
    state, _, _ = rq.run_check(api, cfg, state, dry_run=False, month="2026-11", day=21)
    assert api.variable["value"] == "homelab"


class Crash(BaseException):
    """Simulates the process being killed."""


def test_crash_after_write_keeps_latch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(345)
    original = api.request

    def dying_request(method: str, path: str, params: Any = None, data: Any = None) -> Any:
        result = original(method, path, params, data)
        if method == "PUT":
            raise Crash
        return result

    api.request = dying_request  # type: ignore[method-assign]
    with pytest.raises(Crash):
        run_main(tmp_path, api, monkeypatch, "check")
    assert api.variable["value"] == "homelab"
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["latch"]["used"] == 345
    api.request = original  # type: ignore[method-assign]
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 339
    run_main(tmp_path, api, monkeypatch, "check")
    assert api.variable["value"] == "homelab"


# --- review round 2: limit change and failed return ------------------------------


def test_limit_change_never_fakes_renewal(tmp_path: Path) -> None:
    api = FakeApi(345)
    cfg = make_cfg(tmp_path)
    state, _, _ = rq.run_check(
        api, cfg, {"mode": "auto", "latch": None}, dry_run=False, month="2026-12", day=1
    )
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 339
    bigger = make_cfg(tmp_path, monthly_limit_minutes=1000)
    state, _report, code = rq.run_check(api, bigger, state, dry_run=False, month="2026-12", day=2)
    assert api.variable["value"] == "homelab" and state["latch"] is not None and code == 1
    state, _, _ = rq.run_check(api, bigger, state, dry_run=False, month="2027-01", day=10)
    assert api.variable["value"] == "homelab", "a new month does not override a changed limit"


def latched_state(api: FakeApi, cfg: Any) -> dict[str, Any]:
    state, _, _ = rq.run_check(
        api, cfg, {"mode": "auto", "latch": None}, dry_run=False, month="2026-11", day=20
    )
    assert state["latch"] is not None
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 2
    return state


def test_failed_return_write_keeps_latch_and_rechecks_saas(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    api = FakeApi(345)
    state = latched_state(api, cfg)
    api.fail[f"PUT /projects/{PROJECT}/variables"] = rq.ApiError("http", "HTTP 500", 500)
    state, _, code = rq.run_check(api, cfg, state, dry_run=False, month="2026-12", day=1)
    assert code == 1 and state["latch"] is not None and api.variable["value"] == "homelab"
    api.fail.clear()
    api.saas = [{"online": False, "paused": False}]
    state, _, code = rq.run_check(api, cfg, state, dry_run=False, month="2026-12", day=1)
    assert api.variable["value"] == "homelab" and state["latch"] is not None and code == 1
    api.saas = [{"online": True, "paused": False}]
    state, _, code = rq.run_check(api, cfg, state, dry_run=False, month="2026-12", day=1)
    assert api.variable["value"] == "gitlab" and state["latch"] is None and code == 0


def test_crash_during_return_keeps_latch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(345)
    run_main(tmp_path, api, monkeypatch, "check")
    api.namespace["ci_minutes_usage"]["monthly_minutes_used"] = 2
    monkeypatch.setattr(rq, "utc_now", lambda: rq.datetime(2026, 12, 3, tzinfo=rq.UTC))
    original = api.request

    def dying_request(method: str, path: str, params: Any = None, data: Any = None) -> Any:
        if method == "PUT":
            raise Crash
        return original(method, path, params, data)

    api.request = dying_request  # type: ignore[method-assign]
    make_cfg(tmp_path)
    monkeypatch.setattr(rq, "GitLabApi", lambda *a, **k: api)
    with pytest.raises(Crash):
        rq.main(["--config", str(tmp_path / "config.json"), "check"])
    assert json.loads((tmp_path / "state.json").read_text())["latch"] is not None
