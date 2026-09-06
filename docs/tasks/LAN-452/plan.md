# LAN-452 Structured Outputs 적용 기록

## 목표와 적용 원칙

JSON 응답을 요구하는 LLM 호출에 기존 Pydantic 모델 기반 strict JSON Schema를 전달한다. Structured Outputs 이후에도 기존 Pydantic 검증, 점수·근거 일관성 검증, 캐시와 API fallback 계약을 그대로 실행한다. 프롬프트의 평가·생성 기준과 FastAPI 응답 DTO는 변경하지 않는다.

공통 변환기는 Pydantic validation schema를 복사한 뒤 모든 object에 `additionalProperties: false`를 넣고 모든 property를 `required`에 포함한다. nullable 필드는 JSON Schema의 null union으로 유지한다.

## JSON 응답 호출 조사와 결정

| 영역 | LLM 호출 | 변경 전 형식 | 결정과 schema 원본 |
| --- | --- | --- | --- |
| 시나리오 | `next-message` | 프롬프트로 JSON 요구, 서버 JSON 파싱 | 적용. `NextMessageResponse`. |
| 시나리오 | `inner-thought`와 repair | 프롬프트로 JSON 요구, 서버 JSON 파싱 및 계약 검증 | 적용. `InnerThoughtCandidate`. |
| 시나리오 | `closing-message` | 프롬프트로 JSON 요구, 서버 JSON 파싱 | 적용. `ClosingMessageResponse`. |
| 시나리오 | `message-feedback` 생성·repair·review·review repair | 프롬프트로 JSON 요구, Pydantic과 근거·점수 비즈니스 검증 | 적용. `MessageFeedbackCandidate`를 확장한 내부 출력 모델. `detectedPatterns`도 schema에 포함한다. |
| 시나리오 | `session-feedback` | 프롬프트로 JSON 요구, 서버 계산 점수와 LLM 요약 결합 | 적용. LAN-438 기준과 같은 서버 계산 경계를 유지하고 `SessionFeedbackSummary`만 구조화한다. |
| 프리톡 | opening, turn과 continue repair, closing과 title repair, inner-thought와 repair | 공통 `json_object` | 적용. 각 후보 Pydantic 모델. emotion처럼 서버가 응답에서 사용하지 않는 필드도 현재 프롬프트 계약의 enum 또는 null로 명시한다. |
| 프리톡 | conversation excerpts와 repair, expression recommendations | 공통 `json_object` | 적용. `_ExcerptSelection`, `_RecommendationSelection`. |
| 프리톡 | memory candidates, memory resolution | 공통 `json_object` | 적용. 임베딩을 제외한 후보 모델과 resolution evidence 모델. 임베딩은 계속 서버가 생성한다. |
| 프리톡 | embedding API 호출 | 벡터 응답 | 대상 아님. Chat Completions JSON 응답이 아니다. |
| 발음 | compare, accent check, error description | 오디오 멀티모달, 프롬프트 JSON, 전용 parser와 제한 재시도 | 이번 전환에서는 유지. 실제 endpoint는 단순 strict schema와 오디오 조합을 지원했지만, 17초 전체 예산·단계별 선택 fallback·골든셋 품질 경계가 별도이므로 schema 적용은 발음 품질 회귀 검증과 함께 분리한다. |
| 개발 스크립트 | `poc_pronunciation.py`, `poc_pronunciation_v2.py` | 오디오 멀티모달 PoC | 운영 API 호출이 아니므로 유지. |

## 실패, 재시도, fallback

- Structured Outputs 응답이 malformed JSON이면 공통 계층에서 같은 schema로 최대 2회 시도한다. `inner-thought`는 기존 생성·repair 각 1회가 같은 형식 재시도 역할을 하므로 예외적으로 그 예산을 유지한다.
- Pydantic schema 위반은 기억·표현 추천처럼 별도 복구가 없는 API에서 최대 2회 시도한다. `message-feedback`과 프리톡 excerpt는 첫 응답을 기존 계약 repair로 넘긴다. opening·turn·closing은 기존의 필드 무시·정규화·안전 응답 정책으로 넘겨 API 계약을 유지한다.
- Provider가 `response_format`, `json_schema`, Structured Outputs 또는 호환 endpoint 부재를 400·404·422로 명시하면 그 요청만 기존 방식으로 한 번 fallback한다. 시나리오는 프롬프트 JSON, 프리톡은 `json_object`를 사용한다.
- timeout과 일반 Provider 장애는 형식 미지원으로 오인하지 않고 기존 `AI_GENERATION_FAILED` 계약으로 전달한다.
- Pydantic 및 비즈니스 검증 실패는 기존 API 정책을 유지한다. `message-feedback`은 `202 FAILED`, 프리톡 계약 오류는 502, 생성 실패는 503, 속마음과 일부 생성 API는 기존 안전 문구 fallback을 사용한다.
- 범용 괄호·따옴표 보정은 추가하지 않았다. Structured Outputs 경로는 JSON 전체를 그대로 파싱하며, Provider 미지원 fallback에서만 시나리오의 기존 객체 추출 로직이 남는다.

로그는 원문 응답이나 prompt를 남기지 않는다. `json_format_failure`, `schema_validation_failure`, `structured_output_retry`, `structured_output_fallback`, `contract_validation_failure` 이벤트를 workflow, provider, model, attempt, maxAttempts, 비민감 reason과 함께 기록한다. 시나리오 `message-feedback`의 기존 `validationType=STRUCTURE|CONSISTENCY|EVIDENCE|DISPLAY` 로그도 유지한다. API 접근 로그를 분모로 사용하면 endpoint별 형식 실패율을 계산할 수 있고, retry와 fallback 이벤트 수를 각각 집계할 수 있다.

## 실제 OpenRouter 스모크 테스트

2026-09-06에 익명 텍스트와 0.4초 무음 WAV로 실행했다. 운영 DB와 배포 환경은 사용하지 않았다.

| 모델 / endpoint | 입력과 schema | 결과 | 지연 |
| --- | --- | --- | --- |
| `openai/gpt-5.4-mini` / OpenAI | 텍스트, 단순 strict schema | 성공 | 820ms |
| `openai/gpt-5.4` / OpenAI | 텍스트, 단순 strict schema | 성공 | 1,042ms |
| `openai/gpt-5.4-mini` / OpenAI | 실제 `NextMessageResponse` schema | 성공, Pydantic 검증 통과 | 1,382ms |
| `openai/gpt-5.4` / OpenAI | 실제 message-feedback schema | 성공, Pydantic 검증 통과 | 1,967ms |
| `google/gemini-3.5-flash` / Google AI Studio 고정 | 오디오 멀티모달, 단순 strict schema | 성공 | 2,153ms |

`require_parameters: true`를 넣은 `openai/gpt-5.4-mini`와 `openai/gpt-5.4` 요청은 모두 404 `No endpoints found that can handle the requested parameters`로 실패했다. 따라서 운영 요청에는 이 옵션을 추가하지 않는다. Google AI Studio 오디오 호출도 `require_parameters: true`에서 빈 결과가 한 번 발생했고, 해당 옵션을 제거하고 기존 `reasoning.effort=low`와 Provider 고정을 유지했을 때 정상 JSON을 반환했다.

위 수치는 각각 1회 스모크 결과라 운영 성능 비교값으로 사용하지 않는다. 배포 전후 형식 성공률, retry·fallback 비율, latency와 token 비용 비교는 동일 익명 fixture를 반복 실행하거나 운영 메타데이터 집계로 측정한다. 현재 코드와 테스트는 배포 또는 운영 트래픽 결과를 증명하지 않는다.

## 검증 기록

- strict schema 생성, malformed JSON 1회 재시도, Provider 미지원 fallback, timeout 비-fallback을 단위 테스트한다.
- 기존 테스트의 schema 위반, 비즈니스 규칙 위반, 안전 fallback 및 오류 상태 검증을 유지한다.
- 전체 unittest와 FastAPI OpenAPI schema snapshot 성격의 기존 테스트 결과를 최종 검증에 기록한다.
