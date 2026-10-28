"""그래프 전체가 함께 쓰는 상태와 데이터 모양."""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


class Article(BaseModel):
    """collect가 모아 온 기사 한 건."""

    id: str
    title: str
    url: str
    source: str
    published: str  # ISO 8601 (UTC)
    summary: str = ""  # 피드에 실려 온 짧은 설명
    body: str = ""  # trafilatura로 뽑은 본문 (select 이후에만 채움)


class Score(BaseModel):
    """select 단계에서 LLM이 매기는 점수. 항목별 0~5."""

    article_id: str
    dev_impact: int = Field(ge=0, le=5, description="개발팀 업무에 미치는 영향")
    novelty: int = Field(ge=0, le=5, description="새로운 발표·출시·연구인지")
    credibility: int = Field(ge=0, le=5, description="1차 출처·근거가 분명한지")
    reason: str = Field(description="한 줄 이유 (한국어)")

    @property
    def total(self) -> int:
        # 개발팀 영향에 가중치 2배
        return self.dev_impact * 2 + self.novelty + self.credibility


class Summary(BaseModel):
    """report가 채우는 세 칸 요약."""

    what: str = Field(description="무슨 일인가: 사실만 1~2문장")
    why: str = Field(description="왜 중요한가: 개발팀 관점 1~2문장")
    action: str = Field(description="우리 팀은 무엇을 하면 되나: 1문장")


class Verdict(BaseModel):
    """verify가 원문과 대조한 결과."""

    supported: bool = Field(description="요약의 모든 주장이 원문에 근거가 있는가")
    problems: list[str] = Field(default_factory=list, description="원문에 없는 주장 목록")


class Item(BaseModel):
    """발행 단위: 기사 + 요약 + 검수 결과."""

    article: Article
    summary: Summary
    verdict: Verdict | None = None


class NewsState(TypedDict, total=False):
    articles: list[Article]  # collect 결과 (~100건)
    selected: list[Article]  # select 결과 (5건 + 예비, 우선순위 순)
    cursor: int  # selected 중 report가 다음에 볼 위치
    items: list[Item]  # 이번 회차 report 결과 (verify 대기)
    verified: Annotated[list[Item], operator.add]  # verify 통과분 (누적)
    rejected: Annotated[list[Item], operator.add]  # verify 탈락분 (누적, 기록용)
    published: bool
    errors: Annotated[list[str], operator.add]
