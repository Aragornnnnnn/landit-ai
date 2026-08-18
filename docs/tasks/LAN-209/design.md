# LAN-209 발음 연습 기능 — 설계

표현 학습(writing_expression)에 발음 연습 단계를 추가한다. 유저가 대표 예문을
소리 내어 읽으면 음성을 Gemini 2.5 Flash(OpenRouter 경유)로 분석해 **발음(음소)·강세**
오류를 단어 단위로 피드백하고, 틀린 단어만 재녹음해 전부 통과하면 다음 단계로 진행한다.

플로우: 대표 예문 퀴즈 → 표현 설명 → **발음 연습(게이트)** → 추가 예문 → 복습 영작

## 확정 결정사항

| 항목 | 결정 |
| --- | --- |
| 분석 모델 | Gemini 2.5 Flash (OpenRouter 경유), 동기 호출 |
| 판정 범위 | 발음(음소) + 강세. 억양 제외 |
| 문장 통과 기준 | 실제 정확도 93% 이상 (UI는 100%로 올림 표시, 저장은 실제 점수) |
| 단어 재녹음 통과 기준 | 해당 단어 음소·강세 오류 0 (모델 판정 신뢰) |
| 재시도 | 무제한. 탈출구는 건너뛰기(상시 노출) |
| 악센트 | `en-US`로 시작. 테이블은 `en-GB` 확장 가능 구조 |
| 정답 기준 데이터 | CMUdict 기반 DB 사전 구축. 모델은 "기준 대비 오류 감지"만 수행 |
| 코칭 문구 | 음소 혼동 쌍별 템플릿 테이블 사전 구축. 런타임 LLM 생성 없음 |
| 유저 상태 | 서버 미저장. 단어별 통과 상태는 앱 메모리 관리 (이탈 시 처음부터 — 기존 정책 동일) |
| 유저 음성 | 서버 미저장. 분석 후 폐기. "내 발음 듣기"는 앱 로컬 녹음 재생 |
| 원어민 음성 | TTS 사전 생성 → S3 (타겟 표현·문장·단어 3종) |
| 실시간 STT 자막 | 온디바이스 STT (백엔드 무관) |
| 구버전 앱 | 강제 업데이트 없음. 구버전은 기존 플로우 유지 |

## DB 변경 (백엔드 API 서버 저장소에서 진행)

### 신규 `writing_expression_pronunciation` — 정답 발음 기준

`UNIQUE (writing_expression_id, accent_locale)`

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| id | bigint PK | Y | 발음 기준 PK |
| writing_expression_id | bigint FK | Y | 대상 표현 |
| accent_locale | varchar(35) | Y | `en-US` 등 |
| sentence_text_snapshot | text | Y | 생성 당시 대표 예문. 원문 변경 감지용 |
| target_expression_audio_url | varchar(500) | Y | 타겟 표현 TTS |
| sentence_audio_url | varchar(500) | Y | 문장 TTS |
| words_payload | jsonb | Y | 단어별 발음 기준 배열 |
| status | enum(VARCHAR(20)) | Y | ACTIVE, INACTIVE |
| created_at, updated_at | timestamp(6) | Y | |

`words_payload` 항목:

```json
{
  "order": 2,
  "word": "nothing",
  "phonemes": "N AH1 TH IH0 NG",
  "syllables": ["nuh", "thing"],
  "stressIndex": 0,
  "display": "nuh·thing",
  "audioUrl": "https://cdn.landit.com/pronunciation/words/nothing_en-US.mp3"
}
```

- `phonemes`: CMUdict 표기. 모델 판정 기준용 (UI 비노출)
- `syllables`/`display`: 학습자용 respelling. 강세 음절 모음에 악센트 (`hík·ing`)
- `stressIndex`: 강세 음절 인덱스. 문장 내 무강세 기능어는 `-1`

### 신규 `pronunciation_analysis_log` — 판정 이력 (유저 비노출, 운영용)

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| id | bigint PK | Y | |
| user_profile_id | bigint FK | Y | |
| writing_expression_id | bigint FK | Y | |
| analysis_type | enum(VARCHAR(20)) | Y | `SENTENCE`, `WORD` |
| target_word | varchar(100) | N | WORD일 때 대상 단어 |
| target_word_order | int | N | 동일 단어 중복 등장 대비 |
| overall_score | int | N | 실제 점수 0~100. SENTENCE만 |
| passed | boolean | Y | |
| result_payload | jsonb | Y | 판정 전문 |
| created_at | timestamp(6) | Y | |

`result_payload.words[]` 항목 (분석 API 응답도 동일 구조 + 코칭 문구):

```json
{
  "word": "nothing", "order": 2, "ok": false,
  "errorType": "PHONEME",
  "expectedPhoneme": "TH", "actualPhoneme": "S",
  "userDisplay": "nuh·ssing",
  "errorTargetSpan": "th", "errorUserSpan": "ss"
}
```

강세 오류는 `"errorType": "STRESS", "userStressIndex": 1`.
`errorTargetSpan`/`errorUserSpan`은 발음 표기에서 빨강+밑줄 처리할 부분.

### 신규 `pronunciation_coaching_template` — 코칭 문구

`UNIQUE (error_type, expected_phoneme, actual_phoneme, base_locale)` (partial unique index)

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| id | bigint PK | Y | |
| error_type | enum(VARCHAR(20)) | Y | `PHONEME`, `STRESS`, `FALLBACK` |
| expected_phoneme | varchar(10) | N | 예: `TH` |
| actual_phoneme | varchar(10) | N | 예: `S` |
| base_locale | varchar(35) | Y | `KR` |
| coaching_text | text | Y | `{syllable}` 등 치환 변수 허용 |
| retry_coaching_text | text | N | 재시도 실패 문구 |
| status | enum(VARCHAR(20)) | Y | |
| created_at, updated_at | timestamp(6) | Y | |

### 기존 수정 `writing_expression` — 컬럼 추가

`nuance_comparison_payload` (jsonb, N): 표현 설명 화면의 뉘앙스 비교 카드.
null이면 카드 미노출.

```json
{
  "plain":  { "sentence": "It's really good.",        "feeling": "그냥 '좋다' 정도의 평범한 느낌" },
  "target": { "sentence": "There's nothing like it!", "feeling": "'이만한 게 없다!' — 독보적으로 최고라는 느낌" }
}
```

## AI 서버(이 저장소) 신규 API 스케치

- `POST /api/v1/pronunciation/sentence-analysis` — 오디오 + 기준 데이터(words_payload) →
  점수·단어별 오류·코칭 문구
- `POST /api/v1/pronunciation/word-analysis` — 오디오 + 대상 단어 기준 → 통과/실패·재시도 문구

상세 요청/응답 스키마는 PoC 결과 반영 후 확정한다.

## 작업 순서

1. PoC — 판정 일관성 검증 (`plan.md` 참고)
2. 테이블 확장 (백엔드 API 서버 저장소, Flyway + Entity)
3. API 문서
4. respelling 데이터 + TTS 3종 생성 → S3
5. 코칭 템플릿·뉘앙스 카드 콘텐츠 (LLM 초안 → 사람 검수)
6. CSV 취합 → 검수 → insert
7. 본격 개발
