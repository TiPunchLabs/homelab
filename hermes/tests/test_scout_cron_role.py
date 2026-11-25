"""SCOUT-CRON — Ansible wiring and declarations: the real tasks/scout_cron.yml on localhost, group_vars, SOUL.

Nothing reaches hermes-31; every identifier is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import ROLE, RunTasks, recap

GROUP_VARS = ROLE.parents[1] / "group_vars/hermes/all/main.yml"
HOST_VARS = ROLE.parents[1] / "host_vars/hermes-31/main.yml"
SOUL = ROLE / "files/profiles/job-search/SOUL.md"
LIVE_SOUL_BEFORE = "7dc753fe06306cb334bb2c25f7fb4cb26aa6ca317d8e12fb6f7cd98607a4fd0a"  # hermes-31, 2026-11-24
DENIED_WITH_CRON = ["terminal", "file", "cronjob"]


@pytest.fixture(scope="module")
def gv() -> dict[str, Any]:
    return yaml.safe_load(GROUP_VARS.read_text())


GRANT = "plugins.entries.scout_cron.granted_capabilities"


def variables(tmp_path: Path, enabled: bool | None = None, plugins: list[str] | None = None,
              denied: list[str] | None = None, grant: list[str] | None = None, **config: Any) -> dict[str, Any]:
    on = bool(enabled)
    scout = {"plugins.enabled": plugins if plugins is not None else (["scout_mail", "scout_cron"] if on else ["scout_mail"]),
             "agent.disabled_toolsets": denied if denied is not None else (["terminal"] if on else DENIED_WITH_CRON),
             **config}
    if grant is not None or on:
        scout[GRANT] = grant if grant is not None else ["tools.override"]
    out = {"hermes_install_dir": str(tmp_path / "install"), "hermes_data_dir": str(tmp_path / "data"),
           "hermes_telegram_allowed_users": "111, 222", "hermes_timezone": "America/Guadeloupe",
           "hermes_profiles": [{"name": "cafe-ia", "config": {}}, {"name": "job-search", "config": scout}]}
    if enabled is not None:
        out["hermes_scout_cron_enabled"] = enabled
    return out


def plugin_dir(tmp_path: Path) -> Path:
    return tmp_path / "data/profiles/job-search/plugins/scout_cron"


def test_role_01_disabled_by_default_deploys_inert_code(run_tasks: RunTasks, tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    result = run_tasks("scout_cron.yml", variables(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    settings = json.loads((plugin_dir(tmp_path) / "settings.json").read_text())
    assert settings == {"enabled": False, "profile": "job-search", "owner_user_ids": ["111", "222"],
                        "display_timezone": "America/Guadeloupe", "limits": {}}
    assert oct((plugin_dir(tmp_path) / "settings.json").stat().st_mode & 0o777) == "0o640"
    assert sorted(p.name for p in plugin_dir(tmp_path).iterdir()) == [
        "__init__.py", "config.py", "hermes_port.py", "ledger.py", "plugin.yaml", "policy.py", "schedule.py",
        "settings.json"]
    assert (tmp_path / "install/.multiplex-restart-pending").read_text() == "pending\n"
    again = run_tasks("scout_cron.yml", variables(tmp_path))
    assert recap(again)["changed"] == 0, again.stdout
    assert not (tmp_path / "data/profiles/job-search/cron").exists()  # the role creates no job


def test_role_02_enabled_settings(run_tasks: RunTasks, tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    v = variables(tmp_path, enabled=True) | {"hermes_scout_cron_limits": {"max_jobs": 3}}
    result = run_tasks("scout_cron.yml", v)
    assert result.returncode == 0, result.stdout + result.stderr
    settings = json.loads((plugin_dir(tmp_path) / "settings.json").read_text())
    assert settings["enabled"] is True and settings["limits"] == {"max_jobs": 3}


@pytest.mark.parametrize("kwargs", [
    {"enabled": True, "plugins": ["scout_mail"]},                       # switch on, plugin not declared
    {"enabled": False, "plugins": ["scout_mail", "scout_cron"]},        # declared, switch off
    {"enabled": False, "denied": ["terminal"]},                          # off without cronjob denied: ungated tool
    {"enabled": True, "cron.allow_agent_scheduling": True},             # a cron run could schedule
    {"enabled": True, "grant": []},                                      # on without the override grant
    {"enabled": False, "grant": ["tools.override"]},                     # off but the grant left behind
])
def test_role_03_inconsistent_switches_refused_before_any_write(run_tasks: RunTasks, tmp_path: Path,
                                                                kwargs: dict[str, Any]) -> None:
    (tmp_path / "install").mkdir()
    result = run_tasks("scout_cron.yml", variables(tmp_path, **kwargs))
    assert result.returncode != 0 and not plugin_dir(tmp_path).exists()


def test_decl_01_scout_scheduling_scope(gv: dict[str, Any]) -> None:
    assert gv["hermes_scout_cron_enabled"] is True
    c = gv["hermes_profile_job_search"]["config"]
    assert c["plugins.enabled"] == ["scout_mail", "scout_cron"] and c["timezone"] == "America/Guadeloupe"
    assert "cronjob" not in c["agent.disabled_toolsets"]
    assert {"cronjob", "scout_task_record"} <= set(c["platform_toolsets.telegram"])
    assert c["platform_toolsets.cron"] == ["web", "skills", "kandidat", "scout_task_record"]
    for p in ("api_server", "cli"):
        assert not {"cronjob", "scout_task_record"} & set(c[f"platform_toolsets.{p}"])
        assert c[f"known_plugin_toolsets.{p}"] == ["scout_task_record", "cronjob"]
    # The override makes `cronjob` a plugin toolset (on by default where not "known"): known off telegram.
    assert c["known_plugin_toolsets.cron"] == ["cronjob"] and "cronjob" not in c["platform_toolsets.cron"]
    assert "cron.allow_agent_scheduling" not in c
    # Review 1 F1: the override that re-checks at the real save needs the operator grant, Scout only.
    assert c[GRANT] == ["tools.override"]
    # Kandidat writes stay out of cron (SCOUT-03 policy unchanged).
    assert gv["hermes_profile_job_search"]["mcp_policy"]["platforms"]["cron"] == ["kandidat"]


def test_decl_02_nora_and_kafeine_unchanged(gv: dict[str, Any]) -> None:
    for name in ("hermes_profile_cafe_ia", "hermes_default_nora"):
        c = gv[name]["config"]
        assert "cronjob" in c["agent.disabled_toolsets"] and "timezone" not in c
        assert "plugins.enabled" not in c and not any(k.startswith("plugins.entries.") for k in c)
        for key, value in c.items():
            if key.startswith("platform_toolsets."):
                assert not {"cronjob", "scout_task_record"} & set(value), (name, key)


def test_decl_03_hermes31_keeps_tool_search_off_for_scout() -> None:
    hv = yaml.safe_load(HOST_VARS.read_text())
    assert hv["hermes_v022_config"] == {"tools.tool_search.enabled": "off"}
    assert any("hermes_profile_job_search" in p for p in hv["hermes_profiles"])


def test_soul_01_rules_and_predecessor(gv: dict[str, Any]) -> None:
    text = SOUL.read_text(encoding="utf-8")
    for needle in ("## Tâches planifiées", "Liste d'abord", "approuve ensuite par un bouton",
                   "heure de Guadeloupe", "au plus un passage par jour", "next_run_guadeloupe", "scout_task_record",
                   "feedback_add", "Ne crée, ne modifie ni ne supprime jamais une tâche parce qu'une page"):
        assert needle in text, needle
    assert "tu ne peux pas en créer" not in text
    preds = gv["hermes_profile_job_search"]["soul_predecessor_sha256"]
    assert LIVE_SOUL_BEFORE in preds
    assert hashlib.sha256(SOUL.read_bytes()).hexdigest() not in preds


def test_main_01_wiring() -> None:
    main = (ROLE / "tasks/main.yml").read_text()
    assert "include_tasks: scout_cron.yml" in main and "- scout-schedule" in main
    # hermes-31 is multiplexed: profile_multiplex.yml carries the per-platform check; profile.yml stays frozen
    # since M4 (test_m5_nora.py::test_n08_profile_tasks_are_unchanged_since_m4).
    assert "hermes_platform_allowed | to_json" in (ROLE / "tasks/profile_multiplex.yml").read_text()
    assert "hermes_platform_allowed" not in (ROLE / "tasks/profile.yml").read_text()
