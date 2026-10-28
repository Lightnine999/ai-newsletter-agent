"""select: 관문을 통과한 기사(~100건)에서 5건 + 예비를 고른다.

구조 (깔때기 3단):
  1) 규칙 예선  - 소스별 최신 N건, 전체 상한으로 LLM 비용을 묶는다
  2) LLM 채점   - 배치로 dev_impact·novelty·credibility 점수 (구조화 출력)
  3) 소식 묶기  - 상위 후보를 한 번에 보여 주고 같은 소식끼리 묶게 한다
                  (매체가 달라 제목이 다른 같은 뉴스를 규칙으로는 못 잡아서)
  4) 규칙 결선  - 총점 순 + 소스당 최대 2건 + 소식당 1건
LLM은 '점수'와 '묶음'만 내고, 최종 선택은 코드가 한다 → 결과를 재현·검증하기 쉽다.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from pydantic import BaseModel

from ..llm import LLM
from ..state import Article, NewsState, Score

log = logging.getLogger(__name__)

PER_SOURCE_LIMIT = 10
PRESELECT_LIMIT = 60
BATCH_SIZE = 20
PICK = 5
RESERVE = 3
MAX_PER_SOURCE = 2
SHORTLIST = 20  # 소식 묶기에 보여 줄 상위 후보 수

SYSTEM = """너는 소프트웨어 개발팀을 위한 AI 뉴스 편집자야.
기사마다 0~5점으로 채점해:
- dev_impact: 개발팀이 쓰는 도구·API·모델·비용·보안에 직접 영향이 있는가
- novelty: 새 출시·발표·연구 결과인가 (의견·재탕·목록 기사는 낮게)
- credibility: 1차 출처이거나 근거가 분명한가 (소문·추측은 낮게)
reason은 한국어 한 줄. 주어진 article_id를 그대로 써."""


STORY_SYSTEM = """아래 기사 목록에서 '같은 사건·발표'를 다룬 기사끼리 묶어.
매체나 제목 표현이 달라도 같은 제품 출시·발표·연구를 다루면 같은 묶음이야.
같은 회사의 서로 다른 발표는 다른 묶음이야.
기사가 2건 이상인 묶음만 적고, 주어진 article_id를 그대로 써."""


class ScoreList(BaseModel):
    scores: list[Score]


class StoryGroup(BaseModel):
    story: str
    article_ids: list[str]


class StoryGroups(BaseModel):
    groups: list[StoryGroup]


def preselect(articles: list[Article]) -> list[Article]:
    by_source: dict[str, list[Article]] = defaultdict(list)
    for a in sorted(articles, key=lambda a: a.published, reverse=True):
        if len(by_source[a.source]) < PER_SOURCE_LIMIT:
            by_source[a.source].append(a)
    pool = sorted((a for group in by_source.values() for a in group), key=lambda a: a.published, reverse=True)
    return pool[:PRESELECT_LIMIT]


def score_all(llm: LLM, articles: list[Article]) -> dict[str, Score]:
    scores: dict[str, Score] = {}
    valid_ids = {a.id for a in articles}
    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        listing = "\n".join(f"- article_id={a.id} | [{a.source}] {a.title} | {a.summary[:200]}" for a in batch)
        result = llm.parse(SYSTEM, listing, ScoreList)
        # 검증: 없는 id를 지어내면 버린다
        scores.update({s.article_id: s for s in result.scores if s.article_id in valid_ids})
    missing = valid_ids - scores.keys()
    if missing:
        log.warning("select: 점수를 못 받은 기사 %d건 (0점 처리)", len(missing))
    return scores


def rank(articles: list[Article], scores: dict[str, Score]) -> list[Article]:
    return sorted(articles, key=lambda a: (scores[a.id].total if a.id in scores else -1, a.published), reverse=True)


def cluster_stories(llm: LLM, articles: list[Article]) -> dict[str, str]:
    """article id → 소식 키. 묶이지 않은 기사는 자기 id가 키다."""
    listing = "\n".join(f"- article_id={a.id} | [{a.source}] {a.title}" for a in articles)
    result = llm.parse(STORY_SYSTEM, listing, StoryGroups)
    valid_ids = {a.id for a in articles}
    story_of = {a.id: a.id for a in articles}
    for i, group in enumerate(result.groups):
        members = [x for x in group.article_ids if x in valid_ids]  # 지어낸 id는 버린다
        if len(members) > 1:
            story_of.update({x: f"story-{i}" for x in members})
            log.info("select 같은 소식 묶음 '%s': %d건", group.story, len(members))
    return story_of


def pick(articles: list[Article], scores: dict[str, Score], n: int, story_of: dict[str, str] | None = None) -> list[Article]:
    story_of = story_of or {}
    per_source: dict[str, int] = defaultdict(int)
    used_stories: set[str] = set()
    chosen: list[Article] = []
    for a in rank(articles, scores):
        story = story_of.get(a.id, a.id)
        if a.id not in scores or per_source[a.source] >= MAX_PER_SOURCE or story in used_stories:
            continue
        chosen.append(a)
        per_source[a.source] += 1
        used_stories.add(story)
        if len(chosen) == n:
            break
    return chosen


def select(state: NewsState, llm: LLM) -> NewsState:
    pool = preselect(state["articles"])
    scores = score_all(llm, pool)
    # 소스 제한을 건 채로 후보를 잘라야 한 소스가 후보를 독차지하지 않는다
    shortlist = pick(pool, scores, SHORTLIST)
    chosen = pick(shortlist, scores, PICK + RESERVE, cluster_stories(llm, shortlist))
    for no, a in enumerate(chosen, 1):
        s = scores[a.id]
        log.info("select #%d %2d점 [%s] %s — %s", no, s.total, a.source, a.title, s.reason)
    if len(chosen) < PICK:
        raise RuntimeError(f"select: {PICK}건을 채우지 못했어요 ({len(chosen)}건)")
    return {"selected": chosen, "cursor": 0}
