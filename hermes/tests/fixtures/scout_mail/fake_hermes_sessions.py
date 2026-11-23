"""Fake ``hermes -p <profile> sessions …`` for the offline retire.py tests (review 5, F11).

Mirrors the pinned v0.22.5 behaviours that matter, checked in the real image by
test_scout_mail_image.py: ``list`` hides hidden, archived and tool rows and stops at 20 (``--limit``);
a bare ``export - --format jsonl`` prints every row; ``stats`` counts non-archived sessions and all
messages; ``delete`` refuses a guarded (active turn / compression lock) or unknown session with exit 1.
State: JSON file named by ``FAKE_HERMES_STORE`` (absent = profile without state.db).
``FAKE_HERMES_EXPORT``: ``error`` prints the export guard's error line, ``drop`` omits one row.
"""

import json
import os
import sys
from pathlib import Path

STORE = Path(os.environ["FAKE_HERMES_STORE"])


def load():
    return json.loads(STORE.read_text()) if STORE.exists() else None


def main(argv):
    assert argv[:3] == ["-p", "job-search", "sessions"], argv
    action, rest = argv[3], argv[4:]
    store = load()
    sessions = (store or {}).get("sessions", {})
    if action == "list":
        limit = int(rest[rest.index("--limit") + 1]) if "--limit" in rest else 20
        shown = [s for s, row in sessions.items()
                 if not row.get("hidden") and not row.get("archived") and row.get("source") != "tool"][:limit]
        print("\n".join(shown) if shown else "No sessions found.")
    elif action == "export":
        if store is None:
            print("No sessions found.")
        elif os.environ.get("FAKE_HERMES_EXPORT") == "error":
            print("Error: session too large to export safely (limit 20000)")
        else:
            rows = list(sessions.items())
            if os.environ.get("FAKE_HERMES_EXPORT") == "drop":
                rows = rows[1:]
            for sid, row in rows:
                print(json.dumps({"id": sid, "source": row.get("source", "telegram"),
                                  "archived": int(bool(row.get("archived"))), "hidden": int(bool(row.get("hidden"))),
                                  "messages": row["messages"]}))
    elif action == "stats":
        listed = sum(1 for row in sessions.values() if not row.get("archived"))
        print(f"Total sessions: {listed}\nTotal messages: {sum(len(r['messages']) for r in sessions.values())}")
    elif action == "delete":
        sid = rest[0]
        assert "--yes" in rest
        if sid not in sessions:
            print(f"No session '{sid}'. Run: hermes sessions list to find the id.")
            return 1
        if sessions[sid].get("guarded"):
            print(f"Cannot delete active session: session '{sid}' (or a delegate child) has an active turn "
                  "lease or compression lock")
            return 1
        lineage = [sid] + [s for s, row in sessions.items() if row.get("compressed_from") == sid]
        for s in lineage:
            sessions.pop(s)
        STORE.write_text(json.dumps(store))
        print(f"Deleted session '{sid}'.")
    else:
        raise SystemExit(f"unsupported: {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
