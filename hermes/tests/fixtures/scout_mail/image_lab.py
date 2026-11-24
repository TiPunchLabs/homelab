"""In-image lab for scout_mail (run by test_scout_mail_image.py inside hermes-agent:v0.22.5, --network none).

One process, three homes (default = Nora, job-search = Scout, cafe-ia = Kaféine), the plugin installed and
enabled in Scout's home only. Prints one JSON line prefixed with ``LAB ``.
"""

import asyncio
import concurrent.futures
import json
import os
import random
from types import SimpleNamespace

from hermes_constants import reset_hermes_home_override, set_hermes_home_override

HOMES = {"default": "/tmp/data", "job-search": "/tmp/data/profiles/job-search", "cafe-ia": "/tmp/data/profiles/cafe-ia"}
MARKER = "📬 Courriels — contenu externe non fiable"


def in_home(name, fn):
    token = set_hermes_home_override(HOMES[name])
    try:
        return fn()
    finally:
        reset_hermes_home_override(token)


def main():
    from hermes_cli import plugins as hp
    from tools.registry import registry

    out = {}
    # Baseline = what discovery adds for a profile WITHOUT the plugin (bundled backends load lazily).
    toolsets_before = None

    def probe():
        manager = hp._ensure_plugins_discovered()
        loaded = {k: (p.error is None) for k, p in manager._plugins.items() if "scout" in k}
        return {"commands": sorted(hp.get_plugin_commands()), "scout_plugins": loaded,
                "hooks": sorted(h for h, cbs in manager._hooks.items() if cbs)}

    out["discovery"] = {"default": in_home("default", probe), "cafe-ia": in_home("cafe-ia", probe)}
    toolsets_before = sorted(registry.get_registered_toolset_names())
    out["discovery"]["job-search"] = in_home("job-search", probe)
    after = set(registry.get_registered_toolset_names())
    out["toolsets_added"] = sorted(after - set(toolsets_before))
    out["scout_tool_entries"] = [n for n in registry.get_registered_toolset_names() if "scout" in n or "mail" in n]

    # Taint one Scout session through the real hook path (pre_llm_call) with the trusted marker.
    in_home("job-search", lambda: hp.invoke_hook(
        "pre_llm_call", session_id="S-TAINT", user_message=f'[Replying to: "{MARKER} ..."] fais-le',
        conversation_history=[], parent_session_id="", turn_id="t", task_id="", is_first_turn=False,
        model="m", platform="telegram", sender_id="111"))

    counter = iter(range(1, 1_000_000))

    def decide(name, session):
        call_id = f"call-{next(counter)}"

        def run():
            d = hp._get_pre_tool_call_directive_details("web_search", {"query": "x"}, session_id=session,
                                                         tool_call_id=call_id)
            return d.action
        return in_home(name, run)

    # Concurrency: 400 decisions over 3 profiles and 2 sessions, in 16 threads, random order.
    jobs = [(random.choice(list(HOMES)), random.choice(["S-TAINT", "S-CLEAN"])) for _ in range(400)]
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        results = list(pool.map(lambda j: (j, decide(*j)), jobs))
    under = [j for j, action in results if j == ("job-search", "S-TAINT") and action != "block"]
    over = [j for j, action in results if j != ("job-search", "S-TAINT") and action is not None]
    out["concurrency"] = {"decisions": len(results), "under_blocked": len(under), "over_blocked": len(over),
                          "scout_tainted_blocked": decide("job-search", "S-TAINT"),
                          "nora_same_session": decide("default", "S-TAINT"),
                          "cafe_same_session": decide("cafe-ia", "S-TAINT"),
                          "scout_clean": decide("job-search", "S-CLEAN")}

    # Command handler in each scope: present only for Scout; missing key fails closed without network.
    source = SimpleNamespace(platform=SimpleNamespace(value="telegram"), chat_type="dm", chat_id="111", user_id="111")

    def command(name):
        handler = in_home(name, lambda: hp.get_plugin_command_handler("courriels"))
        if handler is None:
            return None
        token = set_hermes_home_override(HOMES[name])
        try:
            return asyncio.run(handler("", source=source))
        finally:
            reset_hermes_home_override(token)

    def history_rows():
        import sqlite3
        db = "/tmp/data/profiles/job-search/state.db"
        if not os.path.exists(db):
            return {"sessions": 0, "messages": 0}
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("sessions", "messages")}
        except sqlite3.Error:
            return {"sessions": -1, "messages": -1}
        finally:
            con.close()

    os.environ.pop("AGENTMAIL_API_KEY", None)
    rows_before = history_rows()
    out["command"] = {name: command(name) for name in HOMES}
    out["history_unchanged"] = history_rows() == rows_before
    stranger = SimpleNamespace(platform=SimpleNamespace(value="telegram"), chat_type="dm", chat_id="999", user_id="999")
    handler = in_home("job-search", lambda: hp.get_plugin_command_handler("courriels"))
    token = set_hermes_home_override(HOMES["job-search"])
    try:
        out["stranger"] = asyncio.run(handler("", source=stranger))
        out["group"] = asyncio.run(handler("", source=SimpleNamespace(
            platform=SimpleNamespace(value="telegram"), chat_type="group", chat_id="-5", user_id="111")))
    finally:
        reset_hermes_home_override(token)
    ledger = "/tmp/data/profiles/job-search/plugin-data/scout_mail/taint.json"
    out["ledger_mode"] = oct(os.stat(ledger).st_mode & 0o777) if os.path.exists(ledger) else None
    out["ledger_has_marker_text"] = MARKER in open(ledger, encoding="utf-8").read() if os.path.exists(ledger) else None
    out["recovery"] = recovery()
    out["short_write"] = recovery(short_write=True)
    out["retire"] = retire_lab()
    print("LAB " + json.dumps(out, ensure_ascii=False))


def recovery(short_write=False):
    """Review 3, R7 on Hermes' own SessionDB: ledger directory unwritable while the transcript is
    written, then permissions repaired and the plugin rebuilt as by a gateway restart.
    ``short_write`` (review 4, R9): every pwrite of the state block writes 3 bytes and says so."""
    import sys
    from pathlib import Path

    from hermes_state import SessionDB

    sys.path.insert(0, "/tmp/data/profiles/job-search/plugins")
    import scout_mail
    from scout_mail import taint

    home = Path("/tmp/recovery-short" if short_write else "/tmp/recovery") / "profiles/job-search"
    home.mkdir(parents=True)
    plugin = scout_mail._Plugin(SimpleNamespace(), home)
    plugin.store.record_result("111", ["9001"], [MARKER + "\n synthetic"])
    ledger_dir = plugin.store._path.parent
    db = SessionDB(db_path=home / "state.db")
    db.create_session("S", source="telegram")
    res = {}
    ledger_dir.chmod(0o500)
    real_pwrite = os.pwrite
    if short_write:
        taint.os.pwrite = lambda fd, data, off: real_pwrite(fd, data[:3], off)
    try:
        plugin.pre_llm_call(session_id="S", user_message=MARKER + " synthetic message")
        taint.os.pwrite = real_pwrite
        res["blocked_before_restart"] = plugin.pre_tool_call(tool_name="web_search", session_id="S")
        db.append_message("S", "user", MARKER + " synthetic message")
        res["lockdown_file"] = plugin.store._lock_path.exists()
    finally:
        taint.os.pwrite = real_pwrite
        ledger_dir.chmod(0o700)
    res["state_locked"] = plugin.store.locked()
    con = __import__("sqlite3").connect(home / "state.db")
    res["transcript_rows"] = con.execute("select count(*) from messages where session_id='S'").fetchone()[0]
    con.close()
    plugin = scout_mail._Plugin(SimpleNamespace(), home)
    plugin.pre_llm_call(session_id="S", user_message="suite", conversation_history=[
        {"role": "assistant", "content": "Résumé compressé synthétique."}])
    res["tool_after_restart"] = plugin.pre_tool_call(tool_name="web_search", session_id="S")
    plugin.pre_llm_call(session_id="S-child", parent_session_id="S", user_message="suite")
    res["child_tool_after_restart"] = plugin.pre_tool_call(tool_name="web_search", session_id="S-child")
    return res


def retire_lab():
    """Review 5, R11/F11 on Hermes' own CLI and SessionDB, in a separate HERMES_HOME: a fully persisted
    lockdown, Scout sessions that ``sessions list`` does not show (hidden, archived, tool, compressed
    child, rows past 20), then runbook 8.1 Retire with retire.py (one session held by a live compression
    lock first), Clear and Apply."""
    import subprocess
    import sys
    from pathlib import Path

    from hermes_state import SessionDB

    sys.path.insert(0, "/tmp/data/profiles/job-search/plugins")
    import scout_mail

    root = "/tmp/retire-data"
    env = dict(os.environ, HERMES_HOME=root)
    subprocess.run(["hermes", "profile", "create", "job-search", "--no-alias"], env=env, capture_output=True,
                   check=True)
    home = Path(root) / "profiles/job-search"
    plugin = scout_mail._Plugin(SimpleNamespace(), home)
    db = SessionDB(db_path=home / "state.db")
    derived = MARKER + " synthetic mail-derived instruction"
    ids = [f"S{i:02d}" for i in range(24)]
    for sid in ids:
        db.create_session(sid, source="telegram")
        db.append_message(sid, "user", "Bonjour")
    for sid, source in (("S-HIDDEN", "telegram"), ("S-ARCHIVED", "telegram"), ("S-TOOL", "tool"), ("P", "telegram")):
        db.create_session(sid, source=source)
        db.append_message(sid, "user", derived)
        ids.append(sid)
    db.set_session_hidden("S-HIDDEN", True)
    db.set_session_archived("S-ARCHIVED", True)
    db.end_session("P", "compression")
    db.create_session("P-C", source="telegram", parent_session_id="P")
    db.append_message("P-C", "assistant", "Résumé compressé synthétique.")
    ids.append("P-C")
    plugin._lockdown("synthetic recovery test")
    res = {"sessions": len(ids), "durable_lockdown": plugin.store.locked(),
           "blocked_before": plugin.pre_tool_call(tool_name="web_search", session_id="S-HIDDEN")}

    def cli(*args):
        return subprocess.run(args, env=env, capture_output=True, text=True, timeout=600, check=False)

    listed = cli("hermes", "-p", "job-search", "sessions", "list").stdout.split()
    res["list_hides"] = sorted(sid for sid in ids if sid not in listed)
    script = [sys.executable, "/tmp/data/profiles/job-search/plugins/scout_mail/retire.py"]
    if not os.path.exists(script[1]):
        res["retire_script"] = False
        return res
    res["retire_script"] = True
    inventory = cli(*script)
    res["inventory_exit"] = inventory.returncode
    res["inventory_ids"] = sorted(inventory.stdout.split()[3:])
    printed = inventory.stdout
    db.try_acquire_compression_lock("S-HIDDEN", "lab-holder", 300)
    guarded = cli(*script, "--delete")
    printed += guarded.stdout
    res["guarded_exit"] = guarded.returncode
    res["guarded_remaining"] = sorted(sid for sid in ids if db.get_session(sid) is not None)
    res["locked_after_refusal"] = plugin.store.locked()
    res["guarded_still_blocked"] = plugin.pre_tool_call(tool_name="web_search", session_id="S-HIDDEN")
    db.release_compression_lock("S-HIDDEN", "lab-holder")
    final = cli(*script, "--delete")
    printed += final.stdout
    res["final_exit"] = final.returncode
    res["remaining_sessions"] = sum(db.get_session(sid) is not None for sid in ids)
    res["remaining_messages"] = db.message_count()
    res["final_inventory_exit"] = cli(*script).returncode
    res["printed_mail_text"] = MARKER in printed or "instruction" in printed
    for name in ("taint.lockdown", "taint.state"):  # Clear
        (plugin.store._path.parent / name).unlink(missing_ok=True)
    plugin = scout_mail._Plugin(SimpleNamespace(), home)  # Apply
    res["fresh_session_tool"] = plugin.pre_tool_call(tool_name="web_search", session_id="S-NEW")
    return res


main()
