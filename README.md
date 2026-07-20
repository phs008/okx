# OKX Perp 15분봉 RSI Scanner

OKX 공개 REST API에서 USDT 무기한 선물(`SWAP`, perp) 종목을 조회하고, 각 종목의 완료된 15분봉 기준 RSI/VWMA 조건이 맞으면 Discord webhook으로 알려줍니다.

OKX API key는 필요하지 않습니다. Discord 알림을 보낼 때만 webhook URL이 필요합니다.

## 한 번만 검색

```bash
python3 -m okx_scanner scan-once --dry-run
```

`--dry-run`은 Discord를 호출하지 않고 JSON 결과만 출력합니다.

## 15분봉 파워캔들 검색

```bash
python3 -m okx_scanner scan-power
```

최신 완료된 15분봉이 이전 20개 봉 평균보다 몸통과 거래량이 충분히 크고, 직전 고점 또는 저점을 돌파하며 종가가 봉 끝에 가깝고, 최신 봉 거래량이 직전 14일 15분봉 평균 거래량보다 30% 이상 높으면 JSON 출력과 Discord 알림을 보냅니다.

## Discord 알림

프로젝트 루트에 `.env` 파일을 만들고 webhook URL을 넣습니다.

```bash
cp .env.example .env
```

```dotenv
DISCORD_WEBHOOK_RSIVWMA=https://discord.com/api/webhooks/.../...
DISCORD_WEBKOOK_SIGNAL=https://discord.com/api/webhooks/.../...
```

`DISCORD_WEBHOOK_RSIVWMA`는 RSI/VWMA 알림용이고, `DISCORD_WEBKOOK_SIGNAL`은 파워캔들 신호용입니다. `DISCORD_WEBKOOK_SIGNAL`은 요청한 환경변수 철자를 그대로 사용합니다.

그다음 실행합니다.

```bash
python3 -m okx_scanner scan-once
```

조건에 맞는 종목이 없으면 Discord 메시지를 보내지 않습니다.

파워캔들을 계속 감시하려면 다음 명령을 사용합니다.

```bash
python3 -m okx_scanner power-daemon
```

실행 즉시 한 번 검사한 뒤 `SCAN_INTERVAL_SECONDS`마다 반복하며, 실행 중에는 같은 완료봉을 한 번만 전송합니다.

현재 알림 조건은 최신 완료 15분봉 기준입니다.

## 파워캔들 전략 시뮬레이션

```bash
python3 -m okx_scanner simulate-power
```

`DB_PATH_SIGNAL`의 과거 15분봉에서 첫 힘봉을 찾고, 이후 8개 봉을 관찰해 A/B/C/D/UNRESOLVED로 분류합니다.

- RSI 14가 RSI WMA 50을 상향 돌파하고 종가가 VWMA 100을 상향 돌파
- 또는 RSI 14가 RSI WMA 50을 하향 돌파하고 종가가 VWMA 100을 하향 돌파
- RSI/VWMA 전략에서는 최신 봉 거래량 급증 조건을 사용하지 않음

캔들 데이터는 SQLite에 저장합니다. DB가 비어 있으면 종목별 기본 `2400`개 캔들을 먼저 저장하고, 이후에는 최신 완료봉만 추가합니다. DB의 마지막 봉과 최신 완료봉 사이에 누락이 있으면 그 사이 봉을 모두 가져와 저장합니다. RSI/VWMA와 파워캔들은 각각 `INDICATOR_LOOKBACK`, `POWER_INDICATOR_LOOKBACK` 범위만 읽습니다.

## 백그라운드 실행

```bash
python3 -m okx_scanner daemon
```

`daemon`은 실행 즉시 한 번 검색하고, 이후 `SCAN_INTERVAL_SECONDS`마다 반복합니다. 기본값은 `900`초, 즉 15분입니다.

`nohup`으로 계속 실행하려면:

```bash
nohup python3 -m okx_scanner daemon > okx_scanner.log 2>&1 &
```

RSI/VWMA와 파워캔들 daemon을 함께 실행하려면:

```bash
./start_scanners.sh
```

실행 중인지 확인:

```bash
pgrep -af 'python3 -m okx_scanner (daemon|power-daemon)'
```

로그 확인:

```bash
tail -f rsi_scanner.log signal_scanner.log
```

스캔 시작/완료, Discord 전송 시작/성공/실패, 다음 실행까지 sleep 시간이 stdout 로그로 남습니다.

## 설정

| 환경변수 | 기본값 | 설명 |
|---|---:|---|
| `OKX_BASE_URL` | `https://www.okx.com` | OKX API 주소 |
| `QUOTE_CCY` | `USDT` | 조회할 정산/호가 통화 |
| `BAR` | `15m` | 고정값. 이 스캐너는 15분봉 전용입니다 |
| `RSI_PERIOD` | `14` | RSI 기간 |
| `RSI_OVERSOLD` | `30` | 기존 설정값. 현재 RSI/VWMA 돌파 전략에서는 사용하지 않음 |
| `RSI_OVERBOUGHT` | `70` | 기존 설정값. 현재 RSI/VWMA 돌파 전략에서는 사용하지 않음 |
| `RSI_WMA_PERIOD` | `50` | RSI WMA 기준 기간 |
| `CANDLE_LIMIT` | `2400` | 종목당 조회할 캔들 수 |
| `VWMA_PERIOD` | `100` | VWMA 계산 기간 |
| `INDICATOR_LOOKBACK` | `1345` | 매 스캔 계산에 사용할 최근 캔들 수 |
| `POWER_INDICATOR_LOOKBACK` | `1345` | 파워캔들 판별에 사용할 최근 캔들 수. 14일 거래량 SMA 계산을 위해 최소 1345 필요 |
| `DB_PATH_RSIVWMA` | `okx_rsi.sqlite3` | RSI/VWMA SQLite DB 파일 경로 |
| `DB_PATH_SIGNAL` | `okx_signal.sqlite3` | 파워캔들 signal SQLite DB 파일 경로 |
| `SCAN_INTERVAL_SECONDS` | `900` | daemon 반복 주기 |
| `REQUEST_TIMEOUT_SECONDS` | `10` | HTTP timeout |
| `REQUEST_ATTEMPTS` | `3` | OKX 요청 재시도 횟수 |
| `DISCORD_WEBHOOK_RSIVWMA` | 없음 | RSI/VWMA Discord webhook URL |
| `DISCORD_WEBKOOK_SIGNAL` | 없음 | 파워캔들 Discord webhook URL |

## 테스트

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q okx_scanner tests
```
