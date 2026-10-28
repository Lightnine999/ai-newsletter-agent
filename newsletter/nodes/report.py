"""report: 원문 본문을 가져와 세 칸(what / why / action)으로 요약한다."""
from __future__ import annotations

import logging
from typing import Callable

import requests
import trafilatura

from ..llm import LLM
from ..state import Article, Item, NewsState, Summary
from .collect import HEADERS, TIMEOUT
from .select import PICK

log = logging.getLogger(__name__)
MAX_BODY_CHARS = 8000

SYSTEM = """너는 개발팀용 AI 뉴스레터 기자야. 아래 원문만 근거로 한국어로 세 칸을 채워.
- what: 무슨 일인가. 원문에 있는 사실만 1~2문장. 숫자·이름은 원문 그대로.
- why: 개발팀에게 왜 중요한가 1~2문장.
- action: 우리 팀이 해볼 일 1문장 (예: 문서 확인, 가격 비교, 테스트).
원문에 없는 수치·날짜·인용을 만들지 마. 모르면 쓰지 마."""


def fetch_body(url: str) -> str:
    res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    return trafilatura.extract(res.text, include_comments=False) or ""


def summarize(llm: LLM, article: Article) -> Summary:
    prompt = f"제목: {article.title}\n출처: {article.source}\n\n원문:\n{article.body[:MAX_BODY_CHARS]}"
    return llm.parse(SYSTEM, prompt, Summary)


def report(state: NewsState, llm: LLM, fetch: Callable[[str], str] = fetch_body) -> NewsState:
    """아직 모자란 만큼만 다음 후보를 요약한다 (verify에서 떨어지면 다시 돌아옴)."""
    need = PICK - len(state.get("verified", []))
    selected, cursor = state["selected"], state.get("cursor", 0)
    items: list[Item] = []
    errors: list[str] = []
    while len(items) < need and cursor < len(selected):
        article = selected[cursor]
        cursor += 1
        try:
            body = fetch(article.url)
        except Exception as e:  # noqa: BLE001
            errors.append(f"report:본문 실패 {article.url}: {type(e).__name__}")
            body = ""
        # 본문을 못 뽑으면 피드 설명으로 대신하고, 판단은 verify에 맡긴다
        article = article.model_copy(update={"body": body or article.summary})
        if len(article.body) < 100:
            errors.append(f"report:본문 부족으로 건너뜀 {article.url}")
            continue
        items.append(Item(article=article, summary=summarize(llm, article)))
        log.info("report %s", article.title)
    return {"items": items, "cursor": cursor, "errors": errors}
