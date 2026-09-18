# LAN-518 — 프리톡 턴별 교정 문장 생성 설계

## 1. 결정

`POST /api/v1/free-talk/inner-thought` 응답에 두 값을 얹는다.

- `correction`: 제출된 사용자 턴에서 가장 어색한 **한 문장**의 교정(원문·교정문·기준 언어 이유·실수 패턴). 고칠 게 없으면 `null`.
- `reactedToPartner`: 직전 상대 말을 받아준 뒤 자기 얘기를 했는지. 직전 상대 말이 없는 첫 턴은 정의상 `true`.

교정은 **같은 엔드포인트 안의 별도 작은 LLM 호출**로 만든다. 공유 속마음 프롬프트(`app/common/inner_thought_prompt.py`)와
계약(`app/common/inner_thought_contract.py`)은 시나리오 도메인과 공유되고 `innerThought` 안의 문법·교정·피드백 언어를
금지하므로 건드리지 않는다. 장기기억을 교정 근거로 쓰는 것(`memoryContext`, `usedMemoryId`)은 [AI] 장기기억 활용 이슈 범위다.

## 2. 실행 구조

`generate_inner_thought`(`app/free_talk/application/conversation_service.py`)가 오케스트레이터다.

1. 교정 호출(`generate_turn_correction`, `app/free_talk/application/correction_service.py`)을 워커 스레드에 먼저 던진다.
2. 속마음 호출은 요청 스레드에서 기존 그대로(repair 1회 포함) 실행한다.
3. 교정 future를 `free_talk_correction_timeout_seconds`(기본 6초) 데드라인까지만 기다린다. 같은 값이 교정 호출의 SDK
   타임아웃(재시도 0회)이다.
4. 응답 시간은 max(속마음, 교정) 수준이다. 교정은 보조 판정이라 절대 엔드포인트를 실패시키지 않는다.

교정 호출 입력은 `targetLocale`, `baseLocale`, 직전 상대 메시지, 제출 메시지뿐이다. 전체 히스토리·주제·페르소나는 넣지 않는다.
`free_talk_correction_model`로 교정만 다른 모델에 맡길 수 있다(비우면 `OPENROUTER_MODEL`).

## 3. 실패 정책 (조용한 기본값 금지)

교정 호출 실패·타임아웃·JSON 계약 위반·`originalSentence` 원문 불일치 시 `correction = null`, `reactedToPartner = null`로
내려주고 WARNING 로그 한 줄(`workflow=free_talk_turn_correction_fallback reason=… sessionId messageId fields`)을 남긴다.
문장·프롬프트 텍스트는 로그에 쓰지 않는다. `true`로 채우지 않는다. v1은 교정 호출에 repair를 두지 않는다.

`originalSentence`는 서버가 제출 원문 안에서 찾아 원문 조각으로 교체한다(대소문자·공백 차이 허용, 구두점 차이는 불허).
원문과 교정문이 같으면 "고칠 것 없음"으로 본다(반응값은 유지).

## 4. 실수 패턴 (16 + OTHER, 고정)

세션을 가로질러 비교하는 성장 카드의 이름표이므로 고정 목록이다(`FreeTalkMistakePattern`).

| 코드 | 화면 이름 | 예 |
| --- | --- | --- |
| TENSE | 시제 | I go to the gym yesterday → went |
| SUBJECT_VERB_AGREEMENT | 주어-동사 일치 | She like it → likes / I is → am |
| VERB_FORM | 동사 형태 | enjoy to go → enjoy going / I am agree → I agree |
| ARTICLE | 관사 | at a gym(서로 아는 곳) → the gym |
| PLURAL | 단수/복수 | two friend → friends / many money → much money |
| PRONOUN | 대명사 | my sister… he → she |
| PREPOSITION | 전치사 | go to home → go home |
| NEGATION | 부정문 | I not go → I didn't go |
| QUESTION_FORM | 질문 만들기 | You like it? → Do you like it? |
| WORD_ORDER | 어순 | Always I go there → I always go there |
| MISSING_WORD | 빠진 말 | Yesterday very tired. → I was very tired yesterday. |
| REDUNDANCY | 군더더기 | 같은 말 두 번 → 한 번 |
| WORD_CHOICE | 단어 선택 | burning calories → cardio |
| LITERAL_TRANSLATION | 한국어 직역 | my mind is heavy → I feel down |
| REGISTER | 말투 | Give me water → Could I get some water? |
| NATURALNESS | 더 자연스러운 표현 | 문법은 맞지만 원어민이 안 쓰는 말 (문법 오류가 없을 때만) |
| OTHER | 기타 | |

한 문장에 여럿이면 이해를 가장 방해하는 것 하나만 태그한다. 우선순위는 프롬프트 `Mistake Patterns:` 절의 나열 순서다.
철자·대소문자·구두점·필러·축약형·STT 흔적은 고치지 않는다. 성장 카드에서 OTHER·NATURALNESS·REGISTER를 제외하는 규칙은 BE 이슈 메모다.

## 5. 배포 순서

요청·응답 모델이 `extra="forbid"`이므로 **AI 서버를 먼저 배포**하고, 백엔드가 새 응답 필드를 저장하기 시작한다.
이번 이슈는 요청 필드를 추가하지 않으므로 백엔드 배포 전에도 기존 요청은 그대로 동작한다.

## 6. 검증

- `tests/test_free_talk_correction_api.py`: 교정 있음/없음, 원문 정규화, 원문 불일치, 계약 위반 4종, 호출 실패, 타임아웃,
  첫 턴 정의, 동일 문장, 프롬프트 내용, 모델·타임아웃 전달, OpenAPI 스키마.
- `tests/test_free_talk_correction_rules.py`: 원문 대조 규칙.
- 기존 속마음 테스트는 fake가 교정 호출을 프롬프트 마커로 분리 라우팅해 무수정 통과한다.

### 실제 OpenRouter 검증 (2026-09-18, `openai/gpt-5.4-mini`)

운영 모델은 SSM 조회 권한이 없어 LAN-452 스모크의 텍스트 기본 모델로 가정했다. 발화 50개(멀쩡한 발화 20, 실수 발화 30,
각 4~5문장, 직전 상대 말 포함) × 3회 = 150회. 프롬프트 v1 → v2(한 문장만 고르기·바뀐 단어 명시·추임새 없는 직접
답변도 반응으로 인정) 비교. 스크립트와 결과는 레포 밖 스크래치에만 두었다.

| 항목 | v1 | v2 |
| --- | --- | --- |
| 판정 실패(null) | 0/150 | 0/150 |
| 3회 판정이 흔들린 발화 | 6/50 | 5/50 |
| 멀쩡한 발화 오교정 | 1/60턴 | 3/60턴 |
| 실수 발화 교정 놓침(1회 이상) | 5/30 | 4/30 |
| 실수 발화 기대와 다른 패턴(1회 이상) | 4/30 | 2/30 |
| `reactedToPartner` 3회 일치 | 48/50 | 49/50 |
| `originalSentence`가 두 문장 이상 | 3/80건 | 1/84건 |
| `reason`이 바꾼 단어를 안 짚음 | 31/80건 | 1/84건 |
| 응답 시간 p50 / p90 / max (동시 6) | 1.49 / 2.21 / 4.09초 | 1.44 / 2.06 / 2.92초 |

남은 흔들림은 라벨이 원래 애매한 문장(`How was there?`, `I ate my mind`)과 구어에서 통하는 문장(`You like big dogs
or small dogs?`, `there's a lot of cafes`)이다. v2에서 `Can I get you anything?`에 `Give me water.`로 답한 발화의
반응이 3/3 false로 바뀐 것은 정책과 어긋나므로 운영 로그에서 관찰한다.
