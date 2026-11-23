"""Retire every session of Scout's profile through Hermes' own CLI (runbook, section 8.1, Retire).

Run inside the Hermes container, as the hermes user, with Scout parked:

    python3 <plugin dir>/retire.py            # inventory only (read-only), exit 0 when empty
    python3 <plugin dir>/retire.py --delete   # delete every session, then prove the store is empty

Not imported by the plugin: a standalone operator tool, standard library only.

Inventory is ``hermes -p <profile> sessions export - --format jsonl`` without any filter, which reads
every row of the profile store, whatever its source (``tool`` included), hidden or archived flag, or
place in a compression lineage, up to Hermes' 100,000-row export bound. ``sessions list`` is not an
inventory: it hides hidden, archived and tool rows and stops at 20. The export is cross-checked with
``sessions stats``: the export's non-archived rows must match its session count exactly, and an empty
export must come with zero messages. Any disagreement, non-JSON line (export
refused, unknown format) or failed command makes the inventory non-authoritative.

Deletion is ``sessions delete <id> --yes``, one id at a time, so Hermes keeps its active-turn and
compression-lock guards; a refusal is reported and never bypassed. After each pass the inventory is
taken again, until it is empty or a pass removes nothing. Only ids and counts are printed: exported
text is mail-derived and untrusted, it stays in memory. The taint markers are never touched.

Exit status: 0 the inventory is empty; 3 sessions remain (inventory mode); 2 the inventory is not
authoritative or a deletion was refused. On 2 or 3, keep the protection: no Clear, no Apply.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

EMPTY, REMAINING, UNSAFE = 0, 3, 2
_NO_STORE = "No sessions found."  # export on a profile that never created state.db


class InventoryError(RuntimeError):
    """The session inventory cannot be trusted to be complete."""


def _sessions(hermes: str, profile: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``hermes -p <profile> sessions <args>`` and capture its output."""
    return subprocess.run([hermes, "-p", profile, "sessions", *args], capture_output=True, text=True,
                          timeout=900, check=False)


def _count(stats: str, label: str) -> int:
    """Read ``Total <label>: N`` from ``sessions stats``."""
    match = re.search(rf"^Total {label}: (\d+)$", stats, re.M)
    if match is None:
        raise InventoryError(f"sessions stats did not report total {label}")
    return int(match.group(1))


def inventory(hermes: str, profile: str) -> list[str]:
    """Every session id of the profile store, or ``InventoryError``."""
    stats = _sessions(hermes, profile, "stats")
    if stats.returncode != 0:
        raise InventoryError(f"sessions stats exited {stats.returncode}")
    listed, messages = _count(stats.stdout, "sessions"), _count(stats.stdout, "messages")
    export = _sessions(hermes, profile, "export", "-", "--format", "jsonl")
    if export.returncode != 0:
        raise InventoryError(f"sessions export exited {export.returncode}")
    lines = [] if export.stdout.strip() == _NO_STORE else [x for x in export.stdout.splitlines() if x.strip()]
    ids: list[str] = []
    unarchived = 0
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except ValueError:
            raise InventoryError(f"sessions export line {number} is not JSON (export refused?)") from None
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise InventoryError(f"sessions export line {number} has no session id")
        if row.get("archived") not in (0, 1, False, True):
            raise InventoryError(f"sessions export line {number} has no archived flag")
        ids.append(row["id"])
        unarchived += not row["archived"]
    if len(set(ids)) != len(ids):
        raise InventoryError("sessions export repeated a session id")
    if unarchived != listed or (not ids and messages):
        raise InventoryError(f"sessions export saw {unarchived} non-archived of {len(ids)} sessions, "
                             f"sessions stats {listed} non-archived sessions and {messages} messages")
    return ids


def retire(hermes: str, profile: str, out=None) -> int:
    """Delete every session, pass after pass; ``EMPTY`` only once a fresh inventory is empty."""
    out = out or sys.stdout
    ids = inventory(hermes, profile)
    print(f"inventory: {len(ids)} session(s)", file=out)
    while ids:
        refused: dict[str, str] = {}
        for session_id in ids:
            done = _sessions(hermes, profile, "delete", session_id, "--yes")
            if done.returncode != 0:
                lines = (done.stdout + done.stderr).strip().splitlines()
                refused[session_id] = lines[-1] if lines else f"exit {done.returncode}"
        remaining = inventory(hermes, profile)
        print(f"deleted pass: {len(ids) - len(remaining)} removed, {len(remaining)} remaining", file=out)
        if remaining and len(remaining) >= len(ids):
            for session_id in remaining:
                print(f"refused {session_id}: {refused.get(session_id, 'still present')}", file=out)
            print("sessions remain: keep the protection, do not run Clear or Apply; retry once the turn "
                  "or lock has ended, never bypass it", file=out)
            return UNSAFE
        ids = remaining
    print("inventory empty: 0 sessions", file=out)
    return EMPTY


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--profile", default="job-search")
    parser.add_argument("--hermes", default="hermes", help="Hermes CLI executable")
    parser.add_argument("--delete", action="store_true", help="delete every session (default: inventory only)")
    args = parser.parse_args(argv)
    try:
        if args.delete:
            return retire(args.hermes, args.profile)
        ids = inventory(args.hermes, args.profile)
    except (InventoryError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"inventory not authoritative: {exc}; keep the protection, do not run Clear or Apply")
        return UNSAFE
    print(f"inventory: {len(ids)} session(s)")
    for session_id in ids:
        print(session_id)
    return EMPTY if not ids else REMAINING


if __name__ == "__main__":
    sys.exit(main())
