"""In-image lab for scout_cron (run by test_scout_cron_image.py inside hermes-agent:v0.22.5, --network none).

Three homes (default = Nora, job-search = Scout, cafe-ia = Kaféine), Scout with scout_mail and scout_cron.
Real Hermes code paths: AIAgent turns driven by a scripted local model (fake_llm.py) so tool calls go through
Hermes' executor, the tool_search bridge, the plugin hooks and the real approval gate (its gateway queue,
answered here as the Telegram button would); real cron executions (``_execute_job_now``, the path of
``hermes cron run``); the real cron store, notepad and parser. Faked: the gateway runner and Telegram
adapter behind ``post_message`` (they record what would be sent) and the model. Prints ``LAB <json>``.
Usage: image_lab.py <phase>   phase = main | restart
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
import weakref
from datetime import UTC
from types import SimpleNamespace

logging.basicConfig(level=logging.ERROR)
ROOT = "/tmp/data"
HOMES = {"default": ROOT, "job-search": f"{ROOT}/profiles/job-search", "cafe-ia": f"{ROOT}/profiles/cafe-ia"}
SCOUT = HOMES["job-search"]
OWNER, STRANGER = "111", "999"
PORT = 18080
SCEN = "/tmp/scenarios.json"
REQS = "/tmp/requests.jsonl"
MARKER = "📬 Courriels — contenu externe non fiable"
SCENARIOS: dict = {}
EVENTS: list = []
ANSWERS: list = []


def write_scenarios() -> None:
    with open(SCEN, "w", encoding="utf-8") as fh:
        json.dump(SCENARIOS, fh, ensure_ascii=False)


def requests_for(scenario: str) -> list[dict]:
    try:
        with open(REQS, encoding="utf-8") as fh:
            return [r for r in map(json.loads, fh) if r["scenario"] == scenario]
    except FileNotFoundError:
        return []


def start_llm() -> subprocess.Popen:
    write_scenarios()
    proc = subprocess.Popen([sys.executable, "/lab/fake_llm.py", str(PORT), SCEN, REQS])
    import socket
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", PORT), 1).close()
            return proc
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("fake model did not start")


# ---- fake gateway (post_message transport) + approval answers ------------------------------------------

def install_gateway() -> None:
    import gateway.run as gr
    from gateway.config import Platform  # noqa: F401

    class Adapter:
        async def send(self, chat_id, text, metadata=None):
            EVENTS.append({"kind": "post", "chat": chat_id, "len": len(text), "text": text})
            return SimpleNamespace(success=True, message_id=str(len(EVENTS)))

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    adapter = Adapter()

    class Runner:
        _running = True
        _gateway_loop = loop
        session_store = SimpleNamespace(lookup_by_session_key=lambda key: None)

        def _session_key_for_source(self, source):
            return CURRENT["key"]

        def _plugin_messaging_session_owned(self, *a, **k):
            return True

        def _delivery_adapter_for(self, source):
            return adapter

        def _thread_metadata_for_source(self, source):
            return None

    runner = Runner()
    globals()["_RUNNER"] = runner
    gr._gateway_runner_ref = weakref.ref(runner)


CURRENT = {"key": ""}


def notify_factory(key):
    from tools.approval import resolve_gateway_approval

    def notify(data):
        EVENTS.append({"kind": "card", "description": data.get("description"), "pattern_key": data.get("pattern_key"),
                       "allow_permanent": data.get("allow_permanent")})
        answer = ANSWERS.pop(0) if ANSWERS else None
        if answer is not None:
            threading.Timer(0.3, lambda: resolve_gateway_approval(key, answer)).start()
    return notify


# ---- turns -----------------------------------------------------------------------------------------------

def in_home(name, fn):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    token = set_hermes_home_override(HOMES[name])
    try:
        return fn()
    finally:
        reset_hermes_home_override(token)


_turn_no = iter(range(1, 10_000))


def turn(scenario: str, steps: list, *, answers=(), profile="job-search", platform="telegram", user=OWNER,
         chat=OWNER, chat_type="dm", session_id=None, before=None) -> dict:
    """One agent turn of ``profile`` on ``platform``; returns events, tool results and the final text."""
    from gateway.config import Platform
    from gateway.plugin_messages import bind_live_source
    from gateway.session import SessionSource
    from gateway.session_context import clear_session_vars, scoped_session_key, set_session_vars
    from hermes_cli.config import load_config
    from hermes_cli.tools_config import _get_platform_tools
    from run_agent import AIAgent
    from tools.approval import register_gateway_notify, unregister_gateway_notify
    from tools.approval_context import reset_current_session_key, set_current_session_key

    SCENARIOS[scenario] = steps
    write_scenarios()
    n = next(_turn_no)
    sid = session_id or f"S{n}"
    key = f"agent:main:{platform}:{chat_type}:{chat}:{n}"
    CURRENT["key"] = key
    del EVENTS[:]
    ANSWERS[:] = list(answers)

    def run():
        cfg = load_config()
        tokens = set_session_vars(platform=platform, chat_id=chat, chat_type=chat_type, user_id=user,
                                  session_key=key, session_id=sid, profile=profile)
        ktoken = set_current_session_key(key)
        register_gateway_notify(key, notify_factory(key))
        src = SessionSource(platform=Platform(platform) if platform in ("telegram",) else Platform.TELEGRAM,
                            chat_id=chat, chat_type=chat_type, user_id=user)
        try:
            if before:
                before(key, sid)
            with scoped_session_key(key), bind_live_source(src):
                agent = AIAgent(base_url=f"http://127.0.0.1:{PORT}/v1", api_key="x", model="fake-model",
                                platform=platform, quiet_mode=True,
                                enabled_toolsets=sorted(_get_platform_tools(cfg, platform)),
                                disabled_toolsets=(cfg.get("agent") or {}).get("disabled_toolsets"),
                                session_id=sid)
                result = agent.run_conversation(f"[[SC:{scenario}]] demande")
            return {"final": result.get("final_response"), "valid_tools": sorted(agent.valid_tool_names)}
        finally:
            unregister_gateway_notify(key)
            reset_current_session_key(ktoken)
            clear_session_vars(tokens)

    out = in_home(profile, run)
    reqs = requests_for(scenario)
    out["tool_results"] = [r["last_tool"] for r in reqs[1:]]
    out["offered"] = reqs[0]["tools"] if reqs else []
    out["events"] = [{k: v for k, v in e.items() if k != "text"} for e in EVENTS]
    out["posted_text"] = "\n".join(e["text"] for e in EVENTS if e["kind"] == "post")
    out["order"] = [e["kind"] for e in EVENTS]
    return out


def call(action_args: dict) -> list:
    return [{"call": "cronjob_manage", "args": action_args}, {"say": "fin"}]


def scout_jobs() -> list[dict]:
    def read():
        from cron.jobs import list_jobs, use_cron_store
        with use_cron_store(SCOUT):
            return list_jobs(include_disabled=True)
    return in_home("job-search", read)


def summary(job: dict) -> dict:
    return {k: job.get(k) for k in ("id", "name", "deliver", "origin", "next_run_at", "state", "enabled",
                                    "prompt", "enabled_toolsets", "script")} | {
        "expr": (job.get("schedule") or {}).get("expr")}


# ---- phases ---------------------------------------------------------------------------------------------

def phase_main() -> dict:
    os.environ["HERMES_HOME"] = SCOUT
    os.environ["HERMES_GATEWAY_SESSION"] = "1"
    llm = start_llm()
    from hermes_cli import plugins as hp
    out: dict = {}

    def probe():
        m = hp._ensure_plugins_discovered()
        return {"plugins": sorted(k for k, p in m._plugins.items() if "scout" in k and p.error is None),
                "hooks": sorted(h for h, c in m._hooks.items() if c), "commands": sorted(hp.get_plugin_commands())}
    out["discovery"] = {n: in_home(n, probe) for n in ("default", "cafe-ia", "job-search")}

    def exposure():
        from hermes_cli.config import load_config
        from hermes_cli.tools_config import _get_platform_tools
        cfg = load_config()
        return {p: sorted(t for t in _get_platform_tools(cfg, p) if t in ("cronjob", "scout_task_record"))
                for p in ("telegram", "cron", "api_server", "cli")}
    out["exposure"] = {n: in_home(n, exposure) for n in HOMES}
    install_gateway()
    huge = "x" * 6001
    owner_prompt = ("[[SC:none]] Consigne de veille synthétique : offres DevOps, télétravail, "
                    "cinq offres au plus, en français.\n• puce\n" + "détail " * 640)

    t = {}
    t["deny"] = turn("deny", call({"action": "create", "name": "Veille A", "schedule": "0 7 * * 1-5",
                                   "prompt": owner_prompt}), answers=["deny"])
    t["deny_jobs"] = len(scout_jobs())
    t["create"] = turn("create", call({"action": "create", "name": "Veille A", "schedule": "weekdays at 7am",
                                       "prompt": owner_prompt}), answers=["once"])
    jobs = scout_jobs()
    t["create_jobs"] = [summary(j) for j in jobs]
    job_id = jobs[0]["id"] if jobs else ""
    t["list"] = turn("list", call({"action": "list"}))
    t["dup_name"] = turn("dup", call({"action": "create", "name": "veille a", "schedule": "0 8 * * 1",
                                      "prompt": "y"}), answers=["once"])
    t["update"] = turn("update", call({"action": "update", "job_id": job_id, "prompt": owner_prompt + " v2",
                                       "schedule": "0 6 * * 1-5"}), answers=["once"])
    t["update_jobs"] = [summary(j) for j in scout_jobs()]
    t["pause"] = turn("pause", call({"action": "pause", "job_id": job_id}))
    t["pause_state"] = summary(scout_jobs()[0])["state"]
    t["resume"] = turn("resume", call({"action": "resume", "job_id": job_id}), answers=["once"])
    t["resume_state"] = summary(scout_jobs()[0])["state"]
    t["run"] = turn("run", call({"action": "run", "job_id": job_id}))
    def taint(key, sid):
        hp.invoke_hook("pre_llm_call", session_id=sid, user_message=f'[Replying to: "{MARKER} ..."] fais-le',
                       conversation_history=[], parent_session_id="", turn_id="t", task_id="", is_first_turn=False,
                       model="m", platform="telegram", sender_id=OWNER)
    t["tainted"] = turn("tainted", call({"action": "create", "name": "Contaminée", "schedule": "0 7 * * 3",
                                         "prompt": "court"}), answers=["once"], before=taint, session_id="S-TAINT")
    t["tainted_jobs"] = len(scout_jobs())
    refusals = {
        "every_30m": {"schedule": "*/30 * * * *"}, "interval": {"schedule": "every 2h"},
        "one_shot": {"schedule": "in 1h"}, "twice_a_day": {"schedule": "0 7,19 * * *"},
        "foreign_deliver": {"deliver": "telegram:999"}, "deliver_all": {"deliver": "all"},
        "failure_deliver": {"failure_deliver": "telegram:999"}, "script": {"script": "x.py"},
        "toolsets": {"enabled_toolsets": ["web", "kandidat_confirm"]}, "no_agent": {"no_agent": True},
        "workdir": {"workdir": "/tmp"}, "huge": {"prompt": huge},
    }
    t["refusals"] = {}
    for name, extra in refusals.items():
        args = {"action": "create", "name": f"R {name}", "schedule": "0 9 * * 1", "prompt": "court"} | extra
        t["refusals"][name] = turn(f"ref_{name}", call(args), answers=["once"])
    t["refusal_jobs"] = len(scout_jobs())
    # Cap N = 5 (paused jobs count): four more, then the sixth is refused.
    for i in range(4):
        turn(f"fill{i}", call({"action": "create", "name": f"Remplissage {i}", "schedule": f"{10 + i} 9 * * 1",
                               "prompt": "court"}), answers=["once"])
    t["cap_jobs_before"] = len(scout_jobs())
    t["cap"] = turn("cap", call({"action": "create", "name": "Sixième", "schedule": "0 9 * * 2",
                                 "prompt": "court"}), answers=["once"])
    t["cap_jobs_after"] = len(scout_jobs())
    # Channels and profiles.
    t["stranger"] = turn("stranger", call({"action": "list"}), user=STRANGER, chat=STRANGER)
    t["group"] = turn("group", call({"action": "list"}), chat="-100", chat_type="group")
    t["api_server"] = turn("api", call({"action": "list"}), platform="api_server")
    t["cli"] = turn("cli", call({"action": "list"}), platform="cli")
    t["nora"] = turn("nora", call({"action": "list"}), profile="default")
    t["kafeine"] = turn("kafeine", call({"action": "list"}), profile="cafe-ia")
    t["record_in_chat"] = turn("rec_chat", [{"call": "scout_task_record", "args": {"action": "journal_set",
                                                                                  "text": "x"}}, {"say": "fin"}])

    def yolo(key, sid):
        from tools.approval import enable_session_yolo
        enable_session_yolo(key)
    t["yolo"] = turn("yolo", call({"action": "remove", "job_id": job_id}), answers=["once"], before=yolo)

    t["feedback"] = turn("feedback", [{"call": "scout_task_record", "args": {
        "action": "feedback_add", "job_id": job_id, "text": "RETOUR-PROPRIO : privilégier les ESN."}},
        {"say": "fin"}], answers=["once"])
    t["timeout"] = turn("timeout", call({"action": "remove", "job_id": job_id}), answers=[None])
    t["timeout_jobs"] = len(scout_jobs())
    out["turns"] = t

    # ---- cron runs (record, dedup, cap, no scheduling) ------------------------------------------------------
    out["cron"] = cron_phase(job_id)

    # ---- remove: approved, ledger deleted -----------------------------------------------------------------------
    ledger = f"{SCOUT}/plugin-data/scout_cron/ledger/{out['cron']['dedup_job']}.json"
    out["remove_ledger_before"] = os.path.exists(ledger)
    out["remove"] = turn("remove", call({"action": "remove", "job_id": out["cron"]["dedup_job"]}), answers=["once"])
    out["remove_ledger_after"] = os.path.exists(ledger)

    # ---- /taches-scout ------------------------------------------------------------------------------------------
    handler = in_home("job-search", lambda: hp.get_plugin_command_handler("taches-scout"))
    src = SimpleNamespace(platform=SimpleNamespace(value="telegram"), chat_type="dm", chat_id=OWNER, user_id=OWNER)
    bad = SimpleNamespace(platform=SimpleNamespace(value="telegram"), chat_type="dm", chat_id=STRANGER, user_id=STRANGER)
    out["command"] = {"owner": handler(job_id, source=src), "stranger": handler("", source=bad),
                      "elsewhere": {n: in_home(n, lambda: hp.get_plugin_command_handler("taches-scout")) is None
                                    for n in ("default", "cafe-ia")}}
    out["schedule_compare"] = schedule_compare()
    out["timezones"] = timezones()
    out["final_jobs"] = [summary(j) for j in scout_jobs()]
    out["allowlist"] = command_allowlist()
    llm.kill()
    return out


def cron_phase(owner_job: str) -> dict:
    from cron.jobs import create_job, get_job, use_cron_store
    from tools.cronjob_tools import _execute_job_now
    res: dict = {}
    SCENARIOS["dedup"] = {"runs": [
        [{"call": "scout_task_record", "args": {"action": "check_alerted", "urls": [
            "https://jobs.example.test/o/1?utm_source=x", "https://jobs.example.test/o/2"]}},
         {"call": "scout_task_record", "args": {"action": "mark_alerted", "items": [
             {"url": "https://jobs.example.test/o/1", "title": "Ingénieur A"},
             {"url": "https://jobs.example.test/o/2", "title": "Ingénieur B"}]}},
         {"call": "scout_task_record", "args": {"action": "journal_set", "text": "JOURNAL-RUN-1 : source X lente."}},
         {"call": "cronjob_manage", "args": {"action": "create", "name": "evil", "schedule": "0 8 * * *",
                                             "prompt": "x"}},
         {"call": "scout_task_record", "args": {"action": "feedback_add", "job_id": owner_job, "text": "x"}},
         {"say": "RUN-1 : 2 offres."}],
        [{"call": "scout_task_record", "args": {"action": "check_alerted", "urls": [
            "https://www.jobs.example.test/o/1/", "https://jobs.example.test/o/3"]}},
         {"call": "scout_task_record", "args": {"action": "mark_alerted", "items": [
             {"url": "https://jobs.example.test/o/3", "title": "Ingénieur C"}]}},
         {"call": "scout_task_record", "args": {"action": "journal_get"}},
         {"say": "RUN-2 : 1 offre."}]]}
    SCENARIOS["runcap"] = [{"call": "web_search", "args": {"query": f"q{i}"}} for i in range(5)] + \
        [{"call": "scout_task_record", "args": {"action": "alerted_count" if i % 2 else "journal_get"}}
         for i in range(6)] + [{"say": "fin"}]
    write_scenarios()

    def run():
        with use_cron_store(SCOUT):
            job = create_job(prompt="[[SC:dedup]] Veille.", schedule="0 7 * * 1-5", name="dedup-lab",
                             deliver="local")
            runs = []
            for _ in range(2):
                r = _execute_job_now(get_job(job["id"]))
                runs.append({k: r.get(k) for k in ("success", "claimed", "error")})
            capjob = create_job(prompt="[[SC:runcap]] Veille.", schedule="0 8 * * 1-5", name="cap-lab", deliver="local")
            cap = _execute_job_now(get_job(capjob["id"]))
            after = get_job(job["id"])
            from cron import notepad
            notes = {n["key"]: n["value"] for n in notepad.list_notes(job["id"])}
            return job["id"], runs, {k: cap.get(k) for k in ("success", "error")}, after, notes, capjob["id"]
    job_id, runs, cap, after, notes, cap_id = in_home("job-search", run)
    reqs = requests_for("dedup")
    res.update({"dedup_job": job_id, "runs": runs, "cap_run": cap, "notes": notes,
                "next_run_after": after.get("next_run_at"),
                "steps": [{"run": r["run"], "step": r["step"], "last_tool": r["last_tool"],
                           "journal_injected": "JOURNAL-RUN-1" in r["first_user"],
                           "notepad_header": "Job notepad" in r["first_user"]} for r in reqs],
                "cron_offered": reqs[0]["tools"] if reqs else []})
    cap_reqs = requests_for("runcap")
    res["cap_results"] = [r["last_tool"] for r in cap_reqs[1:]]
    ledger = f"{SCOUT}/plugin-data/scout_cron/ledger/{job_id}.json"
    res["ledger_mode"] = oct(os.stat(ledger).st_mode & 0o777)
    with open(ledger, encoding="utf-8") as fh:
        res["ledger"] = json.load(fh)
    in_home("job-search", lambda: _remove(cap_id))
    return res


def _remove(job_id: str) -> None:
    from cron.jobs import remove_job, use_cron_store
    with use_cron_store(SCOUT):
        remove_job(job_id)


def schedule_compare() -> list:
    """Plugin next_runs vs the next_run_at Hermes stores, in Scout's timezone."""
    sys.path.insert(0, f"{SCOUT}/plugins")
    from scout_cron.schedule import next_runs

    def run():
        from datetime import datetime

        import hermes_time
        from cron.jobs import create_job, remove_job, use_cron_store
        rows = []
        with use_cron_store(SCOUT):
            for expr in ("0 7 * * 1-5", "30 6 * * 1,3,5", "0 7 1 * *", "15 23 * * 0", "0 7 * * 7", "0 0 29 2 *",
                         "0 7 1,15 * 1", "45 5 * JAN-MAR MON-FRI", "0 12 */2 * *", "0 7 * * */2"):
                job = create_job(prompt="p", schedule=expr, name=f"cmp {expr}", deliver="local")
                mine = next_runs(expr, hermes_time.get_timezone(), datetime.now(UTC), 1)
                rows.append({"expr": expr, "hermes": job["next_run_at"], "plugin": mine[0].isoformat() if mine else None})
                remove_job(job["id"])
        return rows
    return in_home("job-search", run)


def timezones() -> dict:
    """Per-profile timezone inside ONE multiplexed process, through the ticker's own scope helper.
    As in the gateway: multiplex mode on, so HERMES_TIMEZONE (the default profile's value, here a
    decoy) is ignored and each profile reads its own config."""
    import hermes_time
    from agent.secret_scope import set_multiplex_active
    from cron.scheduler_provider import _profile_cron_scope

    def make(home):
        from cron.jobs import create_job, remove_job
        with _profile_cron_scope(home):
            job = create_job(prompt="p", schedule="0 7 * * 1-5", name="tz", deliver="local")
            remove_job(job["id"])
            return job["next_run_at"]
    saved = os.environ.get("HERMES_TIMEZONE")
    os.environ["HERMES_TIMEZONE"] = "Asia/Tokyo"
    set_multiplex_active(True)
    hermes_time.reset_cache()
    try:
        return {name: make(HOMES[name]) for name in ("job-search", "cafe-ia")}
    finally:
        set_multiplex_active(False)
        if saved is None:
            os.environ.pop("HERMES_TIMEZONE", None)
        else:
            os.environ["HERMES_TIMEZONE"] = saved
        hermes_time.reset_cache()


def command_allowlist() -> list:
    def read():
        from hermes_cli.config import load_config
        return list(load_config().get("command_allowlist") or [])
    return in_home("job-search", read)


def phase_restart() -> dict:
    """A fresh process, as after a gateway restart: jobs are read back; the real ticker fires nothing
    before its time, and a slot missed while down fires once, not once per tick."""
    os.environ["HERMES_HOME"] = SCOUT
    os.environ["HERMES_GATEWAY_SESSION"] = "1"
    llm = start_llm()
    from datetime import datetime, timedelta

    import hermes_time
    from cron.jobs import get_due_jobs, get_job, list_jobs, update_job
    from cron.scheduler import tick
    from cron.scheduler_provider import _profile_cron_scope
    from croniter import croniter
    from hermes_cli import plugins as hp

    hp._ensure_plugins_discovered()
    with _profile_cron_scope(SCOUT):
        jobs = list_jobs(include_disabled=True)
        due_now = [j["id"] for j in get_due_jobs()]
        tick(verbose=False, sync=True)
        fired_on_restart = len([r for r in requests_for("none") if r["step"] == 0])
        # Down at the scheduled time, back more than the 2 h grace later: the stored next_run_at is a
        # real past occurrence of the expression.
        target = next(j for j in jobs if j.get("enabled", True) and j.get("state") != "paused")
        base = datetime.now(UTC).astimezone(hermes_time.get_timezone()) - timedelta(hours=2, minutes=5)
        past = croniter(target["schedule"]["expr"], base).get_prev(datetime).isoformat()
        update_job(target["id"], {"next_run_at": past})
        due_overdue = [j["id"] for j in get_due_jobs()]
        tick(verbose=False, sync=True)
        tick(verbose=False, sync=True)
        after = get_job(target["id"])
    runs = len([r for r in requests_for("none") if r["step"] == 0])
    llm.kill()
    return {"jobs": [summary(j) for j in jobs], "due_now": due_now, "fired_on_restart": fired_on_restart,
            "overdue_target": target["id"], "past": past, "due_overdue": due_overdue, "runs_after_two_ticks": runs,
            "next_run_after": after.get("next_run_at"), "last_run_at": after.get("last_run_at")}


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "main"
    result = phase_main() if phase == "main" else phase_restart()
    print("LAB " + json.dumps(result, ensure_ascii=False, default=str))
