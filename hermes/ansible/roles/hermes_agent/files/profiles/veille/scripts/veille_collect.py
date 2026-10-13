"""Collect tech-watch items for the Hermes `veille` profile.

Run by Hermes cron through thin entry points (`veille_daily.py`,
`veille_weekly.py`): cron scripts take no arguments. The stdout of a run is
injected into the agent's prompt, which selects, scores and summarises.

Collection is deterministic and free (RSS/Atom, GitHub releases, Hacker News
Algolia API). Deduplication is local: an item is reported once, then
remembered in `veille/seen.json` for SEEN_RETENTION.
"""

from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

PROFILE_HOME = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
STATE_DIR = PROFILE_HOME / "veille"

BASE_SOURCES = SCRIPTS_DIR / "veille_sources.yaml"
# Owned by the agent: sources added or disabled from the Telegram chat.
LOCAL_SOURCES = PROFILE_HOME / "veille" / "sources.local.yaml"

SEEN_RETENTION = timedelta(days=45)
HISTORY_RETENTION = timedelta(days=21)
MAX_ITEMS_PER_SOURCE = 8
MAX_ITEMS_TOTAL = 80
SUMMARY_CHARS = 280
HTTP_TIMEOUT = 15.0
USER_AGENT = "hermes-veille/1.0 (+homelab tech watch)"

ATOM = "{http://www.w3.org/2005/Atom}"
# GitHub's releases.atom carries no prerelease flag: rc, canary and nightly
# tags are told apart by name only.
PRERELEASE = re.compile(r"\brc[.\-]?\d|canary|nightly|alpha|beta|preview|\bdev\d", re.IGNORECASE)


@dataclass(frozen=True)
class Item:
    """One collected entry, normalised across feed formats."""

    uid: str
    title: str
    link: str
    published: datetime | None
    summary: str
    source: str
    axis: str


def clean_text(raw: str | None, limit: int = SUMMARY_CHARS) -> str:
    """Strip HTML tags and entities, collapse whitespace, truncate."""
    if not raw:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_date(raw: str | None) -> datetime | None:
    """Parse an RFC 822 (RSS) or ISO 8601 (Atom) date into an aware UTC datetime."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_feed(body: str, source: str, axis: str) -> list[Item]:
    """Parse an RSS 2.0 or Atom document into items."""
    root = ET.fromstring(body)
    items: list[Item] = []
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry"):
            link_el = entry.find(f"{ATOM}link[@rel='alternate']")
            if link_el is None:
                link_el = entry.find(f"{ATOM}link")
            link = link_el.get("href", "") if link_el is not None else ""
            items.append(
                Item(
                    uid=entry.findtext(f"{ATOM}id") or link,
                    title=clean_text(entry.findtext(f"{ATOM}title"), 200),
                    link=link,
                    published=parse_date(entry.findtext(f"{ATOM}updated") or entry.findtext(f"{ATOM}published")),
                    summary=clean_text(entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content")),
                    source=source,
                    axis=axis,
                )
            )
        return items
    for entry in root.iter("item"):
        link = (entry.findtext("link") or "").strip()
        items.append(
            Item(
                uid=(entry.findtext("guid") or link).strip(),
                title=clean_text(entry.findtext("title"), 200),
                link=link,
                published=parse_date(entry.findtext("pubDate")),
                summary=clean_text(entry.findtext("description")),
                source=source,
                axis=axis,
            )
        )
    return items


def parse_hn(payload: dict[str, Any], axis: str) -> list[Item]:
    """Turn a Hacker News Algolia search response into items."""
    items: list[Item] = []
    for hit in payload.get("hits", []):
        object_id = str(hit.get("objectID", ""))
        discussion = f"https://news.ycombinator.com/item?id={object_id}"
        items.append(
            Item(
                uid=f"hn:{object_id}",
                title=clean_text(hit.get("title"), 200),
                link=hit.get("url") or discussion,
                published=parse_date(hit.get("created_at")),
                summary=f"{hit.get('points', 0)} points, {hit.get('num_comments', 0)} commentaires — {discussion}",
                source="Hacker News",
                axis=axis,
            )
        )
    return items


def matches_keywords(title: str, keywords: list[str]) -> bool:
    """Whole-word, case-insensitive match ("ai" must not match "said")."""
    if not keywords:
        return True
    return any(re.search(rf"\b{re.escape(k)}\b", title, re.IGNORECASE) for k in keywords)


def load_sources() -> dict[str, Any]:
    """Merge the Ansible-owned base list with the agent-owned local overrides.

    `sources.local.yaml` may add `sources:` entries and list base source
    names under `disabled:`.
    """
    config: dict[str, Any] = yaml.safe_load(BASE_SOURCES.read_text(encoding="utf-8")) or {}
    if LOCAL_SOURCES.exists():
        local: dict[str, Any] = yaml.safe_load(LOCAL_SOURCES.read_text(encoding="utf-8")) or {}
        disabled = set(local.get("disabled", []))
        config["sources"] = [s for s in config.get("sources", []) if s["name"] not in disabled] + list(
            local.get("sources", [])
        )
    return config


def is_prerelease(item: Item) -> bool:
    """Tell a GitHub prerelease from its title or tag URL."""
    return bool(PRERELEASE.search(item.title) or PRERELEASE.search(item.link.rsplit("/", 1)[-1]))


def feed_url(source: dict[str, Any]) -> str:
    """Resolve the URL of a feed source (`github` kind is a shortcut)."""
    if source.get("kind") == "github":
        return f"https://github.com/{source['repo']}/releases.atom"
    return str(source["url"])


def fetch_all(config: dict[str, Any], since: datetime) -> tuple[list[Item], list[str]]:
    """Fetch every source; failures are reported, never raised."""
    items: list[Item] = []
    errors: list[str] = []
    # No brotli: the container's decoder intermittently fails on some CDNs
    # ("can_accept_more_data() is False" on kubernetes.io).
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers=headers) as client:
        for source in config.get("sources", []):
            name = source["name"]
            try:
                response = client.get(feed_url(source))
                response.raise_for_status()
                parsed = parse_feed(response.text, name, source.get("axis", "divers"))
            except (httpx.HTTPError, ET.ParseError, KeyError) as exc:
                errors.append(f"{name} : {type(exc).__name__} {exc}".strip())
                continue
            recent = [i for i in parsed if i.published is None or i.published >= since]
            if source.get("kind") == "github" and not source.get("prereleases", False):
                recent = [i for i in recent if not is_prerelease(i)]
            items.extend(recent[: source.get("max", MAX_ITEMS_PER_SOURCE)])

        hn = config.get("hackernews")
        if hn:
            try:
                response = client.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={
                        "tags": "story",
                        "numericFilters": f"created_at_i>{int(since.timestamp())},points>={hn.get('min_points', 150)}",
                        "hitsPerPage": 100,
                    },
                )
                response.raise_for_status()
                stories = [
                    i
                    for i in parse_hn(response.json(), hn.get("axis", "divers"))
                    if matches_keywords(i.title, hn.get("keywords", []))
                ]
                items.extend(stories[: hn.get("max", 10)])
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"Hacker News : {type(exc).__name__} {exc}".strip())
    return items, errors


def read_json(path: Path, default: Any) -> Any:
    """Read a JSON file, falling back to `default` when missing or corrupt."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def remember(items: list[Item], now: datetime) -> list[Item]:
    """Drop already-reported items, record the new ones, prune old state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    seen_path = STATE_DIR / "seen.json"
    seen: dict[str, str] = read_json(seen_path, {})
    cutoff = now - SEEN_RETENTION
    seen = {uid: ts for uid, ts in seen.items() if datetime.fromisoformat(ts) >= cutoff}

    fresh: list[Item] = []
    for item in items:
        if item.uid in seen:
            continue
        seen[item.uid] = now.isoformat()
        fresh.append(item)
    seen_path.write_text(json.dumps(seen), encoding="utf-8")

    history_path = STATE_DIR / "history.jsonl"
    history_cutoff = now - HISTORY_RETENTION
    kept = [
        line
        for line in (history_path.read_text(encoding="utf-8").splitlines() if history_path.exists() else [])
        if line and datetime.fromisoformat(json.loads(line)["collected"]) >= history_cutoff
    ]
    for item in fresh:
        record = asdict(item) | {
            "published": item.published.isoformat() if item.published else None,
            "collected": now.isoformat(),
        }
        kept.append(json.dumps(record, ensure_ascii=False))
    history_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return fresh


def load_history(since: datetime) -> list[Item]:
    """Return the items collected by daily runs since `since`."""
    path = STATE_DIR / "history.jsonl"
    if not path.exists():
        return []
    items: list[Item] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        if datetime.fromisoformat(record.pop("collected")) < since:
            continue
        record["published"] = parse_date(record["published"])
        items.append(Item(**record))
    return items


def render(items: list[Item], errors: list[str], title: str) -> str:
    """Render items grouped by axis as compact text for the agent prompt."""
    lines = [f"# {title} — {len(items)} élément(s)"]
    if not items:
        lines.append("Aucun nouvel élément.")
    by_axis: dict[str, list[Item]] = {}
    for item in items[:MAX_ITEMS_TOTAL]:
        by_axis.setdefault(item.axis, []).append(item)
    for axis, group in by_axis.items():
        lines.append(f"\n## {axis}")
        for item in group:
            date = item.published.strftime("%Y-%m-%d") if item.published else "date inconnue"
            lines.append(f"- [{item.source}] {item.title} — {date} — {item.link}")
            if item.summary:
                lines.append(f"  {item.summary}")
    if errors:
        lines.append("\n## Sources en erreur")
        lines.extend(f"- {e}" for e in errors)
    return "\n".join(lines)


def run_daily(window: timedelta = timedelta(hours=96)) -> str:
    """Collect new items since the last runs (window caps a long pause)."""
    now = datetime.now(UTC)
    items, errors = fetch_all(load_sources(), now - window)
    fresh = remember(items, now)
    return render(fresh, errors, f"Collecte du {now:%Y-%m-%d}")


def run_weekly(window: timedelta = timedelta(days=7)) -> str:
    """Replay the past week's daily collections for the weekly synthesis."""
    now = datetime.now(UTC)
    return render(load_history(now - window), [], f"Semaine du {now - window:%Y-%m-%d} au {now:%Y-%m-%d}")


if __name__ == "__main__":
    sys.stdout.write(run_daily() + "\n")
