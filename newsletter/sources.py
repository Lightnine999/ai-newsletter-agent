"""자료를 가져오는 길(소스)과, 들어온 기사를 거르는 관문.

다섯 길 비교는 docs/sources.md 참고. 여기서는 그중 RSS와 공개 API(HN)만 씀.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from .state import Article

# 관문 1: 허용 목록. 1차 출처(회사 블로그)와 검증된 매체만 둔다.
RSS_FEEDS: dict[str, str] = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "Google AI": "https://blog.google/technology/ai/rss/",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "MIT Tech Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "Simon Willison": "https://simonwillison.net/atom/everything/",
}
HN_QUERY_URL = "https://hn.algolia.com/api/v1/search_by_date"

# 관문 2: 차단 도메인 (광고·보도자료 재배포 등)
BLOCKED_DOMAINS = {"prnewswire.com", "globenewswire.com", "medium.com"}

AI_KEYWORDS = re.compile(
    r"\b(ai|llm|gpt|claude|gemini|llama|model|agent|openai|anthropic|"
    r"transformer|diffusion|rag|inference|fine-?tun\w*)\b",
    re.IGNORECASE,
)

MAX_AGE = timedelta(hours=36)  # 주말·지연 여유
MIN_TITLE_LEN = 15


def article_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", title.lower()).strip()


def gate(articles: list[Article], now: datetime | None = None) -> tuple[list[Article], dict[str, int]]:
    """관문을 통과한 기사와, 관문별로 몇 건이 떨어졌는지 반환."""
    now = now or datetime.now(timezone.utc)
    dropped = {"blocked": 0, "stale": 0, "short": 0, "off_topic": 0, "duplicate": 0}
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    passed: list[Article] = []

    for a in articles:
        reason = _reject_reason(a, now, seen_urls, seen_titles)
        if reason:
            dropped[reason] += 1
            continue
        seen_urls.add(a.url)
        seen_titles.add(normalize_title(a.title))
        passed.append(a)
    return passed, dropped


def _reject_reason(a: Article, now: datetime, seen_urls: set[str], seen_titles: set[str]) -> str | None:
    if domain_of(a.url) in BLOCKED_DOMAINS:
        return "blocked"
    try:
        published = datetime.fromisoformat(a.published)
    except ValueError:
        return "stale"
    if now - published > MAX_AGE:
        return "stale"
    if len(a.title) < MIN_TITLE_LEN:
        return "short"
    if not AI_KEYWORDS.search(f"{a.title} {a.summary}"):
        return "off_topic"
    if a.url in seen_urls or normalize_title(a.title) in seen_titles:
        return "duplicate"
    return None
