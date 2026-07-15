# OKX 15분봉 RSI·거래량·가격 급변 스캐너 연구 보고서

작성일: 2026-07-13  
결론: **Python REST 스캐너를 MVP로 구현**하고, 실제 부하나 지연 요구가 커질 때 WebSocket으로 전환한다.

## 1. 결정 사항과 명시적 기본값

사용자 문장의 모호한 부분은 숨은 가정으로 두지 않고 모두 설정값으로 만든다. 최초 구현의 기본값은 다음과 같다.

| 항목 | 기본값 | 정확한 의미 |
|---|---:|---|
| 시장 | `SPOT`, `quoteCcy=USDT`, `state=live` | 거래 가능한 OKX USDT 현물 종목만 검색 |
| 봉 | `15m` | **완료된 봉(`confirm=1`)만** 사용 |
| RSI | Wilder RSI(14) | `RSI <= 30`이면 과매도, `RSI >= 70`이면 과매수 |
| RSI 조건 | OR | 과매도 또는 과매수 중 하나면 충족 |
| 거래량 | `vol` | 현물에서는 기준통화(base currency) 수량 |
| 거래량 배수 | `current.vol / previous.vol >= 1.5` | 바로 직전의 완료된 15분봉과 비교 |
| 가격 변화 | `(close - open) / open * 100` | 최신 완료 15분봉 몸통의 부호 있는 등락률 |
| 가격 조건 | `abs(change_pct) >= 30` | 상승 또는 하락이 30% 이상 |
| 0 거래량 정책 | `skip` | 직전 거래량이 0이면 비율을 정의하지 않고 신호 제외 |
| 알림 중복 키 | `instId + bar + candle_ts + signal_side` | 같은 봉의 같은 신호는 재시작 후에도 한 번만 알림 |

`PRICE_REFERENCE=previous_close`, `VOLUME_FIELD=volCcyQuote`, `INSTRUMENT_TYPE=SWAP` 등은 후속 설정으로 허용한다. 특히 “30% 상승/하락”이 전일/직전 종가 기준이라는 뜻이었다면 `PRICE_REFERENCE`만 변경하면 된다.

모든 조건은 **동일한 최신 완료 봉에서 동시에** 만족해야 한다.

```text
rsi_extreme = rsi14 <= 30 or rsi14 >= 70
volume_surge = previous_volume > 0 and current_volume / previous_volume >= 1.5
signed_change_pct = (current_close - current_open) / current_open * 100
price_surge = abs(signed_change_pct) >= 30
signal = rsi_extreme and volume_surge and price_surge
```

## 2. 공식 문서로 확인한 사실

### OKX

1. 공개 종목 목록은 `GET /api/v5/public/instruments?instType=SPOT`으로 얻는다. 공개 데이터라 인증이 필요 없고, 문서상 제한은 IP+instrument type 기준 **20 requests / 2 seconds**다. 응답의 `state=live`, `quoteCcy=USDT`, `instId`를 이용해 기본 유니버스를 만든다.  
   출처: [OKX Get instruments](https://www.okx.com/docs-v5/en/#order-book-trading-public-data-get-instruments)
2. 캔들은 `GET /api/v5/market/candles?instId=...&bar=15m&limit=100`으로 얻는다. 문서상 최신 1,440개까지 조회할 수 있고, 요청당 최대 `limit=300`, 제한은 IP 기준 **40 requests / 2 seconds**다.  
   출처: [OKX Get candlesticks](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks)
3. 캔들 배열은 `[ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]` 순서다. `confirm=0`은 미완료, `confirm=1`은 완료 봉이다. 현물의 `vol`은 기준통화 수량이고 `volCcyQuote`는 호가통화 수량이다. 따라서 인덱스 추측 대신 명시적 파서/dataclass로 변환해야 한다.  
   출처: [OKX Get candlesticks](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks)
4. OKX는 시장 데이터에 WebSocket 사용을 권장한다. WebSocket 연결 요청 제한은 IP 기준 초당 3회, 한 연결의 `subscribe`/`unsubscribe`/`login` 합계는 시간당 480회이며 30초 이상 데이터가 없을 때 ping/pong 유지 절차가 필요하다.  
   출처: [OKX WebSocket overview/connect](https://www.okx.com/docs-v5/en/#overview-websocket)
5. 캔들 WebSocket 채널은 `/ws/v5/business`의 `candle15m`이고 가장 빠른 push 간격은 1초다. 대규모 실시간 구독으로 발전시킬 때 사용할 수 있으나, 재연결·재구독·누락 봉 보충 로직이 추가된다.  
   출처: [OKX WS Candlesticks channel](https://www.okx.com/docs-v5/en/#websocket-api-public-channel-ws-candlesticks-channel)
6. OKX 문서는 등록 지역에 따라 API 도메인이 다를 수 있음을 알린다. 따라서 `OKX_BASE_URL`을 설정으로 노출하고 기본 글로벌 도메인만 코드에 둔다.  
   출처: [OKX API guide](https://www.okx.com/docs-v5/en/)

### Discord

1. Incoming webhook은 별도 bot 인증 없이 채널에 메시지를 게시할 수 있다. 실행은 `POST /webhooks/{webhook.id}/{webhook.token}`이며 `wait=true`를 쓰면 서버 저장 확인을 응답으로 받을 수 있다. 메시지는 `content`, `embeds` 등 최소 한 필드가 필요하고 `content`는 최대 2,000자, embeds는 최대 10개다.  
   출처: [Discord Execute Webhook](https://docs.discord.com/developers/resources/webhook#execute-webhook)
2. Discord는 제한 숫자를 하드코딩하지 말고 응답 rate-limit 헤더를 읽도록 요구한다. HTTP 429에서는 `Retry-After` 또는 JSON의 `retry_after`만큼 기다려야 한다. 반복 404는 중단해야 하며, 무효 요청 누적은 임시 제한 위험이 있다.  
   출처: [Discord Rate Limits](https://docs.discord.com/developers/topics/rate-limits)

## 3. 라이브 API 가능성 검증

2026-07-13에 인증 없는 공식 공개 REST API를 실제 호출해 다음을 확인했다.

- `SPOT`, `USDT`, `state=live`: **303종목**
- 각 종목에서 최근 100개 15분봉 요청: 303/303 성공
- 호출 속도: 약 10 requests/s로 보수적으로 제한
- 전체 완료 시간: **31.815초**
- 최신 완료 봉에서 절대 30% 이상 움직인 종목: 0
- 세 조건을 모두 만족한 종목: 0

원본 증거: `.omx/goals/autoresearch/okx-15m-rsi-volume-discord-scanner/live-api-audit.json`

이는 15분마다 약 32초 걸리는 REST 스캔이 현재 기본 유니버스에서 충분히 가능함을 보인다. 동시에 단일 15분봉 30% 조건은 계산 가능하지만 매우 드문 조건이라는 점도 보여준다. 이 한 시점 표본만으로 미래 빈도를 추정할 수는 없다. 운영 시작 시 `--dry-run`으로 7일간 후보 수를 계측하고, 알림이 너무 적으면 가격 기준을 10% 또는 직전 종가 기준으로 조정하는 것이 합리적이다.

## 4. 권장 아키텍처

### 4.1 REST 기반 Python MVP

Python 3.11+ 표준 라이브러리만으로도 구현할 수 있다. 초기 버전에서는 OKX SDK가 필요 없다. 공개 REST endpoint만 사용하므로 OKX API key도 필요 없다.

```text
src/okx_scanner/
  config.py       # 환경변수 파싱, 범위 검증, 비밀값 redaction
  models.py       # Candle, Instrument, Signal
  okx_client.py   # timeout, rate limiter, retry, response schema validation
  indicators.py   # Wilder RSI
  detector.py     # 거래량/가격/RSI 조합 판정
  state.py        # 원자적 JSON 상태 또는 sqlite3 outbox/dedup
  discord.py      # wait=true webhook, 429/5xx 처리
  service.py      # scan_once 및 daemon scheduler
  cli.py          # scan-once, daemon, health, --dry-run
tests/
  fixtures/
  test_indicators.py
  test_detector.py
  test_okx_client.py
  test_discord.py
  test_state.py
```

권장 실행 흐름:

1. 시작 시 공개 instruments를 받고 `live + USDT`로 필터링한다. 1시간마다 새로 고친다.
2. 매 UTC 15분 경계 후 8초에 스캔을 시작한다. API가 아직 완료 봉을 주지 않으면 5초 간격으로 최대 3회 재확인한다.
3. 종목별 최근 100개 캔들을 요청하고 `confirm=1`만 남긴 뒤 `ts` 오름차순으로 정렬한다.
4. 기대한 최신 완료 봉 timestamp와 일치하는지 확인한다. 누락이면 해당 종목은 신호를 만들지 않고 구조화 로그를 남긴다.
5. 100개 종가로 Wilder RSI(14)를 계산한다. 최초 14개 변화의 단순 평균으로 평균 상승/하락을 seed한 뒤 Wilder smoothing을 적용한다.
6. 최신 완료 봉과 직전 완료 봉으로 세 조건을 판정한다.
7. dedup/outbox 상태를 확인한 뒤 Discord로 전송한다. 성공 확인 후 sent 상태로 원자적으로 기록한다.
8. 스캔 요약(`universe`, `success`, `skipped`, `errors`, `signals`, `duration`)을 JSON 로그로 남긴다.

### 4.2 WebSocket을 지금 선택하지 않는 이유

303 REST 요청을 보수적 속도로 처리해도 약 32초로 15분 주기보다 훨씬 짧다. WebSocket은 더 빠르지만 수백 구독, heartbeat, 자동 재연결, 재구독, gap recovery, 초기 RSI history bootstrap이 필요하다. 따라서 MVP에는 복잡도 대비 이점이 작다.

다음 조건 중 하나가 생기면 WebSocket으로 전환한다.

- 1분 이하 봉으로 확대
- SPOT+SWAP+FUTURES 전체를 함께 검색
- 봉 종료 후 수초 이내 알림이 반드시 필요
- 실제 REST 스캔 p95가 120초를 초과

전환 후에도 시작/복구 시 REST 100개 봉으로 RSI를 bootstrap하고, `candle15m`의 `confirm=1` 이벤트만 detector에 전달한다.

### 4.3 웹 UI 선택지

현재 요구는 백그라운드 검색과 Discord 알림이 핵심이므로 웹 UI는 운영 복잡도만 늘린다. 우선 Python daemon + JSON 로그로 배포한다. 이후 필요하면 같은 detector/service 위에 얇은 read-only 상태 페이지를 추가한다. 웹 요청 처리 프로세스 안에서 scheduler를 함께 띄우면 다중 worker가 중복 스캔할 수 있으므로, 웹과 scanner는 별도 프로세스로 유지해야 한다.

## 5. 계산 세부사항과 예외

### Wilder RSI(14)

- 완료 봉을 오래된 순서로 정렬한다.
- 최소 15개 종가가 필요하지만, 초기 seed 영향 감소를 위해 기본 100개를 사용한다.
- 변화량 `delta = close[i] - close[i-1]`.
- `gain=max(delta,0)`, `loss=max(-delta,0)`.
- 최초 14개 gain/loss의 산술평균을 seed로 사용한다.
- 이후 `avg = (previous_avg * 13 + current) / 14`.
- 평균 loss가 0이고 gain>0이면 RSI=100, gain과 loss 모두 0이면 RSI=50, 평균 gain이 0이고 loss>0이면 RSI=0.
- 경계는 포함한다: 30.0과 70.0도 각각 과매도/과매수다.

### 데이터 방어

- `confirm=0`은 절대 신호 계산에 포함하지 않는다.
- `open <= 0`, 음수 volume, 필드 수가 9가 아닌 행, 숫자 변환 실패는 malformed data로 skip한다.
- 직전 volume이 0이면 기본값은 skip이다. 0 대비 양수 거래량을 무한대로 간주하면 유동성 없는 신규/정지 종목의 거짓 신호가 늘 수 있다.
- 신규 상장 등으로 완료 봉이 15개 미만이면 RSI를 만들지 않는다.
- 같은 종목의 캔들 timestamp가 중복되면 마지막으로 받은 값 하나만 유지하되 경고한다.
- 서버 clock과 무관하게 캔들 `ts` 및 15분 경계를 UTC epoch로 계산한다.
- `vol`과 `volCcyQuote`는 의미가 다르므로 설정값 이름과 alert에 사용 필드를 표시한다.

## 6. 호출 제한, 재시도, 상태

### OKX

- token-bucket을 **10 requests/s, burst 10**으로 설정해 문서상 20 requests/s보다 여유를 둔다.
- timeout은 connect/read 합계 10초, 각 종목 최대 3회다.
- HTTP 429, OKX code `50011`, 네트워크 오류, 5xx만 지수 backoff+jitter로 재시도한다.
- 4xx schema/parameter 오류는 재시도하지 않는다.
- 한 종목 실패가 전체 스캔을 중단하지 않도록 격리한다.
- 성공률이 95% 미만이면 스캔을 degraded로 표시하고 운영 경고를 1회 보낸다.

### Discord와 중복 억제

- `DISCORD_WEBHOOK_URL`은 환경변수 또는 권한 0600 secret file에서만 읽는다. 소스, `.env.example`, 로그, exception URL에 넣지 않는다.
- URL을 로그에 남겨야 하는 상황에서도 host와 끝 4자만 남기고 token/path를 redaction한다.
- `wait=true`를 사용하고 `allowed_mentions={"parse":[]}`로 의도하지 않은 mention을 막는다.
- 429는 `Retry-After`/`retry_after`를 따른다. 5xx는 jitter backoff로 최대 5회, 400/401/403/404는 재시도하지 않는다. 404는 webhook 비활성 상태로 전환한다.
- 상태는 처음에는 표준 라이브러리 `sqlite3`를 권장한다. `signals(key PRIMARY KEY, status, attempts, message_id, updated_at)` outbox로 pending/sent를 관리한다.
- 네트워크 timeout 직전에 Discord가 메시지를 저장했는지 알 수 없는 경우 완전한 exactly-once는 보장할 수 없다. 로컬 outbox는 정상 재시작 중복을 막지만 이 모호한 실패에서는 중복 가능성을 구조화 로그로 표시한다.

권장 embed 필드: 종목, 과매수/과매도, RSI, 방향, 등락률, 현재/직전 거래량, 배수, 봉 시작/종료 UTC 및 KST, `instId`, 조건 설정 버전.

## 7. 설정과 CLI 계약

```text
OKX_BASE_URL=https://www.okx.com
INSTRUMENT_TYPE=SPOT
QUOTE_CCY=USDT
BAR=15m
RSI_PERIOD=14
RSI_OVERSOLD=30
RSI_OVERBOUGHT=70
VOLUME_FIELD=vol
VOLUME_RATIO_MIN=1.5
PRICE_REFERENCE=open
PRICE_MOVE_PERCENT_MIN=30
MAX_REQUESTS_PER_SECOND=10
REQUEST_TIMEOUT_SECONDS=10
DISCORD_WEBHOOK_URL=<secret>
STATE_DB=.state/scanner.sqlite3
```

```bash
python -m okx_scanner scan-once --dry-run
python -m okx_scanner scan-once
python -m okx_scanner daemon
python -m okx_scanner health
```

잘못된 임계값, 지원하지 않는 volume field, 누락된 webhook(dry-run 제외)은 시작 시 즉시 실패시킨다. `scan-once --dry-run`은 실제 OKX를 조회하지만 Discord는 호출하지 않고 후보 JSON을 stdout에 출력한다.

## 8. 테스트 전략과 합격 기준

### 단위 테스트

- 알려진 고정 종가 벡터의 Wilder RSI 결과를 소수점 허용오차로 검증
- 상승만/하락만/변화 없음 RSI가 100/0/50인지 검증
- RSI 30/70, 거래량 1.5, 가격 ±30 경계가 포함되는지 검증
- 세 조건 중 하나라도 빠지면 signal이 아닌지 검증
- 최신 미완료 봉이 첫 행이어도 무시되는지 검증
- newest-first 응답을 정렬하고 정확한 직전 완료 봉을 고르는지 검증
- 직전 volume 0, open 0, malformed row, 짧은 history 처리 검증

### fixture/통합 테스트

- OKX 정상/빈 데이터/50011/429/5xx/timeout/schema 변경 fixture
- instruments에서 `live + USDT`만 남는지 검증
- Discord 2xx, 429 retry_after, 5xx backoff, 404 영구 중단 검증
- webhook URL이 captured log/exception에 포함되지 않는지 검증
- process restart 전후 동일 dedup key의 전송 횟수가 1인지 검증
- pending outbox 복구 및 DB 원자성 검증

### smoke/운영 합격 기준

1. live OKX dry-run에서 완료 봉만 계산하고 schema 오류 0건.
2. 기본 유니버스 스캔 p95 < 120초, 성공률 >= 99%.
3. 고정 fixture에서 기대 신호 집합과 실제 집합이 정확히 동일.
4. 같은 fixture를 연속 2회 및 재시작 후 실행해 Discord mock 호출은 1회.
5. 429 응답 시 지정 시간 전 재호출 0회.
6. 모든 로그와 테스트 artifact에서 webhook URL/token 검출 0건.
7. lint/typecheck가 도입될 경우 통과하고, 기본 `python -m unittest` 전체 통과.

## 9. 위험과 완화

| 위험 | 영향 | 완화 |
|---|---|---|
| 30%/15분 조건이 지나치게 희귀 | 알림이 거의 없음 | 7일 dry-run 계측, 임계값 설정화 |
| 저유동성 종목의 왜곡 | 순간 체결로 거짓 양성 | 최소 `volCcyQuote` 옵션, 신규상장/0-volume skip |
| API schema/순서 오해 | 잘못된 신호 | 9필드 검증, named model, fixture 계약 테스트 |
| 미완료 봉 사용 | 봉 종료 전 신호 번복 | `confirm=1` 강제, expected timestamp 검사 |
| REST 제한/일시 장애 | 종목 누락 | 10 rps, retry/backoff, 성공률 요약 |
| 중복 Discord 알림 | 스팸 | sqlite outbox+dedup, `wait=true` |
| webhook 유출 | 채널 스팸/탈취 | secret 저장, redaction, 0600 권한, 즉시 회전 절차 |
| 지역별 OKX 도메인 | 연결 실패 | `OKX_BASE_URL` 설정 및 startup health check |

## 10. 최종 구현 권고

1. **1단계**: 표준 라이브러리 기반 Python `scan-once --dry-run`, indicator/detector 단위 테스트.
2. **2단계**: sqlite outbox와 Discord webhook, retry/redaction 테스트.
3. **3단계**: `daemon` scheduler, systemd/Docker health check, 7일 dry-run 관찰.
4. **4단계**: 관찰 결과로 30% 및 유동성 임계값 조정.
5. **전환 기준 충족 시**: WebSocket `candle15m` + REST bootstrap/gap recovery.

이 경로는 API key 없이 시작할 수 있고, 현재 303개 USDT 현물 유니버스를 15분 주기 안에 충분히 처리하며, 계산 정의·비밀 관리·재시도·중복 억제를 모두 테스트 가능한 경계로 분리한다.
