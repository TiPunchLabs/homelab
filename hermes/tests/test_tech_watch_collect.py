"""Tests for the `tech-watch` profile collector (hermes_agent role files).

Run from the repo root:
    uv run pytest hermes/tests -q
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "ansible/roles/hermes_agent/files/profiles/tech-watch/scripts"
sys.path.insert(0, str(SCRIPTS))

import tech_watch_collect as vc

NOW = datetime(2026, 10, 9, 11, 0, tzinfo=UTC)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Blog</title>
<item><title>Fresh &amp; new</title><link>https://ex.org/a</link><guid>a</guid>
<pubDate>Thu, 08 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Hello   &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Old</title><link>https://ex.org/b</link><guid>b</guid>
<pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Releases</title>
<entry><id>tag:github.com,2008:Repository/1/v1.2.0</id><title>v1.2.0</title>
<updated>2026-10-08T12:00:00Z</updated>
<link rel="alternate" type="text/html" href="https://github.com/o/r/releases/tag/v1.2.0"/>
<content type="html">&lt;h2&gt;Breaking&lt;/h2&gt; changes</content></entry>
</feed>"""

HN = {
    "hits": [
        {
            "objectID": "1",
            "title": "New local LLM beats GPT",
            "url": "https://ex.org/llm",
            "points": 300,
            "num_comments": 120,
            "created_at": "2026-10-08T09:00:00Z",
        },
        {
            "objectID": "2",
            "title": "He said goodbye",
            "url": None,
            "points": 500,
            "num_comments": 10,
            "created_at": "2026-10-08T09:00:00Z",
        },
    ]
}


@pytest.fixture
def profile_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every state path of the module at a throwaway profile home."""
    state = tmp_path / "tech-watch"
    monkeypatch.setattr(vc, "STATE_DIR", state)
    monkeypatch.setattr(vc, "LOCAL_SOURCES", state / "sources.local.yaml")
    return tmp_path


def make_item(uid: str, axis: str = "ia") -> vc.Item:
    """Build a minimal item."""
    return vc.Item(
        uid=uid, title=f"T {uid}", link=f"https://ex.org/{uid}", published=NOW, summary="", source="S", axis=axis
    )


def test_clean_text_strips_html_and_truncates() -> None:
    assert vc.clean_text("<p>Hello &amp;   <b>world</b></p>") == "Hello & world"
    assert vc.clean_text("x" * 10, limit=5) == "xxxx…"
    assert vc.clean_text(None) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Thu, 08 Oct 2026 10:00:00 GMT", datetime(2026, 10, 8, 10, tzinfo=UTC)),
        ("2026-10-08T12:00:00Z", datetime(2026, 10, 8, 12, tzinfo=UTC)),
        ("2026-10-08T12:00:00", datetime(2026, 10, 8, 12, tzinfo=UTC)),
        ("not a date", None),
        (None, None),
    ],
)
def test_parse_date(raw: str | None, expected: datetime | None) -> None:
    assert vc.parse_date(raw) == expected


def test_parse_rss() -> None:
    items = vc.parse_feed(RSS, "Blog", "python")
    assert [i.uid for i in items] == ["a", "b"]
    assert items[0].title == "Fresh & new"
    assert items[0].summary == "Hello world"
    assert items[0].axis == "python"


def test_parse_atom_prefers_alternate_link() -> None:
    (item,) = vc.parse_feed(ATOM, "Repo", "devops")
    assert item.link == "https://github.com/o/r/releases/tag/v1.2.0"
    assert item.published == datetime(2026, 10, 8, 12, tzinfo=UTC)
    assert item.summary == "Breaking changes"


def test_parse_hn_falls_back_to_discussion_link() -> None:
    items = vc.parse_hn(HN, "ia")
    assert items[1].link == "https://news.ycombinator.com/item?id=2"
    assert items[0].uid == "hn:1"


def test_keywords_match_whole_words_only() -> None:
    assert vc.matches_keywords("New local LLM beats GPT", ["llm"])
    assert not vc.matches_keywords("He said goodbye", ["ai"])
    assert vc.matches_keywords("Anything", [])


def test_local_sources_add_and_disable(profile_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = profile_home / "base.yaml"
    base.write_text("sources:\n  - {name: A, url: 'https://a'}\n  - {name: B, url: 'https://b'}\n")
    monkeypatch.setattr(vc, "BASE_SOURCES", base)
    vc.LOCAL_SOURCES.parent.mkdir(parents=True)
    vc.LOCAL_SOURCES.write_text("disabled: [A]\nsources:\n  - {name: C, url: 'https://c'}\n")

    assert [s["name"] for s in vc.load_sources()["sources"]] == ["B", "C"]


def test_feed_url_github_shortcut() -> None:
    assert vc.feed_url({"kind": "github", "repo": "o/r"}) == "https://github.com/o/r/releases.atom"
    assert vc.feed_url({"url": "https://x/feed"}) == "https://x/feed"


def test_remember_reports_each_item_once(profile_home: Path) -> None:
    assert [i.uid for i in vc.remember([make_item("a"), make_item("b")], NOW)] == ["a", "b"]
    assert [i.uid for i in vc.remember([make_item("a"), make_item("c")], NOW)] == ["c"]


def test_remember_forgets_after_retention(profile_home: Path) -> None:
    vc.remember([make_item("a")], NOW - vc.SEEN_RETENTION - timedelta(days=1))
    assert [i.uid for i in vc.remember([make_item("a")], NOW)] == ["a"]


def test_history_feeds_weekly_window(profile_home: Path) -> None:
    vc.remember([make_item("old")], NOW - timedelta(days=10))
    vc.remember([make_item("new")], NOW - timedelta(days=2))

    assert [i.uid for i in vc.load_history(NOW - timedelta(days=7))] == ["new"]


def test_render_groups_by_axis_and_lists_errors() -> None:
    text = vc.render([make_item("a", "ia"), make_item("b", "devops")], ["X : boom"], "Titre")
    assert text.startswith("# Titre — 2 élément(s)")
    assert "## ia" in text and "## devops" in text
    assert "## Sources en erreur\n- X : boom" in text


def test_render_empty() -> None:
    assert "Aucun nouvel élément." in vc.render([], [], "Titre")


def test_fetch_all_survives_failing_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ok.example":
            return httpx.Response(200, text=RSS)
        if request.url.host == "hn.algolia.com":
            return httpx.Response(200, json=HN)
        return httpx.Response(503)

    real_client = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(vc.httpx, "Client", client)
    config = {
        "sources": [
            {"name": "Good", "url": "https://ok.example/feed", "axis": "ia"},
            {"name": "Down", "url": "https://down.example/feed", "axis": "ia"},
        ],
        "hackernews": {"keywords": ["llm"], "axis": "ia"},
    }

    items, errors = vc.fetch_all(config, since=NOW - timedelta(days=4))

    assert [i.uid for i in items] == ["a", "hn:1"]  # "b" is too old, "said" filtered
    assert len(errors) == 1 and errors[0].startswith("Down : HTTPStatusError")


@pytest.mark.parametrize(
    ("title", "tag", "expected"),
    [
        ("v1.2.0", "v1.2.0", False),
        ("rc.38-v0.21.5", "rc.38-v0.21.5", True),
        ("Hermes Agent canary", "v0.21.5%2Bcanary.20261008T070449Z", True),
        ("v0.40.2-rc0: server fix", "v0.40.2-rc0", True),
        ("b6789", "b6789", False),
        ("Source code", "v2.0.0-beta.1", True),
    ],
)
def test_is_prerelease(title: str, tag: str, expected: bool) -> None:
    item = vc.Item(
        uid=tag,
        title=title,
        link=f"https://github.com/o/r/releases/tag/{tag}",
        published=NOW,
        summary="",
        source="S",
        axis="ia",
    )
    assert vc.is_prerelease(item) is expected


def test_fetch_all_drops_github_prereleases_and_caps_per_source(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = "".join(
        f"<entry><id>{tag}</id><title>{tag}</title><updated>2026-10-08T12:00:00Z</updated>"
        f'<link rel="alternate" href="https://github.com/o/r/releases/tag/{tag}"/></entry>'
        for tag in ["v3.0.0", "v3.0.0-rc1", "v2.9.0", "v2.8.0"]
    )
    feed = f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'
    real_client = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=feed)), **kwargs)

    monkeypatch.setattr(vc.httpx, "Client", client)
    config = {"sources": [{"name": "R", "kind": "github", "repo": "o/r", "axis": "devops", "max": 2}]}

    items, errors = vc.fetch_all(config, since=NOW - timedelta(days=4))

    assert [i.title for i in items] == ["v3.0.0", "v2.9.0"]
    assert errors == []
