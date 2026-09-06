# LAN-373 발음 평가 AI 서버 구현

## 배경

원어민 표현 학습에 발음 평가 기능을 추가한다. LAN-209 PoC에서 파이프라인이 확정됐다:

- **판정**: `google/gemini-3.5-flash` (OpenRouter 경유) — 원어민 TTS 오디오 + 유저 음성을 **한 요청에 넣고 오디오끼리 대조**, 다른 단어만 보고. temperature 0, reasoning effort low. 골든 셋 24/24 정확 일치, 오탐 0, 지연 p50 4.5초
- **타임스탬프**: torchaudio `WAV2VEC2_ASR_BASE_960H` 강제 정렬 — 정답 문장을 아는 상태에서 오디오에 정렬, 단어별 start/end 산출. 오차 0.01~0.04초, CPU 0.1초/파일. 외부 API 아님(서버 내부 함수)
- **참조 음성**: 표현·문장·단어 3종 TTS를 사전 생성해 S3/CDN 배포, 판정 시 대조 기준으로 재사용
- 모델 학습·파인튜닝 없음. 재현 코드: `scripts/poc_pronunciation_v2.py`, 실험 로그: `docs/tasks/LAN-209/plan.md`, 판정 원본: `docs/tasks/LAN-209/poc_results/`

백엔드(Spring)가 유저 음성을 받아 AI 서버를 호출하고, AI 서버는 판정 결과만 반환한다. 점수 계산·코칭 문구·통과 판정은 백엔드 담당이므로 **AI 서버는 하지 않는다**.

## 작업 1 — 발음 분석 API (핵심)

BE가 호출할 내부 엔드포인트를 만든다.

```
POST /internal/v1/pronunciation/analyze
```

**Request** (multipart 또는 JSON+오디오 전달 방식은 기존 BE↔AI 통신 컨벤션에 맞출 것):

| 필드 | 설명 |
| --- | --- |
| userAudio | 유저 발화 녹음 (m4a·wav·mp3, ≤30초) |
| sentenceText | 정답 문장 (예: "There's nothing like hiking to clear my head.") |
| referenceAudioUrl | 사전 생성된 문장 TTS의 URL (대조 기준) |
| words | 단어 배열 (order 포함, 정렬·판정 기준) |

**Response**:

```json
{
  "words": [
    { "order": 1, "word": "There's", "status": "CORRECT", "startMs": 120, "endMs": 480 },
    {
      "order": 2, "word": "nothing", "status": "PHONEME_ERROR",
      "startMs": 500, "endMs": 940,
      "userDisplay": "nuh·ssing", "errorTargetSpan": "th", "errorUserSpan": "ss",
      "userStressIndex": null
    },
    {
      "order": 4, "word": "hiking", "status": "STRESS_ERROR",
      "startMs": 1200, "endMs": 1750,
      "userDisplay": null, "errorTargetSpan": null, "errorUserSpan": null,
      "userStressIndex": 1
    }
  ]
}
```

내부 처리:

1. **Gemini 판정**: PoC 확정 설정 그대로 (오디오 대조 모드, temperature 0, reasoning low). 기준 텍스트를 주고 판정하는 모드는 앵커링 환각으로 탈락했으니 쓰지 말 것
2. **wav2vec2 강제 정렬**: 전체 단어의 startMs/endMs 산출. **컷 규칙을 서버에서 보정해서 반환**: start−30ms ~ min(end+50ms, 다음 단어 start−10ms). (20ms 페이드아웃은 앱 담당이라 제외)
3. 두 결과를 order 기준으로 병합

성능 목표: 전체 p50 5초 이내 (Gemini 4.5초 + 정렬 0.1초 + 오버헤드). BE 타임아웃이 20초다.

## 작업 2 — Gemini 출력 확장 (PoC 미검증 구간, 품질 검증 필수)

PoC에서 검증된 출력은 **오류 단어 + 유형(SOUND/STRESS)뿐**이다. UI 요구사항 때문에 아래 3개를 추가로 받아야 한다:

1. `userDisplay` — 유저 발음이 어떻게 들렸는지 respelling (예: nothing → "nuh·ssing")
2. `errorTargetSpan` / `errorUserSpan` — 원어민 표기와 유저 표기에서 다른 구간 (예: "th" vs "ss")
3. `userStressIndex` — STRESS 오류 시 유저가 힘준 음절 인덱스 (0-base)

프롬프트를 확장하고 **PoC 골든 셋(24케이스)으로 회귀 검증**할 것:

- 기존 판정 성능(24/24, 오탐 0)이 유지되는지
- 추가 필드가 실제 오류와 일치하는지 (예: th→s 오발음 샘플에서 userDisplay가 s 계열로 나오는지)
- 확장 후 지연이 p50 5초를 넘지 않는지 (넘으면 reasoning effort 등 조정 실험)

검증 결과가 나쁘면 확장 필드를 빼고 "오류 단어+유형만" 반환하는 폴백 스펙으로 보고할 것.

## 작업 3 — TTS 사전 생성 파이프라인

표현별로 3종을 생성해 S3에 업로드하는 배치/스크립트:

1. **표현 음성** (target expression, 예: "There is nothing like")
2. **문장 음성** (대표 예문 전체) — 판정 대조 기준 + 앱 "원어민 발음 듣기" 재생용
3. **단어별 음성** (문장의 각 단어) — 오류 단어 카드의 "원어민" 재생용

- 키 구조 예: `tts/expressions/{expressionId}/sentence.mp3`, `tts/expressions/{expressionId}/words/{order}-{word}.mp3`
- 생성 결과(URL 목록)를 BE가 저장할 수 있는 형태로 출력
- 단어 음성은 문장 TTS에서 잘라내지 말고 단어 단위로 따로 생성할 것 (자연스러운 단독 발음 필요)

## 작업 4 — 발음 기준 데이터 사전 생성

문장이 고정 콘텐츠이므로 단어별 기준 데이터를 미리 만들어 BE에 제공:

- `nativeDisplay`: 원어민 respelling (예: "nuh·thing")
- `syllables` + `stressIndex`: 음절 분해와 강세 위치 (예: ["hik","ing"], 0) — 사전(CMU dict 등) 기반, AI 호출 불필요

## 하지 않는 것

- 점수 계산, 통과 판정, 코칭 문구 생성 (BE 담당)
- 유저 음성 저장 (판정 후 폐기)
- 녹음 품질 게이트 (앱 담당)
- 모델 학습·파인튜닝
- Azure Pronunciation Assessment A/B (별도 백로그)

## 완료 기준

- [ ] analyze API가 위 계약대로 동작 (골든 셋 통과 + 응답 스키마 검증)
- [ ] 확장 필드(userDisplay/span/userStressIndex) 품질 검증 리포트
- [ ] 지연 p50 ≤ 5초 실측
- [ ] TTS 3종 생성 파이프라인 + 샘플 표현 1개 실제 S3 업로드 확인
- [ ] 기준 데이터(respelling/음절/강세) 생성 스크립트 + 샘플 출력
