"""select: 관문을 통과한 기사(~100건)에서 5건 + 예비를 고른다.

구조 (깔때기 3단):
  1) 규칙 예선  - 소스별 최신 N건, 전체 상한으로 LLM 비용을 묶는다
  2) LLM 채점   - 배치로 dev_impact·novelty·credibility 점수 (구조화 출력)
  3) 규칙 결선  - 총점 순 + 소스당 최대 2건(다양성)
LLM은 '점수'만 내고, 최종 선택은 코드가 한다 → 결과를 재현·검증하기 쉽다.
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

SYSTEM = """너는 소프트웨어 개발팀을 위한 AI 뉴스 편집자야.
기사마다 0~5점으로 채점해:
- dev_impact: 개발팀이 쓰는 도구·API·모델·비용·보안에 직접 영향이 있는가
- novelty: 새 출시·발표·연구 결과인가 (의견·재탕·목록 기사는 낮게)
- credibility: 1차 출처이거나 근거가 분명한가 (소문·추측은 낮게)
reason은 한국어 한 줄. 주어진 article_id를 그대로 써."""


class ScoreList(BaseModel):
    scores: list[Score]


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


def pick(articles: list[Article], scores: dict[str, Score], n: int) -> list[Article]:
    ranked = sorted(articles, key=lambda a: (scores[a.id].total if a.id in scores else -1, a.published), reverse=True)
    per_source: dict[str, int] = defaultdict(int)
    chosen: list[Article] = []
    for a in ranked:
        if a.id not in scores or per_source[a.source] >= MAX_PER_SOURCE:
            continue
        chosen.append(a)
        per_source[a.source] += 1
        if len(chosen) == n:
            break
    return chosen


def select(state: NewsState, llm: LLM) -> NewsState:
    pool = preselect(state["articles"])
    scores = score_all(llm, pool)
    chosen = pick(pool, scores, PICK + RESERVE)
    for rank, a in enumerate(chosen, 1):
        s = scores[a.id]
        log.info("select #%d %2d점 [%s] %s — %s", rank, s.total, a.source, a.title, s.reason)
    if len(chosen) < PICK:
        raise RuntimeError(f"select: {PICK}건을 채우지 못했어요 ({len(chosen)}건)")
    return {"selected": chosen, "cursor": 0}
