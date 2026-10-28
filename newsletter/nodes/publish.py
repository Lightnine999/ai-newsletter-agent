"""publish: 검수 통과분을 Discord 웹훅으로 보내고, 같은 내용을 마크다운으로 남긴다."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import requests

from ..state import Item, NewsState

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))
EMBED_COLOR = 0x5865F2


def today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def to_embed(rank: int, item: Item) -> dict:
    s = item.summary
    return {
        "title": f"{rank}. {item.article.title}"[:256],
        "url": item.article.url,
        "color": EMBED_COLOR,
        "description": f"**무슨 일**\n{s.what}\n\n**왜 중요**\n{s.why}\n\n**우리 팀은**\n{s.action}"[:4000],
        "footer": {"text": item.article.source},
    }


def to_markdown(items: list[Item]) -> str:
    lines = [f"# AI 아침 브리핑 {today()}", ""]
    for rank, item in enumerate(items, 1):
        s = item.summary
        lines += [
            f"## {rank}. [{item.article.title}]({item.article.url})",
            f"_{item.article.source}_",
            "",
            f"- **무슨 일**: {s.what}",
            f"- **왜 중요**: {s.why}",
            f"- **우리 팀은**: {s.action}",
            "",
        ]
    return "\n".join(lines)


def send_discord(payload: dict) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL이 설정되지 않았어요")
    res = requests.post(url, json=payload, timeout=15)
    res.raise_for_status()


def publish(state: NewsState, send: Callable[[dict], None] = send_discord) -> NewsState:
    items = state.get("verified", [])
    if not items:
        raise RuntimeError("publish: 검수를 통과한 기사가 없어요")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUTPUT_DIR / f"{today()}.md"
    md_path.write_text(to_markdown(items), encoding="utf-8")
    log.info("publish 마크다운 저장: %s", md_path)

    header = f"☀️ **AI 아침 브리핑 {today()}** — 오늘 개발팀이 알아둘 {len(items)}건"
    payload = {"content": header, "embeds": [to_embed(i, it) for i, it in enumerate(items, 1)]}
    if os.environ.get("DRY_RUN") == "1":
        log.info("DRY_RUN: Discord 전송 생략")
    else:
        send(payload)
        log.info("publish Discord 전송 완료 (%d건)", len(items))
    return {"published": True}
