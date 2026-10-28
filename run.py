# run.py
import os, sys
from graph import run                           # graph.py 에 있는 그 run()

if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        os.environ["DRY_RUN"] = "1"             # 35장의 dry_run 스위치
    out = run()
    for line in out["log"]:
        print(line)                             # 이 출력이 Actions 로그에 그대로 남는다
    # 41장 보강: Discord가 거절해도 send는 False만 돌려줘서 실행이 '성공'으로 끝난다
    # → 보내야 하는 실행인데 발행 줄에 '보냄'이 없으면 exit 1로 끝내 Actions를 빨간불로 만든다
    should_send = os.environ.get("DRY_RUN", "1") != "1"
    if should_send and not any(l.startswith("⑤") and "보냄" in l for l in out["log"]):
        print("발행 실패: Discord로 보내지 못했어요. 위의 '발행: 실패' 줄을 확인하세요.")
        sys.exit(1)
