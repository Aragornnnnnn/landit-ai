# LAN-388 — 발음 분석 webm 녹음 지원: 실측·검증 기록

웹(크롬·안드로이드 웹뷰) MediaRecorder는 webm(opus)으로만 녹음된다. BE(landit-be
`feat/LAN-387`)가 webm을 통과시키기 전에 AI 서버가 먼저 받아야 한다 —
**배포 순서: AI 먼저 → BE 나중** (역순이면 webm 요청이 502).

## duration 실측 (ffprobe `format=duration`)

| 샘플 | 반환값 | 비고 |
| --- | --- | --- |
| ffmpeg 파이프 산출 webm (`-f webm -`, seek 불가) | `N/A` (문자열) | stream duration도 `N/A`. 기존 코드는 float 파싱 실패로 하드 거부했다 |
| 실제 크롬 MediaRecorder webm (파일 저장) | 정상 판독 (4.437초) | 데스크톱 크롬 산출물 2건 모두 판독됨 (무음 샘플 3.9초 포함) |

결론: 데스크톱 크롬의 blob은 대체로 판독되지만, 스트리밍 mux 산출물(및 다른
webview·muxer 변형)은 `N/A`가 실재한다. 판독 실패 시 **유계 디코드 폴백**으로
실길이를 재고, 폴백 발동은 warning 로그(`fallback_count` 누적)로 관측한다.

폴백 방침 (확정): probe 실패·≤0 → `-t 31`로 최대 31초만 디코드 → 출력 wav
실측 길이 30초 이상이면 INVALID_AUDIO 거부, 미만이면 그 값으로 정상 진행.
opus는 압축률상 10MB(BE 크기 제한) 안에 수십 분이 들어가므로 상한 없는
디코드는 그 자체가 DoS 경로다 — 30초 검증은 어떤 경로로도 우회되지 않는다.

## ffmpeg opus 디코더 확인

- 로컬(homebrew ffmpeg 8.1.1): opus 디코더 있음
- 컨테이너(python:3.12-slim + apt ffmpeg — Dockerfile과 동일 구성): opus 디코더
  있음 (아래 CI 단계로 상시 검증)
- CI에 `Verify container ffmpeg decodes opus` 단계 추가 — 빌드된 이미지에서
  opus 디코더 부재 시 CI가 실패한다

## E2E (로컬 uvicorn + 참조 s1_tts.wav)

유저 음성: 골든 s1 실발화(correct.wav)를 크롬 AudioContext → MediaRecorder로
재녹음한 **진짜 크롬 산출 webm** (70KB, 4.54초).

| 케이스 | 결과 |
| --- | --- |
| 크롬 webm (duration 판독됨) | 200, 6.1초. 8단어 전부 CORRECT, 타임스탬프 633~3566ms 단조 증가 |
| 같은 음성의 스트리밍 재믹스 (probe `N/A`) | 200, 4.9초. 판정·타임스탬프 동일, 폴백 warning 1회 발동 확인 |

## 골든 셋 (2회, 확장 프롬프트)

`golden_20260829T052738Z_extended.json` · `golden_20260829T053017Z_extended.json`

- 두 회 모두 정확일치 10/12, 지연 p50 4.5초
- 오탐: `diner:SOUND` — LAN-373 기록 6회 중 5회 나타난 알려진 플레이크
- 미검출: 1차 `hiking:STRESS`, 2차 `yesterday:STRESS` — 회차마다 단어가 바뀌는
  LLM 변동 (LAN-373 기록: "회차 간 변동 있어 2회로는 판정 불가, 5회 이상 필요")
- 이 평가는 `judge_pronunciation`을 wav로 직접 호출해 **이번에 수정한 디코드
  경로를 타지 않는다** — 판정 계층 무변경 확인용이며, 디코드 회귀는
  `tests/test_pronunciation_audio.py`(실 ffmpeg)와 위 E2E가 커버한다

## 부수 발견 (기존 동작, 이번 변경과 무관)

완전 무음 녹음은 침묵 트림이 전체를 잘라 빈 wav(헤더뿐)가 되고, 그 probe가
`N/A`라 `AudioDecodeError` → 400 INVALID_AUDIO로 거부된다. m4a 등 기존
형식에서도 동일하게 재현되는 기존 경로다. 무음 거부 자체는 타당하나 에러
메시지("could not read audio duration")가 원인을 오도한다 — 필요 시 후속.
