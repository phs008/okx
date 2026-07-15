# OKX Perp 15분봉 RSI Scanner

OKX 공개 REST API에서 USDT 무기한 선물(`SWAP`, perp) 종목을 조회하고, 각 종목의 완료된 15분봉 기준 RSI/VWMA 조건이 맞으면 Discord webhook으로 알려줍니다.

OKX API key는 필요하지 않습니다. Discord 알림을 보낼 때만 webhook URL이 필요합니다.

## 한 번만 검색

```bash
python3 -m okx_scanner scan-once --dry-run
```

`--dry-run`은 Discord를 호출하지 않고 JSON 결과만 출력합니다.

## Discord 알림

프로젝트 루트에 `.env` 파일을 만들고 webhook URL을 넣습니다.

```bash
cp .env.example .env
```

```dotenv
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/.../...
```

그다음 실행합니다.

```bash
python3 -m okx_scanner scan-once
```

조건에 맞는 종목이 없으면 Discord 메시지를 보내지 않습니다.

현재 알림 조건은 최신 완료 15분봉 기준입니다.

- RSI가 `30 이하`이고 종가가 VWMA 100 아래
- 또는 RSI가 `70 이상`이고 종가가 VWMA 100 위

캔들 데이터는 SQLite에 저장합니다. DB가 비어 있으면 종목별 기본 `2400`개 캔들을 먼저 저장하고, 이후에는 최신 완료봉만 추가합니다. DB의 마지막 봉과 최신 완료봉 사이에 누락이 있으면 그 사이 봉을 모두 가져와 저장합니다. 스캔 계산은 매번 전체 `2400`개를 읽지 않고 `INDICATOR_LOOKBACK` 개수만 읽습니다.

## 백그라운드 실행

```bash
python3 -m okx_scanner daemon
```

`daemon`은 실행 즉시 한 번 검색하고, 이후 `SCAN_INTERVAL_SECONDS`마다 반복합니다. 기본값은 `900`초, 즉 15분입니다.

`nohup`으로 계속 실행하려면:

```bash
nohup python3 -m okx_scanner daemon > okx_scanner.log 2>&1 &
```

로그 확인:

```bash
tail -f okx_scanner.log
```

스캔 시작/완료, Discord 전송 시작/성공/실패, 다음 실행까지 sleep 시간이 stdout 로그로 남습니다.

## 설정

| 환경변수 | 기본값 | 설명 |
|---|---:|---|
| `OKX_BASE_URL` | `https://www.okx.com` | OKX API 주소 |
| `QUOTE_CCY` | `USDT` | 조회할 정산/호가 통화 |
| `BAR` | `15m` | 고정값. 이 스캐너는 15분봉 전용입니다 |
| `RSI_PERIOD` | `14` | RSI 기간 |
| `RSI_OVERSOLD` | `30` | 이 값 이하이면 알림 |
| `RSI_OVERBOUGHT` | `70` | 이 값 이상이면 알림 |
| `CANDLE_LIMIT` | `2400` | 종목당 조회할 캔들 수 |
| `VWMA_PERIOD` | `100` | VWMA 계산 기간 |
| `INDICATOR_LOOKBACK` | `300` | 매 스캔 계산에 사용할 최근 캔들 수 |
| `DB_PATH` | `okx_scanner.sqlite3` | SQLite DB 파일 경로 |
| `SCAN_INTERVAL_SECONDS` | `900` | daemon 반복 주기 |
| `REQUEST_TIMEOUT_SECONDS` | `10` | HTTP timeout |
| `REQUEST_ATTEMPTS` | `3` | OKX 요청 재시도 횟수 |
| `DISCORD_WEBHOOK_URL` | 없음 | Discord webhook URL |

## 테스트

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q okx_scanner tests
```
