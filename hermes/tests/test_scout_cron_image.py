"""SCOUT-CRON — the scout_cron plugin inside the real Hermes v0.22.5 image (``--network none``; skipped when absent).

The declared configs of Nora (default), Kaféine (cafe-ia) and Scout (job-search) are applied with
``hermes config set`` (vault values replaced by synthetic ones; Kandidat MCP servers left out, covered by
test_scout03_kandidat.py), both Scout plugins installed, then ``fixtures/scout_cron/image_lab.py`` drives:
- Telegram-like agent turns through a scripted local model: Hermes' executor, the tool_search bridge, the
  plugin hooks and the real approval gate, answered as the Telegram button would;
- real cron executions of Scout jobs (the ``hermes cron run`` path), two runs per job for the record;
- a second process for the restart case; the deploy checks of the role (hermes_checks.py).
Faked: the model and the Telegram transport behind ``post_message`` (they record what would be sent).
AC mapping: AC1 g1_*, AC2 g2_*, AC3 g3_*, AC4 g4_*, AC5 g5_*, AC7 ac7_*.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROLE = Path(__file__).resolve().parents[1] / "ansible/roles/hermes_agent"
GROUP_VARS = Path(__file__).resolve().parents[1] / "ansible/group_vars/hermes/all/main.yml"
HOST_VARS = Path(__file__).resolve().parents[1] / "ansible/host_vars/hermes-31/main.yml"
PLUGINS = ROLE / "files/plugins"
FIXTURES = Path(__file__).parent / "fixtures/scout_cron"
CHECKS = ROLE / "files/hermes_checks.py"
IMAGE = "{}:{}".format(yaml.safe_load((ROLE / "defaults/main.yml").read_text())["hermes_image"], "v0.22.5")
OWNER = "111"
sys.path.insert(0, str(ROLE / "filter_plugins"))
import hermes_profiles as hp

SYNTHETIC_HINT = "Contexte synthétique de test : ingénieur DevOps, aucune donnée réelle."


def declared(profile: dict[str, Any]) -> dict[str, str]:
    """Config keys as `hermes config set` arguments; vault values synthetic, MCP servers left out."""
    out = {}
    for key, value in (profile.get("config") or {}).items():
        if key.startswith("mcp_servers."):
            continue
        if key == "agent.environment_hint":
            value = SYNTHETIC_HINT
        if isinstance(value, str) and "{{" in value:
            continue
        out[key] = hp.hermes_config_arg(value)
    return out


def setup_script(group_vars: dict[str, Any], tool_search: str) -> str:
    """Container script. ``tool_search``: "off" as hermes-31 (host_vars hermes_v022_config, every profile),
    or "auto" (Hermes' default: deferred tools behind the tool_call bridge)."""
    v022 = yaml.safe_load(HOST_VARS.read_text())["hermes_v022_config"] | {"tools.tool_search.enabled": tool_search}
    lines = ["set -e", "cd /opt/hermes",
             "hermes profile create job-search --no-alias >/dev/null",
             "hermes profile create cafe-ia --no-alias >/dev/null"]
    for flag, profile in (("", group_vars["hermes_default_nora"]), ("-p cafe-ia ", group_vars["hermes_profile_cafe_ia"]),
                          ("-p job-search ", group_vars["hermes_profile_job_search"])):
        for key, value in (declared(profile) | {k: hp.hermes_config_arg(v) for k, v in v022.items()}).items():
            lines.append(f"hermes {flag}config set {shlex.quote(key)} {shlex.quote(value)} >/dev/null")
    j = "/tmp/data/profiles/job-search"
    cron_settings = {"enabled": True, "profile": "job-search", "owner_user_ids": [OWNER],
                     "display_timezone": "America/Guadeloupe", "limits": {"run_tool_calls": 8, "run_web_calls": 3}}
    mail_settings = {"enabled": True, "profile": "job-search", "inbox_id": "lab@agentmail.to", "owner_user_ids": [OWNER]}
    lines += [
        f"mkdir -p {j}/plugins", f"cp -r /plugins/scout_mail {j}/plugins/", f"cp -r /plugins/scout_cron {j}/plugins/",
        f"echo {shlex.quote(json.dumps(cron_settings))} > {j}/plugins/scout_cron/settings.json",
        f"echo {shlex.quote(json.dumps(mail_settings))} > {j}/plugins/scout_mail/settings.json",
        # Lab only: the scripted model, and a short approval timeout for the timeout case.
        "hermes -p job-search config set model.default fake-model >/dev/null",
        "hermes -p job-search config set model.provider custom >/dev/null",
        "hermes -p job-search config set model.base_url http://127.0.0.1:18080/v1 >/dev/null",
        "hermes -p job-search config set approvals.timeout 4 >/dev/null",
        f"echo OPENAI_API_KEY=sk-lab-not-a-key >> {j}/.env",
    ]
    check = "python3 -c \"$(cat /checks/hermes_checks.py)\""
    allowed = ",".join(t for t in group_vars["hermes_profile_job_search"]["config"]["platform_toolsets.telegram"]
                       if t != "no_mcp")
    denied = ",".join(group_vars["hermes_profile_job_search"]["config"]["agent.disabled_toolsets"])

    def run_check(name: str, cmd: str) -> list[str]:
        return [f"set +e; out=$({cmd} 2>&1); rc=$?; set -e",
                f"printf 'CHECK %s %s %s\\n' {name} \"$rc\" \"$(echo \"$out\" | tr '\\n' '|')\""]
    lines += run_check("scout_cron_pre", f"{check} scout-schedule true job-search,cafe-ia job-search /tmp/data")
    lines += ["python3 /lab/image_lab.py main", "python3 /lab/image_lab.py restart"]
    lines += run_check("scout_cron_post", f"{check} scout-schedule true job-search,cafe-ia job-search /tmp/data")
    lines += run_check("scout_cron_wrong_switch", f"{check} scout-schedule false job-search,cafe-ia job-search /tmp/data")
    lines += run_check("scout_mail", f"{check} scout-mail true job-search,cafe-ia job-search /tmp/data")
    per_platform = json.dumps({p: group_vars["hermes_profile_job_search"]["config"][f"platform_toolsets.{p}"]
                               for p in ("telegram", "cron", "api_server", "cli")})
    lines += run_check("toolsets_scout",
                       f"HERMES_HOME={j} {check} toolsets {allowed} {denied} false {shlex.quote(per_platform)}")
    cafe = group_vars["hermes_profile_cafe_ia"]["config"]
    cafe_platform = json.dumps({p: cafe[f"platform_toolsets.{p}"] for p in ("telegram", "cron", "api_server", "cli")})
    cafe_allowed = ",".join(t for t in cafe["platform_toolsets.telegram"] if t != "no_mcp")
    lines += run_check("toolsets_cafe", f"HERMES_HOME=/tmp/data/profiles/cafe-ia {check} toolsets {cafe_allowed} "
                       f"{','.join(cafe['agent.disabled_toolsets'])} true {shlex.quote(cafe_platform)}")
    nora = group_vars["hermes_default_nora"]["config"]
    nora_allowed = ",".join(t for t in nora["platform_toolsets.telegram"] if t != "no_mcp")
    lines += run_check("toolsets_nora", f"HERMES_HOME=/tmp/data {check} toolsets {nora_allowed} "
                       f"{','.join(nora['agent.disabled_toolsets'])} true")
    return "\n".join(lines)


@pytest.fixture(scope="module", params=["off", "auto"], ids=["tool_search_off", "tool_search_auto"])
def lab(request: pytest.FixtureRequest) -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True, check=False).returncode:
        pytest.skip(f"{IMAGE} not available locally")
    group_vars = yaml.safe_load(GROUP_VARS.read_text())
    result = subprocess.run(
        [docker, "run", "--rm", "--network", "none", "-u", "10000", "-w", "/opt/hermes", "-e", "HERMES_HOME=/tmp/data",
         "-v", f"{PLUGINS}:/plugins:ro", "-v", f"{FIXTURES}:/lab:ro", "-v", f"{CHECKS}:/checks/hermes_checks.py:ro",
         "--entrypoint", "sh", IMAGE, "-c", setup_script(group_vars, request.param)],
        capture_output=True, text=True, timeout=1500, check=False,
    )
    labs = [json.loads(x[4:]) for x in result.stdout.splitlines() if x.startswith("LAB ")]
    checks = {}
    for line in result.stdout.splitlines():
        if line.startswith("CHECK "):
            _, name, rc, out = line.split(" ", 3)
            checks[name] = {"rc": int(rc), "out": out}
    assert len(labs) == 2, result.stdout[-3000:] + result.stderr[-3000:]
    return {"main": labs[0], "restart": labs[1], "checks": checks, "tool_search": request.param}


def turn(lab: dict[str, Any], name: str) -> dict[str, Any]:
    return lab["main"]["turns"][name]


def first_result(t: dict[str, Any]) -> str:
    return (t["tool_results"] or [""])[0] or ""


def refused(t: dict[str, Any]) -> bool:
    return "Refusé par la politique" in first_result(t)


# ---- AC1 / G1 ---------------------------------------------------------------------------------------------

def test_g1_01_plugin_and_command_for_scout_only(lab: dict[str, Any]) -> None:
    d = lab["main"]["discovery"]
    assert d["job-search"]["plugins"] == ["scout_cron", "scout_mail"]
    assert "taches-scout" in d["job-search"]["commands"] and "courriels" in d["job-search"]["commands"]
    for other in ("default", "cafe-ia"):
        assert d[other] == {"plugins": [], "hooks": [], "commands": []}


def test_g1_02_scheduling_toolsets_per_profile_and_platform(lab: dict[str, Any]) -> None:
    e = lab["main"]["exposure"]
    assert e["job-search"] == {"telegram": ["cronjob", "scout_task_record"], "cron": ["scout_task_record"],
                               "api_server": [], "cli": []}
    for other in ("default", "cafe-ia"):
        assert e[other] == {"telegram": [], "cron": [], "api_server": [], "cli": []}


def test_g1_03_other_platforms_and_profiles_cannot_schedule(lab: dict[str, Any]) -> None:
    for name in ("api_server", "cli", "nora", "kafeine"):
        t = turn(lab, name)
        assert "cronjob_manage" not in t["valid_tools"]
        assert t["order"] == [], name  # nothing posted, no approval card
        assert "cronjob_manage" in first_result(t) or "Planification" in first_result(t) or \
            "not available" in first_result(t), (name, first_result(t))
    assert lab["main"]["final_jobs"] and all(j["name"] != "x" for j in lab["main"]["final_jobs"])


def test_g1_04_stranger_and_group_refused(lab: dict[str, Any]) -> None:
    for name in ("stranger", "group"):
        t = turn(lab, name)
        assert "conversation Telegram privée du propriétaire" in first_result(t), first_result(t)
        assert t["order"] == []


def test_g1_05_cron_run_cannot_schedule_or_take_feedback(lab: dict[str, Any]) -> None:
    steps = lab["main"]["cron"]["steps"]
    run1 = [s for s in steps if s["run"] == 0]
    # cronjob_manage: Hermes refuses it in a cron run (wording depends on tool_search).
    assert "not available in this execution context" in run1[4]["last_tool"] or \
        "'cronjob_manage' does not exist" in run1[4]["last_tool"]
    assert "n'est accessible qu'à son exécution planifiée" in run1[5]["last_tool"]  # feedback_add in cron
    assert "cronjob_manage" not in lab["main"]["cron"]["cron_offered"]
    assert all(j["name"] != "evil" for j in lab["main"]["final_jobs"])


def test_g1_06_record_tool_refused_in_chat(lab: dict[str, Any]) -> None:
    assert "n'est accessible qu'à son exécution planifiée" in first_result(turn(lab, "record_in_chat"))


# ---- AC2 / G2 ---------------------------------------------------------------------------------------------

def test_g2_01_denied_creation_saves_nothing(lab: dict[str, Any]) -> None:
    t = turn(lab, "deny")
    assert t["order"][-1] == "card" and set(t["order"][:-1]) == {"post"}
    assert lab["main"]["turns"]["deny_jobs"] == 0
    assert "denied" in first_result(t).lower() or "refus" in first_result(t).lower()


def test_g2_02_approved_creation_saved_as_shown(lab: dict[str, Any]) -> None:
    t = turn(lab, "create")
    assert t["order"][-1] == "card" and t["order"].count("post") >= 2  # long instructions: split before the card
    jobs = lab["main"]["turns"]["create_jobs"]
    assert len(jobs) == 1
    job = jobs[0]
    shown = re.sub(r"\(\d+/\d+\) ", "", t["posted_text"])
    assert "".join(job["prompt"].split()) in "".join(shown.split())  # the text the owner saw is what was saved
    assert "0 7 * * 1-5" in t["posted_text"] and "heure de Guadeloupe" in t["posted_text"] and "UTC" in t["posted_text"]
    assert job["expr"] == "0 7 * * 1-5" and job["next_run_at"].endswith("07:00:00-04:00")
    assert job["deliver"] == "origin" and job["origin"]["chat_id"] == OWNER and job["origin"]["platform"] == "telegram"
    card = next(e for e in t["events"] if e["kind"] == "card")
    assert card["pattern_key"].startswith("plugin_rule:scout_cron:") and len(card["description"]) <= 450
    assert "next_run_guadeloupe" in t["tool_results"][0]


def test_g2_03_single_use_rule_keys(lab: dict[str, Any]) -> None:
    keys = [e["pattern_key"] for name in ("deny", "create", "update", "resume", "feedback")
            for e in turn(lab, name)["events"] if e["kind"] == "card"]
    assert len(keys) == 5 and len(set(keys)) == 5


def test_g2_04_timeout_is_refusal(lab: dict[str, Any]) -> None:
    t = turn(lab, "timeout")
    assert "card" in t["order"] and lab["main"]["turns"]["timeout_jobs"] == 5
    assert "timed out" in first_result(t).lower() or "silence" in first_result(t).lower()


def test_g2_05_yolo_refused_before_anything_is_posted(lab: dict[str, Any]) -> None:
    t = turn(lab, "yolo")
    assert "/yolo" in first_result(t) and t["order"] == []


def test_g2_06_update_in_place_and_resume_need_approval(lab: dict[str, Any]) -> None:
    upd = lab["main"]["turns"]["update_jobs"]
    first = lab["main"]["turns"]["create_jobs"][0]
    assert len(upd) == 1 and upd[0]["id"] == first["id"] and upd[0]["expr"] == "0 6 * * 1-5"
    assert upd[0]["prompt"].endswith(" v2") and "card" in turn(lab, "update")["order"]
    assert lab["main"]["turns"]["pause_state"] == "paused" and turn(lab, "pause")["order"] == []
    assert lab["main"]["turns"]["resume_state"] == "scheduled" and "card" in turn(lab, "resume")["order"]


def test_g2_07_list_free_and_annotated(lab: dict[str, Any]) -> None:
    t = turn(lab, "list")
    assert t["order"] == [] and "next_run_guadeloupe" in first_result(t) and "next_run_utc" in first_result(t)


def test_g2_08_feedback_needs_approval_and_reaches_the_notepad(lab: dict[str, Any]) -> None:
    t = turn(lab, "feedback")
    assert t["order"][-1] == "card" and "RETOUR-PROPRIO" in t["posted_text"]
    assert '"success": true' in first_result(t)
    assert "RETOUR-PROPRIO" in lab["main"]["command"]["owner"]


def test_g2_09_no_permanent_allowlist_entry(lab: dict[str, Any]) -> None:
    assert lab["main"]["allowlist"] == []


# ---- AC3 / G3 ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["every_30m", "interval", "one_shot", "twice_a_day", "foreign_deliver",
                                  "deliver_all", "failure_deliver", "script", "toolsets", "no_agent", "workdir",
                                  "huge"])
def test_g3_01_refusals(lab: dict[str, Any], name: str) -> None:
    t = lab["main"]["turns"]["refusals"][name]
    assert refused(t), (name, first_result(t))
    assert t["order"] == []  # nothing posted, no card


def test_g3_02_nothing_saved_by_refusals(lab: dict[str, Any]) -> None:
    assert lab["main"]["turns"]["refusal_jobs"] == 1


def test_g3_03_job_cap_counts_paused_jobs(lab: dict[str, Any]) -> None:
    t = lab["main"]["turns"]
    assert t["cap_jobs_before"] == 5 and t["cap_jobs_after"] == 5 and refused(t["cap"])
    assert "plafond 5" in first_result(t["cap"])


def test_g3_04_duplicate_name_and_run_refused(lab: dict[str, Any]) -> None:
    assert refused(turn(lab, "dup_name")) and "porte déjà ce nom" in first_result(turn(lab, "dup_name"))
    assert refused(turn(lab, "run")) and turn(lab, "run")["order"] == []


def test_g3_05_run_tool_call_caps(lab: dict[str, Any]) -> None:
    results = lab["main"]["cron"]["cap_results"]
    web = results[:5]
    assert not any("Plafond" in r for r in web[:3]) and all("Plafond de 3 recherches" in r for r in web[3:])
    rest = results[5:11]
    assert not any("Plafond" in r for r in rest[:5]) and "Plafond de 8 appels" in rest[5], rest


def test_g3_06_deploy_check_accepts_the_policy(lab: dict[str, Any]) -> None:
    c = lab["checks"]
    assert c["scout_cron_pre"]["rc"] == 0, c["scout_cron_pre"]
    assert c["scout_cron_post"]["rc"] == 0, c["scout_cron_post"]
    assert "5 job(s)" in c["scout_cron_post"]["out"] and "OUT OF POLICY" not in c["scout_cron_post"]["out"]
    assert c["scout_cron_wrong_switch"]["rc"] == 1 and "must not be loaded" in c["scout_cron_wrong_switch"]["out"]


# ---- AC4 / G4 ---------------------------------------------------------------------------------------------

def test_g4_01_tainted_session_blocked_and_nothing_posted(lab: dict[str, Any]) -> None:
    t = turn(lab, "tainted")
    assert t["order"] == []  # requirement (a): no proposal, no card
    assert "courriels" in first_result(t) or "autre contrôle de sécurité" in first_result(t), first_result(t)
    assert lab["main"]["turns"]["tainted_jobs"] == 1  # under the job cap: only the mail veto refused it
    assert all(j["name"] != "Contaminée" for j in lab["main"]["final_jobs"])


# ---- AC5 / G5 ---------------------------------------------------------------------------------------------

def test_g5_01_two_runs_record_and_deduplicate(lab: dict[str, Any]) -> None:
    c = lab["main"]["cron"]
    assert [r["success"] for r in c["runs"]] == [True, True]
    steps = {(s["run"], s["step"]): s for s in c["steps"]}
    first_check = json.loads(steps[(0, 1)]["last_tool"])
    assert first_check["already_alerted"] == [] and len(first_check["new"]) == 2
    second_check = json.loads(steps[(1, 1)]["last_tool"])
    assert [a["title"] for a in second_check["already_alerted"]] == ["Ingénieur A"]
    assert second_check["new"] == ["https://jobs.example.test/o/3"]
    assert not steps[(0, 0)]["journal_injected"] and steps[(1, 0)]["journal_injected"]
    assert "JOURNAL-RUN-1" in json.loads(steps[(1, 3)]["last_tool"])["journal"]
    assert c["notes"]["journal"].startswith("JOURNAL-RUN-1")


def test_g5_02_ledger_private_and_bounded(lab: dict[str, Any]) -> None:
    c = lab["main"]["cron"]
    assert c["ledger_mode"] == "0o600"
    assert len(c["ledger"]["entries"]) == 3
    assert all(re.fullmatch(r"[0-9a-f]{16}", k) for k in c["ledger"]["entries"])
    assert not any("example.test" in k for k in c["ledger"]["entries"])


def test_g5_03_cron_tools_narrowed(lab: dict[str, Any]) -> None:
    offered = set(lab["main"]["cron"]["cron_offered"])
    assert not offered & {"memory", "session_search", "todo", "clarify", "cronjob_manage"}
    assert {"web_search", "web_extract"} <= offered
    assert ("tool_call" in offered) if lab["tool_search"] == "auto" else ("scout_task_record" in offered)


def test_g5_04_remove_deletes_the_ledger(lab: dict[str, Any]) -> None:
    m = lab["main"]
    assert m["remove_ledger_before"] and not m["remove_ledger_after"]
    assert "card" in m["remove"]["order"]


def test_g5_05_command_owner_only(lab: dict[str, Any]) -> None:
    c = lab["main"]["command"]
    assert "Tâches planifiées de Scout : 5 / 5" in c["owner"]
    assert "conversation Telegram privée du propriétaire" in c["stranger"]
    assert c["elsewhere"] == {"default": True, "cafe-ia": True}


# ---- AC6 (part) / AC7 ---------------------------------------------------------------------------------------

def test_ac6_01_existing_deploy_checks_still_pass(lab: dict[str, Any]) -> None:
    c = lab["checks"]
    assert c["scout_mail"]["rc"] == 0, c["scout_mail"]
    if lab["tool_search"] == "off":  # the hermes-31 configuration the check is written for
        for name in ("toolsets_scout", "toolsets_cafe", "toolsets_nora"):
            assert c[name]["rc"] == 0, (name, c[name])


def test_bridge_01_calls_through_tool_call_are_guarded(lab: dict[str, Any]) -> None:
    """With tool_search on, cronjob_manage is deferred: the model calls it through tool_call and the
    guards still apply (Hermes unwraps the bridge before plugin hooks)."""
    t = turn(lab, "create")
    if lab["tool_search"] == "auto":
        assert "cronjob_manage" not in t["valid_tools"] and "tool_call" in t["valid_tools"]
    else:
        assert "cronjob_manage" in t["valid_tools"] and "tool_call" not in t["valid_tools"]
    assert t["order"][-1] == "card"


def test_ac7_01_restart_reads_jobs_back_without_firing(lab: dict[str, Any]) -> None:
    r = lab["restart"]
    assert len(r["jobs"]) == 5 and r["due_now"] == [] and r["fired_on_restart"] == 0  # nothing fires at restart
    # Missed beyond the grace window while down: exactly one catch-up run over two ticks, then the next slot.
    assert r["due_overdue"] == [r["overdue_target"]] and r["runs_after_two_ticks"] == 1, r
    assert r["next_run_after"] > r["past"] and r["last_run_at"]


def test_tz_01_profile_timezone_in_the_multiplexed_scope(lab: dict[str, Any]) -> None:
    tz = lab["main"]["timezones"]
    assert tz["job-search"].endswith("07:00:00-04:00") and tz["cafe-ia"].endswith("07:00:00+00:00")


def test_tz_02_plugin_next_runs_match_hermes(lab: dict[str, Any]) -> None:
    for row in lab["main"]["schedule_compare"]:
        assert row["plugin"] == row["hermes"], row
