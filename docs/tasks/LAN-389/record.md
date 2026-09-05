# LAN-389 — STRESS 검출 소실(드리프트) 해소: 실측·조치 기록

LAN-388 측정에서 발견된 판정 드리프트(과거 base 13회 내내 검출되던
s3_stress가 5연속 미검출, diner 오탐은 동시 소멸 — 보수화 방향 이동)의
원인 규명과 해소. 강세 검출은 스펙 기능이라 출시 전 해결 게이트로 잡았다.
배경: `docs/tasks/LAN-388/record.md`.

## ① 원인 실측 — 모델 버전이 아니라 서빙 프로바이더

- OpenRouter에 `google/gemini-3.5-flash`의 날짜 고정 슬러그는 없다
  (2026-08-31 실측: `-lite`·`:batch` 변형뿐. `-20260519`는 해석되지만 별칭으로
  정규화). 엔드포인트는 전부 상류 `gemini-3.5-flash-20260519`(5월 버전)를
  서빙 중 — 8월 말 드리프트를 "버전 교체"로는 설명할 수 없다.
- **프로바이더 고정 실측 (s3_stress ×3 + s3_correct ×1, 검증본 프롬프트)**:

  | 프로바이더 | s3_stress (yesterday:STRESS) | s3_correct |
  | --- | --- | --- |
  | `google-ai-studio` | **3/3 검출** | 무오탐 |
  | `google-vertex` | **0/3 미검출** | 무오탐 |

- 결론: 같은 모델 슬러그라도 Vertex 서빙은 STRESS 검출이 죽는다. OpenRouter
  자동 라우팅이 Vertex로 기울면서(30분 uptime: vertex 99.8 vs ai-studio 97.9)
  검출 소실이 드리프트처럼 나타났다. 과거 13회 측정은 AI Studio를 탄 것으로
  추정된다.

## 조치 — 프로바이더 고정 + 폴백 관측

- `pronunciation_provider_order` 설정 신설 (기본 `google-ai-studio`,
  쉼표 구분 우선순위, 빈 값 = 자동 라우팅). `app/pronunciation/llm/routing.py`의
  공통 헬퍼가 판정·억양·묘사 세 호출 전부에 라우팅을 주입한다.
- 폴백은 허용한다(가용성 우선 — AI Studio 다운 시 503 대신 Vertex 서빙).
  단, 폴백 서빙은 STRESS 검출이 죽는 조용한 저하이므로 본 판정 응답의
  provider가 선호 프로바이더와 다르면 warning 로그를 남긴다.

## ① 검증 — 프로바이더 고정 후 골든 5회 (검증본 프롬프트): **불충분**

`golden_20260831T051144Z_base.json` (google-ai-studio 고정):

| 샘플 | vertex (8/29) | ai-studio 고정 (8/31) | 과거 base 13회 |
| --- | --- | --- | --- |
| s3_stress (yesterday) | 0/5 미검출 | **5/5 복구** | 13/13 |
| s1_stress (hiking) | 5/5 정상 | **0/5 미검출** | 13/13 |
| s2_correct (diner) | 오탐 0/5 | **오탐 5/5 (상시화)** | 오탐 ~38%/run |
| 나머지 9개 샘플 | 정상 | 5/5 정상 | 정상 |
| 지연 p50 | 4.1s | **2.8s** | ~4.1s |

판단: 지연이 4.1→2.8초로 크게 바뀐 것까지 보면 **상류 서빙이 양쪽 프로바이더
모두에서 8월 말에 바뀌었다** (단일 프로바이더 라우팅 문제가 아님). 어느 쪽을
골라도 STRESS 샘플 하나가 과반 미달로 죽으므로(ai-studio는 hiking, vertex는
yesterday) 프로바이더 고정은 "보정 대상 서빙을 고정한다"는 전제 조건일 뿐
해소가 아니다 → ② 프롬프트 재보정으로 진행. 고정 기본값은 ai-studio 유지
(재보정의 재현성 확보 + 지연 개선).

## ③ 주기 드리프트 감시

- `scripts/eval_pronunciation_golden.py --gate`: 샘플별 미검출(또는 측정 에러)
  run이 과반이면 종료 코드 1. 오탐은 허용 기준이 기획 미정이라 게이트에서
  제외하고 리포트로만 관측한다.
- `.github/workflows/golden-eval.yml`: 매주 월 09:00 KST + 수동 트리거로
  5회 측정(검증본 프롬프트) → 게이트 실패 시 워크플로 실패로 알림, 결과
  JSON은 아티팩트 90일 보존. **가동 조건: 레포 시크릿 `OPENROUTER_API_KEY`
  등록 필요.** 회당 비용은 판정 60콜 수준.

## ② 판정 프롬프트 재보정 — 문구별 실측과 확정본

문구를 바꿔가며 민감 샘플 표본(강세 3종·available·diner·정상)으로 실측한
결과, **강세 문구가 조금만 달라져도 SOUND 검출이 죽는 조합**이 반복됐다:

| 변형 | 강세(hiking 등) | available:SOUND | diner 오탐 |
| --- | --- | --- | --- |
| 구 프롬프트 (PoC 검증본 원문) | 미검출 | 3/3 | 상시 |
| V1: 강세 프로토콜 + "even when every phoneme is correct" | 복구 | **0/5 소멸** | 상시 |
| V3a: 예시 없는 확인 지시만 | 도로 죽음 + 이상 오탐 | 2/3 | — |
| V3b: 예시만 유지 | 복구 | 검출되나 STRESS로 오분류 2/3 | 상시 |
| V4: V3b + 강세 위치 판별 규칙 | 복구 | **0/3 소멸** | — |
| **V5 (확정): V3b + SOUND 예시에 "full vowel in place of a reduced one"** | 복구 | 2/3 | **소멸** |

확정본(V5) 골든 5회 (`golden_20260831T052829Z_base.json`, ai-studio 고정):

- **정확일치 58/60 · 오탐 0 · 게이트 통과** (과거 기준 59/60·오탐 1과 대등,
  오탐은 개선). 지연 p50 2.7초.
- STRESS 4종(s1~s4) 전부 5/5 복구. diner 상시 오탐 완전 소멸.
- 잔여 관측 항목: s4_phoneme(available) 3/5 — 과거 13/13 대비 저하지만
  과반 검출로 게이트 통과. 주기 측정에서 추이를 지켜본다.

확장 프롬프트에도 동일 보정을 적용했다 (판정 규칙 동일 유지 원칙). 확장
새니티 1회(`golden_20260831T052929Z_extended.json`): 10/12 — 강세 4종 검출
유지, 실패는 available 미검출(위 잔여 약점)과 compensation 오탐 1회.
운영 탐지는 검증본만 사용하므로 출시 게이트에는 영향 없다.

## 2026-09-02 — 모음 삽입(음절 불리기) 규칙 추가 (V6)

QA 실측 리포트: 한국식 모음 삽입(bus→"버스" 2음절, bad→"배드",
honestly→"어.네.스.틀.리" 5음절)이 전혀 검출되지 않았다. 원인은 프롬프트의
SOUND 정의가 "대치(substitution)"만 다뤄 삽입(epenthesis)이 분류표 밖이었던
것. V5의 SOUND 예시에 삽입 규칙을 덧붙였다 (V6):

> or extra vowel sounds inserted so the word gains syllables (e.g. "bus"
> said as two syllables "bu-seu", ...)

재현율 케이스로 실사용자 녹음 3건을 골든 셋 s5~s7(`*_epenthesis`)에 편입
(참조는 macOS Samantha TTS 합성 — s1~s4의 자산 TTS와 출처가 다름을 유의).
골든 오디오는 개인 음성이라 저장소에 커밋하지 않고(.gitignore 유지) S3
비공개 경로에 보관한다 — CI는 golden-eval.yml이 평가 직전 내려받고, 로컬은:
`aws s3 sync s3://landit-content-982529430654/golden/pronunciation/audio docs/tasks/LAN-209/audio`

프로바이더 고정(ai-studio) 조건 실측, 각 5회:

| 케이스 | V5 (기준) | V6 (+삽입 규칙) |
| --- | --- | --- |
| s6 bad→"배드" | 0/5 미탐 | **5/5** |
| s5 bus, s7 honestly | 5/5 | 5/5 유지 |
| 골든 STRESS 4종 | 유지 | 유지 (놓침 0) |
| s4_phoneme(available) — V5 잔여 약점 | **0/5 (완전 사멸 확인)** | **5/5 복구** |
| s4_correct | 5/5 | 4/5 — available:SOUND 오탐 1회 |

판단: 유일한 부작용(s4_correct의 available 오탐)은 s4_phoneme의 진탐 5/5와
같은 단어·같은 유형이라 문구로 분리 억제가 어렵고(억제 시 진탐 동반 사멸
위험), "놓침이 오탐보다 나쁘다"는 제품 기준에 따라 수용한다. develop
프롬프트(고정·보정 이전) 대비 실험에서도 동일한 삽입 효과가 재현됐다.

확정본(V6) 골든 5회 (`golden_20260902T081421Z_base.json`, ai-studio 고정):

- **정확일치 72/75 · 놓침 0 · 게이트 통과.** 지연 p50 3.3초.
- 신규 s5~s7(epenthesis) 15/15, STRESS 4종 전부 유지, s4_phoneme(available)
  잔여 약점 5/5 완전 복구 — 놓침이 전 케이스에서 0이 된 첫 측정.
- 불일치 3건은 전부 s4_correct의 available:SOUND 오탐(3/5) — 위에서 수용한
  트레이드. 오탐률이 표본에 따라 1/5~3/5로 흔들리므로 주기 측정에서 추이를
  지켜보고, 상승 시 s4_correct 녹음 자체의 경계성(available 모음)을 재검수한다.
