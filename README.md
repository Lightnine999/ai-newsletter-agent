# AI 아침 브리핑 에이전트

매일 아침 7시 30분(KST), 그날 나온 AI 기사 중 개발팀이 알아야 할 5건을 골라 세 칸으로 요약하고 Discord로 보내는 LangGraph 에이전트예요. AIFFEL 노드 "매일 아침 AI 소식 5건을 골라 보내는 에이전트"를 1부부터 7부까지 따라 만들었어요.

```
START → collect → select ─(Send × 기사 수)→ report → verify → publish → END
                     └──────── 고른 기사가 0건이면 ────────┘
```

메인은 [graph.py](graph.py)(State·노드 다섯 개·`build()`·`run()`)와 [run.py](run.py)(실행 진입점)예요.

| 노드 | 하는 일 | State 칸 |
|------|---------|----------|
| collect | RSS 5곳(OpenAI·DeepMind·TechCrunch·The Verge·AI타임스)에서 최근 24시간 글만 모으고, 같은 주소는 한 번만 남겨요. 응답 없는 소스는 건너뛰고 이름을 로그에 적어요 | `collected` |
| select | 40건 묶음마다 8건(예선), 살아남은 것을 한 화면에 놓고 5건(본선). 구조화된 출력으로 이유와 사건 라벨을 받아요 | `picked` |
| report | `Send`로 기사마다 워커를 띄워요. 원문 본문이 600자 미만이면 빼고, headline·summary·why 세 칸으로 요약해요 | `drafted` (이어 붙이기) |
| verify | 요약을 쓴 호출과 따로 부른 LLM이 headline·summary를 원문과 뜻으로 대조해요. 떨어진 건 버리고 출처를 로그에 남겨요 | `verified` |
| publish | Discord embed 카드로 보내요. `DRY_RUN` 기본은 1(보내지 않음), 0건이면 "오늘은 조용합니다" 한 장 | 바깥 |

소스 선택과 관문은 [docs/sources.md](docs/sources.md)에 정리했어요.

실행 로그 예시:

```
① 수집   24시간 time window · 72건
② 선별   72 → 예선 16 → 5건
   취재 제외 AI타임스 · 본문 475자
④ 검수   4 → 4건
⑤ 발행   4건 · 보냄
```

## 노드와 다르게 넣은 것

| 위치 | 바꾼 것 | 이유 |
|------|---------|------|
| `graph.py` `url_key` | 주소 비교 때 `?` 뒤를 통째로 떼지 않고 추적용 꼬리표(`utm_*`, `fbclid`, `gclid`, `ref`)만 떼요 | AI타임스 주소는 기사 번호가 `?idxno=` 뒤에 있어서 50건이 1건으로 합쳐졌어요 |
| `graph.py` `fan_report` | 고른 기사가 0건이면 `verify`로 바로 가요 | 노드 44장의 고치는 법. 0건인 날에도 "오늘은 조용합니다"가 가야 멈춤과 구분돼요 |
| `graph.py` `publish` | ⑤ 줄을 `보냄` / `dry-run` / `실패` 세 가지로 적어요 | 발송 실패가 `dry-run`으로 찍혀 헷갈렸어요 |
| `run.py` | 보내야 하는 실행인데 못 보냈으면 `exit 1`로 끝나요 | 노드 41장 ①: Discord가 거절해도 실행이 성공으로 끝나 실패 메일이 안 왔어요 |

## 로컬 실행

```bash
uv venv && uv pip install -r requirements.txt
cp .env.example .env                 # OPENAI_API_KEY, DISCORD_WEBHOOK_URL 채우기
.venv/bin/python run.py --dry-run    # 보내지 않고 로그와 보낼 카드만 출력
DRY_RUN=0 .venv/bin/python run.py    # 실제로 Discord에 보냄 (.env의 DRY_RUN=1이 기본값)
```

## 매일 아침 받아 보기 (GitHub Actions)

1. Discord 채널 편집 → 연동 → 웹후크 → 새 웹후크 → URL 복사
2. 저장소 Settings → Secrets and variables → Actions에 `OPENAI_API_KEY`, `DISCORD_WEBHOOK_URL` 등록
3. Actions 탭 → `매일 브리핑` → Run workflow에서 dry_run을 체크해 한 번 돌려 로그 확인 → 정상이면 체크를 끄고 다시 실행

스케줄은 `30 22 * * *`(UTC) = 매일 07:30 KST예요. 알아둘 점:

- GitHub cron은 붐비는 시간에 몇 분에서 한 시간까지 늦을 수 있어요.
- 공개 저장소에 60일간 커밋이 없으면 스케줄 워크플로가 자동으로 꺼져요. Actions 탭에서 다시 켜 주세요.
- `watchdog` 워크플로(노드에는 없는 추가 장치)가 08:30에 "최근 3시간 안에 성공한 실행이 있나"를 보고, 없으면 같은 웹훅으로 알려요. 07:30 실행이 한 시간 넘게 밀리면 잘못 울릴 수 있고, 웹훅이 고장 난 날엔 이 알림도 막혀요.

## 아직 못 하는 것 (노드 44장)

- 평가셋이 없어 프롬프트를 바꾼 뒤 나빠졌는지 몰라요.
- 발행 전 사람 승인이 없어요.
- 실행 기록(소스별 건수, 단계별 탈락)이 파일로 쌓이지 않아요.
- 24장의 한글 검사가 연결돼 있지 않아요.
- 같은 사건 중복은 프롬프트에만 맡겨요. event 라벨을 Counter로 세거나 매체별 상한을 두는 건(20장) 아직 안 했어요. 실제로 AI타임스가 5건 중 3건 넘게 차지한 날이 있었어요.
- 403·404 응답 소스는 "응답 없음"에 안 잡혀요(14장의 `.raise_for_status()`를 아직 안 붙였어요).
- AI타임스 피드는 시각을 시간대 없이 한국 시간으로 적어서, UTC로 읽으면 9시간 미래 글로 보여요.

## 참고용: `newsletter/` 패키지

노드를 따라가기 전에 먼저 만들어 본 완성본이에요. 기사마다 점수 매기기, 숫자 글자 대조, 되돌아가는 검수 엣지처럼 **노드가 비교 끝에 접은 방식**이 들어 있어서 비교용으로만 남겨 뒀어요. 매일 실행에는 쓰지 않아요. 테스트는 `uv pip install pytest` 후 `.venv/bin/python -m pytest -q`로 돌려요.
