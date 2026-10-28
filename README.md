# AI 아침 브리핑 에이전트

매일 아침 7시 30분(KST), 그날 나온 AI 기사 중 개발팀이 알아야 할 5건을 골라 세 칸으로 요약하고 Discord로 보내는 LangGraph 에이전트예요.

```
START → collect → select → report → verify → publish → END
                             ↑          │
                             └──────────┘  검수 탈락 시 예비 후보로 다시 요약
```

| 노드 | 하는 일 | 파일 |
|------|---------|------|
| collect | RSS 8곳 + Hacker News API에서 모으고 관문으로 거름 | `newsletter/nodes/collect.py`, `newsletter/sources.py` |
| select | 규칙 예선 → LLM 채점 → 같은 소식 묶기 → 규칙 결선(소스당 2건, 소식당 1건)으로 5건 + 예비 3건 | `newsletter/nodes/select.py` |
| report | 원문 본문(trafilatura)을 읽고 **무슨 일 / 왜 중요 / 우리 팀은** 세 칸 요약 | `newsletter/nodes/report.py` |
| verify | 숫자 대조(규칙) + 주장 대조(LLM)로 원문에 없는 내용 걸러냄 | `newsletter/nodes/verify.py` |
| publish | Discord 웹훅 전송 + `output/날짜.md` 저장 | `newsletter/nodes/publish.py` |

자료 수집 방식 비교와 관문 설명은 [docs/sources.md](docs/sources.md)에 있어요.

## 설계 포인트

- **LLM은 점수만, 선택은 코드가** — select에서 LLM은 기사마다 `dev_impact·novelty·credibility`를 매기고, 최종 5건은 코드가 총점과 다양성 규칙으로 골라요. 그래서 결과를 재현하고 테스트하기 쉬워요. LLM이 없는 id를 지어내면 버려요.
- **같은 소식은 한 번만** — 매체마다 제목이 달라서 URL·제목 비교로는 중복을 못 잡아요(실제로 Genie 4 발표가 TechCrunch와 The Verge에서 둘 다 뽑혔어요). 그래서 상위 후보를 한 번에 LLM에 보여 주고 같은 사건끼리 묶게 한 뒤, 묶음마다 점수가 가장 높은 기사 하나만 남겨요.
- **세 칸 요약** — pydantic `Summary(what, why, action)` 구조화 출력이라 칸이 빠지거나 형식이 흐트러지지 않아요.
- **두 겹 검수** — 요약에 나온 숫자가 원문에 없으면 LLM을 부르기 전에 바로 탈락시키고, 그다음 LLM이 주장 하나하나를 원문과 대조해요. 떨어진 자리는 예비 후보로 채워요.
- **멈추면 알아채기** — 실패하면 `main.py`가 Discord로 경보를 보내고 Actions가 빨간불이 돼요. 아예 안 돌았을 때는 08:30 `watchdog` 워크플로가 "오늘 성공한 실행이 없다"고 알려요.

## 로컬 실행

```bash
uv venv && uv pip install -r requirements.txt pytest
cp .env.example .env   # 키 채우기
.venv/bin/python -m pytest -q          # 네트워크·키 없이 도는 테스트
.venv/bin/python -m newsletter.main    # DRY_RUN=1이면 Discord 대신 output/에만 저장
```

## 매일 아침 받아 보기 (GitHub Actions)

1. Discord 채널 설정 → 연동 → 웹후크 만들기 → URL 복사
2. 저장소 Settings → Secrets and variables → Actions에 등록
   - `OPENAI_API_KEY`, `DISCORD_WEBHOOK_URL` (필수)
   - `DISCORD_ALERT_WEBHOOK_URL` (선택, 경보를 다른 채널로)
3. Actions 탭 → `daily-newsletter` → Run workflow로 한 번 수동 실행해 확인

스케줄은 `30 22 * * *`(UTC) = 매일 07:30 KST예요. 알아둘 점:

- GitHub cron은 붐비는 시간에 몇 분~수십 분 늦을 수 있어요.
- 공개 저장소에 60일간 커밋이 없으면 스케줄 워크플로가 자동으로 꺼져요. 꺼지면 watchdog도 같이 멈추니, Actions 탭에서 다시 켜 주세요.

## 한계

- 숫자 대조는 표기가 바뀌면(예: `$1 billion` → `10억 달러`) 근거가 있어도 탈락시킬 수 있어요. 프롬프트에서 "숫자는 원문 그대로"를 요구하는 이유예요.
- 피드 목록과 키워드는 `newsletter/sources.py`에서 손으로 관리해요.
