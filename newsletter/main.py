"""실행 진입점. 실패하면 Discord로 경보를 보내고 exit 1 (GitHub Actions가 빨간불)."""
from __future__ import annotations

import logging
import os
import sys

import requests

from .graph import build_graph
from .llm import OpenAILLM

log = logging.getLogger("newsletter")


def alert(message: str) -> None:
    url = os.environ.get("DISCORD_ALERT_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")
    if not url or os.environ.get("DRY_RUN") == "1":
        return
    try:
        requests.post(url, json={"content": f"🚨 뉴스레터 에이전트 실패\n```{message[:1800]}```"}, timeout=15)
    except requests.RequestException as e:
        log.error("경보 전송도 실패: %s", e)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    try:
        final = build_graph(OpenAILLM()).invoke({}, {"recursion_limit": 20})
    except Exception as e:  # noqa: BLE001
        log.exception("실행 실패")
        alert(f"{type(e).__name__}: {e}")
        return 1
    for err in final.get("errors", []):
        log.warning("경고: %s", err)
    log.info("완료: 발행 %d건, 검수 탈락 %d건", len(final["verified"]), len(final.get("rejected", [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
