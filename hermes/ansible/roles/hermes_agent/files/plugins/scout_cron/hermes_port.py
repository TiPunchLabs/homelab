"""Every Hermes v0.22.5 internal scout_cron relies on, in one place (imported lazily, inside the image).

The image tests (test_scout_cron_image.py) exercise each of these against the real image; an upgrade of
Hermes must re-run them. Unit tests replace this class with a fake.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class HermesPort:
    """Thin adapter over Hermes; every method may raise, callers fail closed."""

    def __init__(self, ctx: Any, home: Path) -> None:
        self.ctx = ctx
        self.home = home

    @contextmanager
    def scope(self) -> Iterator[None]:
        """Pin Scout's home for the cron store, the notepad and the timezone, whatever the caller's
        thread had bound (a slash command runs on the gateway loop)."""
        from cron.jobs import use_cron_store
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        token = set_hermes_home_override(str(self.home))
        try:
            with use_cron_store(self.home):
                yield
        finally:
            reset_hermes_home_override(token)

    # ---- context ------------------------------------------------------------------------------

    def profile_name(self) -> str:
        from hermes_constants import profile_name_for_home

        return profile_name_for_home(self.home) or ""

    def cron_execution(self) -> Any:
        return self.ctx.current_cron_execution()

    def session(self, name: str) -> str:
        from gateway.session_context import get_session_env

        return str(get_session_env(name, "") or "")

    def approval_bypass_active(self) -> bool:
        """True when /yolo or approvals.mode: off would skip the approval gate."""
        from tools import approval, approval_context

        return bool(approval._yolo_active()) or str(approval_context._get_approval_mode()).lower() == "off"

    def other_hooks_veto(self, owner: Any, hook_kwargs: dict) -> bool:
        """Call every OTHER plugin's pre_tool_call callback of this profile directly and say whether
        one blocks. Hermes' own aggregator cannot be re-entered from inside a pre_tool_call callback:
        it skips a callback that is still running (ours) and turns the skip into a block. A callback
        that raises counts as a veto."""
        manager = self.ctx._manager
        for cb in list(manager._hooks.get("pre_tool_call", [])):
            if getattr(cb, "__self__", None) is owner:
                continue
            try:
                ret = manager._invoke_hook_callback(cb, dict(hook_kwargs))
            except Exception:
                return True
            if isinstance(ret, dict) and ret.get("action") == "block" and ret.get("message"):
                return True
        return False

    def post(self, text: str) -> bool:
        handle = self.ctx.post_message(text)
        return bool(getattr(handle, "ok", False))

    # ---- store --------------------------------------------------------------------------------

    def jobs(self) -> list[dict]:
        from cron.jobs import list_jobs

        return list_jobs(include_disabled=True)

    def resolve_job(self, ref: str) -> dict | None:
        from cron.jobs import resolve_job_ref

        return resolve_job_ref(ref)

    def parse_schedule(self, text: str) -> dict:
        from cron.jobs import parse_schedule

        return parse_schedule(text)

    def timezone(self) -> ZoneInfo:
        import hermes_time

        tz = hermes_time.get_timezone()
        return tz if tz is not None else ZoneInfo("UTC")

    def now(self) -> datetime:
        return datetime.now(ZoneInfo("UTC"))

    def note_get(self, job_id: str, key: str) -> str | None:
        from cron import notepad

        return notepad.get_note(job_id, key)

    def note_set(self, job_id: str, key: str, value: str) -> None:
        from cron import notepad

        notepad.set_note(job_id, key, value)
