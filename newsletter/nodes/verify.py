"""verify: 요약을 원문과 대조해 검수한다.

두 겹으로 본다.
  1) 규칙 검사 - 요약에 나온 숫자가 원문에도 있는가 (환각된 수치를 싸게 잡는다)
  2) LLM 대조  - 요약의 주장 하나하나가 원문에 근거가 있는가
둘 다 통과해야 발행한다. 떨어지면 예비 후보로 다시 report 한다.
"""
from __future__ import annotations

import logging
import re

from ..llm import LLM
from ..state import Item, NewsState, Verdict
from .select import PICK

log = logging.getLogger(__name__)

SYSTEM = """너는 팩트체커야. '요약'의 각 주장이 '원문'에 근거가 있는지 확인해.
- what 칸의 사실 주장이 원문에 없으면 problems에 적어.
- why·action 칸은 의견이므로, 원문 사실을 왜곡하지 않으면 통과야.
- 근거 없는 주장이 하나라도 있으면 supported=false."""

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def unsupported_numbers(item: Item) -> list[str]:
    body_digits = {n.replace(",", "") for n in NUMBER.findall(item.article.body)}
    claimed = {n.replace(",", "") for n in NUMBER.findall(item.summary.what)}
    return sorted(claimed - body_digits)


def check(llm: LLM, item: Item) -> Verdict:
    bad_numbers = unsupported_numbers(item)
    if bad_numbers:
        return Verdict(supported=False, problems=[f"원문에 없는 숫자: {', '.join(bad_numbers)}"])
    s = item.summary
    prompt = f"원문:\n{item.article.body[:8000]}\n\n요약:\nwhat: {s.what}\nwhy: {s.why}\naction: {s.action}"
    return llm.parse(SYSTEM, prompt, Verdict)


def verify(state: NewsState, llm: LLM) -> NewsState:
    passed: list[Item] = []
    failed: list[Item] = []
    for item in state.get("items", []):
        checked = item.model_copy(update={"verdict": check(llm, item)})
        (passed if checked.verdict.supported else failed).append(checked)
        if not checked.verdict.supported:
            log.warning("verify 탈락: %s — %s", item.article.title, checked.verdict.problems)
    room = PICK - len(state.get("verified", []))
    return {"verified": passed[:room], "rejected": failed, "items": []}


def route_after_verify(state: NewsState) -> str:
    """5건이 모자라고 예비가 남았으면 report로 되돌린다."""
    short = len(state.get("verified", [])) < PICK
    has_reserve = state.get("cursor", 0) < len(state.get("selected", []))
    return "report" if short and has_reserve else "publish"
