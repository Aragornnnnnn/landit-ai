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

## 골든 셋 5회 연속 측정 — 샘플별 변동률과 드리프트 판단 (PR과 무관한 관측 기록)

2026-08-29, 검증본(base) 프롬프트 `--runs 5` (`golden_20260829T054125Z_base.json`).
비교 기준은 LAN-373의 base 13회(2026-08-26~27, 파일 5개)와 확장 프롬프트 측정.
판정 모델: OpenRouter 경유 `google/gemini-3.5-flash` (설정 기본값, .env 미오버라이드).

| 샘플 | 과거 base 13회 | 확장 2회 (8/29) | base 5회 (8/29) | 비고 |
| --- | --- | --- | --- | --- |
| s1_correct | 13/13 | 2/2 | 5/5 | |
| s1_phoneme | 13/13 | 2/2 | 5/5 | |
| s1_stress | 13/13 | 1/2 | 5/5 | 확장에서 1회 미검출 |
| s2_correct | 8/13 (diner FP 5회) | 0/2 (diner FP) | **5/5 (FP 0)** | 상시 플레이크가 소멸 |
| s2_phoneme | 13/13 | 2/2 | 5/5 | |
| s2_stress | 13/13 | 2/2 | 5/5 | |
| s3_correct | 13/13 | 2/2 | 5/5 | |
| s3_phoneme | 13/13 | 2/2 | 5/5 | |
| s3_stress | 13/13 | 1/2 | **0/5 (5연속 미검출)** | yesterday:STRESS |
| s4_correct | 13/13 | 2/2 | 5/5 | |
| s4_phoneme | 13/13 | 2/2 | 5/5 | |
| s4_stress | 13/13 | 2/2 | 5/5 | |

판단: **상류 모델 드리프트로 본다.**

- 과거 13회 내내 13/13이던 s3_stress가 5연속 미검출 — 무작위 변동으로는 설명이
  안 되는 이동이다 (과거 분포 기준 확률 사실상 0).
- 같은 측정에서 run당 약 38% 재현되던 diner 오탐이 0/5로 소멸 — 오탐 감소와
  미검출 등장이 **같은 방향(보수화)** 으로 동시에 움직였다. 개별 플레이크의
  요동이 아니라 판정 경향 자체의 이동이라는 뜻이다.
- 어제 확장 프롬프트 2회의 STRESS 미검출(hiking, yesterday)도 같은 방향이다.
- 따라서 "diner 3연속"은 원래 재현율 높은 플레이크라 그 자체는 신호가 아니고,
  진짜 신호는 s3_stress의 검출 소실이다. 과거 오탐 기준(1.7% = 59/60 블록의
  판정 단위 비율)과의 비교로는 오히려 개선처럼 보이지만, STRESS 재현율
  손실이 그 대가다.

권고 (이 PR 범위 밖, 별도 진행): 골든 셋을 주기적으로 5회 단위 측정해 경향을
추적하고, s3_stress 미검출이 유지되면 STRESS 검출 기준의 프롬프트 재보정을
별도 티켓으로 진행한다. OpenRouter의 서빙 모델 버전 고정 가능 여부도 확인할 것.

## 부수 발견 (기존 동작, 이번 변경과 무관)

완전 무음 녹음은 침묵 트림이 전체를 잘라 빈 wav(헤더뿐)가 되고, 그 probe가
`N/A`라 `AudioDecodeError` → 400 INVALID_AUDIO로 거부된다. m4a 등 기존
형식에서도 동일하게 재현되는 기존 경로다. 무음 거부 자체는 타당하나 에러
메시지("could not read audio duration")가 원인을 오도한다 — 필요 시 후속.
