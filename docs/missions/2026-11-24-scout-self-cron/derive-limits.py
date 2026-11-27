"""Largest instruction / feedback size (as displayed) whose worst-case one-message post fits POST_BUDGET.

Run from the worktree root: uv run --no-sync python docs/missions/2026-11-24-scout-self-cron/derive-limits.py
The policy limits are lifted here (search above the configured caps); the size bound is policy._cost.
"""
import dataclasses
import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile

sys.path.insert(0, "hermes/tests")
import test_scout_cron as t  # noqa: E402
import scout_cron  # noqa: E402
from scout_cron import policy  # noqa: E402
from scout_cron.schedule import ScheduleError, daily_fields  # noqa: E402


def cost(post: str) -> int:
    total, fenced = 0, False
    for line in post.split("\n"):
        total += policy._cost(line, fenced and line != policy.FENCE)
        fenced = fenced != (line == policy.FENCE)
    return total


def exprs() -> list[str]:
    """Accepted daily expressions of at most MAX_EXPR_CHARS, dense in MarkdownV2 specials."""
    out = []
    for minute, hour in (("59", "23"), ("58", "22")):
        for tail in ("* *", "* 1-5", "1-12 1-5"):
            dom = ""
            for a in range(1, 31, 3):
                cand = f"{dom},{a}-{a + 1}" if dom else f"{a}-{a + 1}"
                if len(f"{minute} {hour} {cand} {tail}") > policy.MAX_EXPR_CHARS:
                    break
                dom = cand
            e = f"{minute} {hour} {dom} {tail}"
            try:
                daily_fields(e)
                out.append(e)
            except ScheduleError:
                pass
    return out


NAMES = ["\\" * 40, "`\\" * 20, "😀" * 40]  # 80 displayed units each, all fenced
EXPRS = exprs()


def worst_proposal_cost(p: int) -> tuple[int, str]:
    prompt_a, prompt_b = "\\" * (p // 2) + "x" * (p % 2), "😀" * (p // 2) + "y" * (p % 2)
    assert policy.display_size(prompt_a) == policy.display_size(prompt_b) == p
    worst, which = 0, ""
    for day in range(7):
        now = t.NOW + timedelta(days=day)
        for e1 in EXPRS:
            e2 = next(e for e in EXPRS if e != e1)
            for paused in (False, True):
                extra = {"state": "paused", "enabled": False} if paused else {}
                stored = t.job(job_id="ffffffffffff", name=NAMES[0], expr=e1, prompt=prompt_a, **extra)

                def ctx(store):
                    c = t.ctx(store, max_prompt_chars=8000)
                    return policy.Context(**{**c.__dict__, "now": now})
                cases = {
                    "create": (t.create_args(name=NAMES[1], schedule=e1, prompt=prompt_a), ctx([])),
                    "remove": ({"action": "remove", "job_id": "ffffffffffff"}, ctx([stored])),
                    "update": ({"action": "update", "job_id": "ffffffffffff", "name": NAMES[2], "schedule": e2,
                                "prompt": prompt_b}, ctx([stored])),
                }
                if paused:
                    cases["resume"] = ({"action": "resume", "job_id": "ffffffffffff"}, ctx([stored]))
                for kind, (args, c) in cases.items():
                    d = policy.evaluate(args, c)
                    assert d.kind == "confirm", (kind, d.message)
                    if cost(d.proposal) > worst:
                        worst, which = cost(d.proposal), kind
    return worst, which


def worst_feedback_cost(f: int) -> int:
    text = "\\" * (f // 2) + "x" * (f % 2)
    worst = 0
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        path.write_text(json.dumps(t.settings_raw()))
        for e1 in EXPRS:
            for paused in (False, True):
                p = scout_cron._Plugin(SimpleNamespace(), Path(tmp), port=t.FakePort(Path(tmp)), settings_path=path)
                p.guard_installed = True
                p.settings = dataclasses.replace(p.settings, limits=dataclasses.replace(p.settings.limits,
                                                                                       feedback_chars=8000))
                extra = {"state": "paused", "enabled": False} if paused else {}
                p.port.store.append(t.job(job_id="ffffffffffff", name=NAMES[0], expr=e1, prompt="x" * 3000, **extra))
                proposal = []
                p.port.post = lambda text: proposal.append(text) or True
                out = t.call(p, {"action": "feedback_add", "job_id": "ffffffffffff", "text": text},
                             tool="scout_task_record")
                if out and out["action"] == "block" and "un seul message" in out["message"]:
                    return policy.POST_BUDGET + 1  # refused for size even with the instructions as a fingerprint
                assert out and out["action"] == "approve", out
                worst = max(worst, cost(proposal[0]))
    return worst


if __name__ == "__main__":
    print("expressions:", EXPRS)
    def largest(fn, lo, hi):
        while lo < hi:  # largest n with fn(n) <= POST_BUDGET
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if fn(mid) <= policy.POST_BUDGET else (lo, mid - 1)
        return lo
    p = largest(lambda n: worst_proposal_cost(n)[0], 1000, 4000)
    c, kind = worst_proposal_cost(p)
    print(f"max instructions (displayed): {p}; worst post {c} units ({kind}); +1 -> {worst_proposal_cost(p + 1)}")
    f = largest(worst_feedback_cost, 100, 4000)
    print(f"max feedback (displayed): {f}; worst post {worst_feedback_cost(f)}; +1 -> {worst_feedback_cost(f + 1)}")
