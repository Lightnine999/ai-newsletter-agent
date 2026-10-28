"""collect: 여러 길에서 기사를 모으고 관문으로 거른다."""
from __future__ import annotations

import calendar
import logging
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

from ..sources import HN_QUERY_URL, RSS_FEEDS, article_id, gate
from ..state import Article, NewsState

log = logging.getLogger(__name__)
TIMEOUT = 15
HEADERS = {"User-Agent": "ai-newsletter-agent/0.1 (+https://github.com/Lightnine999/ai-newsletter-agent)"}
HN_MIN_POINTS = 50


def fetch_rss(name: str, url: str) -> list[Article]:
    res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    feed = feedparser.parse(res.content)
    return [a for a in (_from_entry(name, e) for e in feed.entries) if a]


def _from_entry(source: str, entry) -> Article | None:
    link = entry.get("link")
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not link or not stamp:
        return None
    # feedparser의 *_parsed는 UTC 기준 struct_time
    published = datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc)
    return Article(
        id=article_id(link),
        title=entry.get("title", "").strip(),
        url=link,
        source=source,
        published=published.isoformat(),
        summary=_strip_html(entry.get("summary", ""))[:500],
    )


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


def fetch_hn() -> list[Article]:
    since = int(time.time()) - 36 * 3600
    params = {
        "query": "AI",
        "tags": "story",
        "numericFilters": f"created_at_i>{since},points>{HN_MIN_POINTS}",
        "hitsPerPage": 50,
    }
    res = requests.get(HN_QUERY_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    return [
        Article(
            id=article_id(h["url"]),
            title=h.get("title") or "",
            url=h["url"],
            source="Hacker News",
            published=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc).isoformat(),
        )
        for h in res.json().get("hits", [])
        if h.get("url")
    ]


def collect(state: NewsState, fetchers: dict | None = None) -> NewsState:
    """소스 하나가 죽어도 전체는 계속 간다. 실패는 errors에 남긴다."""
    fetchers = fetchers or {
        **{name: (lambda n=name, u=url: fetch_rss(n, u)) for name, url in RSS_FEEDS.items()},
        "Hacker News": fetch_hn,
    }
    raw: list[Article] = []
    errors: list[str] = []
    for name, fetch in fetchers.items():
        try:
            got = fetch()
            log.info("collect %-16s %3d건", name, len(got))
            raw.extend(got)
        except Exception as e:  # noqa: BLE001 - 소스별 실패는 격리
            errors.append(f"collect:{name}: {type(e).__name__}: {e}")
            log.warning("collect %s 실패: %s", name, e)

    passed, dropped = gate(raw)
    log.info("collect 원본 %d건 → 관문 통과 %d건 (탈락 %s)", len(raw), len(passed), dropped)
    if len(passed) < 5:
        raise RuntimeError(f"관문 통과 기사가 {len(passed)}건뿐이에요. 소스 상태를 확인하세요: {errors}")
    return {"articles": passed, "errors": errors}
