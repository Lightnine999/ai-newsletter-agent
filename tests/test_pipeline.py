"""네트워크·API 키 없이 돌아가는 테스트. LLM과 소스는 가짜로 바꿔 끼운다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from newsletter.graph import build_graph
from newsletter.nodes.select import MAX_PER_SOURCE, pick, preselect
from newsletter.nodes.verify import unsupported_numbers
from newsletter.sources import article_id, gate
from newsletter.state import Article, Item, Score, Summary, Verdict

NOW = datetime(2026, 10, 28, 22, 0, tzinfo=timezone.utc)
BODY = "OpenAI released a new model with 128 tokens context and 40 percent lower price. " * 5


def make(i: int, source: str = "S", hours_ago: int = 1, title: str | None = None, url: str | None = None) -> Article:
    url = url or f"https://example.com/{source}/{i}"
    return Article(
        id=article_id(url),
        title=title or f"New AI model release number {i} from {source}",
        url=url,
        source=source,
        published=(NOW - timedelta(hours=hours_ago)).isoformat(),
        summary="An LLM update.",
    )


class FakeLLM:
    """요청 스키마에 따라 정해진 답을 돌려준다. bad_ids의 요약은 원문에 없는 숫자를 넣는다."""

    def __init__(self, bad_ids: set[str] = frozenset()):
        self.bad_ids = bad_ids
        self.calls: dict[str, int] = {}

    def parse(self, system, user, schema):
        self.calls[schema.__name__] = self.calls.get(schema.__name__, 0) + 1
        if schema.__name__ == "ScoreList":
            ids = [line.split("article_id=")[1].split(" ")[0] for line in user.splitlines()]
            # 뒤쪽 번호일수록 높은 점수, 그리고 없는 id 하나를 지어낸다
            scores = [Score(article_id=x, dev_impact=min(5, n), novelty=3, credibility=3, reason="r") for n, x in enumerate(ids)]
            return schema(scores=scores + [Score(article_id="ghost", dev_impact=5, novelty=5, credibility=5, reason="r")])
        if schema is Summary:
            bad = any(b in user for b in self.bad_ids)
            return Summary(what="가격이 999% 내렸다." if bad else "128 토큰 문맥, 40% 저렴.", why="비용 절감.", action="가격표 확인.")
        if schema is Verdict:
            return Verdict(supported=True)
        raise AssertionError(schema)


# ---------- 관문 ----------

def test_gate_drops_each_kind():
    articles = [
        make(1),
        make(2, url="https://prnewswire.com/x"),  # blocked
        make(3, hours_ago=100),  # stale
        make(4, title="AI news"),  # short
        make(5, title="Best pizza recipes in town this week").model_copy(update={"summary": ""}),  # off_topic
        make(6, title=make(1).title, url="https://other.com/1"),  # 같은 제목
    ]
    passed, dropped = gate(articles, now=NOW)
    assert [a.title for a in passed] == [make(1).title]
    assert dropped == {"blocked": 1, "stale": 1, "short": 1, "off_topic": 1, "duplicate": 1}


# ---------- 선택 ----------

def test_preselect_caps_each_source():
    pool = preselect([make(i, "Big") for i in range(30)] + [make(i, "Small") for i in range(3)])
    assert sum(a.source == "Big" for a in pool) == 10
    assert sum(a.source == "Small" for a in pool) == 3


def test_pick_keeps_source_diversity_and_order():
    arts = [make(i, src) for src in "AB" for i in range(5)]
    scores = {a.id: Score(article_id=a.id, dev_impact=5 if a.source == "A" else 1, novelty=1, credibility=1, reason="") for a in arts}
    chosen = pick(arts, scores, 4)
    assert [a.source for a in chosen] == ["A", "A", "B", "B"]
    assert max(sum(a.source == s for a in chosen) for s in "AB") <= MAX_PER_SOURCE


# ---------- 검수 ----------

def test_unsupported_numbers_flags_invented_figures():
    article = make(1).model_copy(update={"body": BODY})
    ok = Item(article=article, summary=Summary(what="128 토큰, 40% 저렴", why="", action=""))
    bad = Item(article=article, summary=Summary(what="999% 저렴", why="", action=""))
    assert unsupported_numbers(ok) == []
    assert unsupported_numbers(bad) == ["999"]


# ---------- 그래프 전체 ----------

def run(llm, monkeypatch, tmp_path, n_sources=5):
    monkeypatch.setattr("newsletter.sources.datetime", _FrozenDatetime)
    monkeypatch.setattr("newsletter.nodes.publish.OUTPUT_DIR", tmp_path)
    sent = []
    fetchers = {f"src{s}": (lambda s=s: [make(i, f"src{s}") for i in range(20)]) for s in range(n_sources)}
    graph = build_graph(llm, fetchers=fetchers, fetch=lambda url: BODY + url, send=sent.append)
    return graph.invoke({}), sent


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def test_graph_publishes_five(monkeypatch, tmp_path):
    final, sent = run(FakeLLM(), monkeypatch, tmp_path)
    assert len(final["verified"]) == 5
    assert len(sent) == 1 and len(sent[0]["embeds"]) == 5
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_graph_replaces_rejected_with_reserve(monkeypatch, tmp_path):
    # 첫 후보 2건의 요약에 지어낸 숫자를 넣는다 → 예비로 교체되어야 함
    probe, _ = run(FakeLLM(), monkeypatch, tmp_path)
    first_two = {it.article.url for it in probe["verified"][:2]}
    final, sent = run(FakeLLM(bad_ids=first_two), monkeypatch, tmp_path)
    assert len(final["rejected"]) == 2
    assert len(final["verified"]) == 5
    assert not first_two & {it.article.url for it in final["verified"]}


def test_collect_survives_one_dead_source(monkeypatch, tmp_path):
    monkeypatch.setattr("newsletter.sources.datetime", _FrozenDatetime)
    monkeypatch.setattr("newsletter.nodes.publish.OUTPUT_DIR", tmp_path)

    def dead():
        raise ConnectionError("down")

    fetchers = {"ok": lambda: [make(i, f"s{i % 4}") for i in range(20)], "dead": dead}
    final = build_graph(FakeLLM(), fetchers=fetchers, fetch=lambda u: BODY, send=lambda p: None).invoke({})
    assert any("collect:dead" in e for e in final["errors"])
    assert len(final["verified"]) == 5


def test_collect_fails_loudly_when_too_few(monkeypatch):
    monkeypatch.setattr("newsletter.sources.datetime", _FrozenDatetime)
    graph = build_graph(FakeLLM(), fetchers={"one": lambda: [make(1)]}, fetch=lambda u: BODY, send=lambda p: None)
    with pytest.raises(RuntimeError, match="관문 통과"):
        graph.invoke({})
