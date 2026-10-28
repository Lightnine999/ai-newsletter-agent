"""LLM 호출을 한 곳에 모은 얇은 래퍼. 테스트에서는 가짜로 바꿔 끼운다."""
from __future__ import annotations

import os
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")


class LLM(Protocol):
    def parse(self, system: str, user: str, schema: type[T]) -> T: ...


class OpenAILLM:
    """구조화 출력(pydantic)으로 응답을 받는다."""

    def __init__(self, model: str = MODEL) -> None:
        from openai import OpenAI

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았어요 (.env 또는 GitHub Secrets)")
        self.client = OpenAI()
        self.model = model

    def parse(self, system: str, user: str, schema: type[T]) -> T:
        res = self.client.chat.completions.parse(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=schema,
        )
        parsed = res.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError(f"LLM이 {schema.__name__} 형식으로 답하지 않았어요")
        return parsed
