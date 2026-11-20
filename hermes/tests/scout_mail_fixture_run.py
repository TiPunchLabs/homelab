"""SCOUT-MAIL-01 AC6 — measure sizes and local processing time of /courriels on synthetic fixtures.

Offline: the fake backend of test_scout_mail.py, default limits, no network, no model. Prints one JSON
document (sizes per stage, calls, local CPU time). Usage:
    .venv/bin/python hermes/tests/scout_mail_fixture_run.py > evidence/m3-fixture-run.json
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_scout_mail as t  # noqa: E402
from scout_mail.config import Limits  # noqa: E402


def batch(kind: str) -> list[dict]:
    names = list(t.FIXTURES["messages"])
    if kind == "all_fixtures":
        return [t.mail(n, i) for i, n in enumerate(names, start=1) if n != "oversized"]
    if kind == "typical_alerts_x8":
        long_alert = t.FIXTURES["messages"]["alert_fr"]["extracted_text"] * 6  # ~2.4k chars, a dense job alert
        return [t.mail("alert_fr", i, extracted_text=long_alert) for i in range(1, 9)]
    if kind == "html_newsletters_x8":
        html = t.FIXTURES["messages"]["newsletter_html"]["html"].replace("<p>", "<p>" + "Offre détaillée. " * 40)
        return [t.mail("newsletter_html", i, html=html * 5) for i in range(1, 9)]
    raise ValueError(kind)


def run(kind: str, action: str) -> dict:
    msgs = batch(kind)
    raw_bytes = [len(json.dumps(m, ensure_ascii=False).encode()) for m in msgs]
    timings = []
    for _ in range(20):
        svc, backend, _ = t.make(msgs)
        start = time.perf_counter()
        out = svc.run(action, t.SCOUT)
        timings.append((time.perf_counter() - start) * 1000)
    model_req = next((r for r in backend.requests if "deepseek" in r["url"]), None)
    return {
        "batch": kind, "action": action, "messages_in_inbox": len(msgs),
        "message_json_bytes": {"min": min(raw_bytes), "max": max(raw_bytes), "median": statistics.median(raw_bytes)},
        "list_response_bytes": len(backend.requests[0]["url"]) and next(
            e["bytes"] for e in out.stats["events"] if e["op"] == "agentmail_get"),
        "http_calls": out.stats["http_calls"], "model_calls": out.stats["model_calls"],
        "read": out.stats.get("read"), "has_more": out.stats.get("has_more"),
        "model_context_chars": out.stats.get("context_chars"),
        "model_request_bytes": len(model_req["body"]) if model_req else 0,
        "reply_chars": len(out.rendered.text), "reply_parts": len(out.rendered.parts),
        "not_shown": "Non affichés" in out.rendered.text,
        "local_processing_ms_median": round(statistics.median(timings), 2),
        "local_processing_ms_max": round(max(timings), 2),
    }


if __name__ == "__main__":
    lim = Limits()
    print(json.dumps({
        "limits": {k: getattr(lim, k) for k in lim.__dataclass_fields__ if not k.startswith("_")},
        "runs": [run(k, a) for k in ("all_fixtures", "typical_alerts_x8", "html_newsletters_x8") for a in ("", "liste")],
        "note": "Offline, fake backend: network and model latency are NOT measured here; see runbook for live timing.",
    }, ensure_ascii=False, indent=2))
