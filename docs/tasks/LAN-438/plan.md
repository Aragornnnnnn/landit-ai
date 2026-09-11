# LAN-438 평가 근거 보완

## 승인 범위

2026-09-05 사용자 승인. 질문별 판정 → 가중 평균 → 영역 가중치 → 종합 상한 구조를 유지한다.
AI rubric 구현과 BE 계산·저장 구현은 파일이 겹치지 않는 독립 단위다.

## 구현 계약

- AI는 Notion 상세 평가 루브릭의 5개 영역별 Level 1~5 기준을 실제 프롬프트에 포함한다. 요청·Core 형식은 유지한다.
- BE의 confidence는 정답 확률이 아닌 가중 관찰 비율이다. 각 영역이 서로 다른 답변 2개 이상에서 관찰되고 관찰 비율이 0.75 이상일 때만 sufficientEvidence=true다.
- 모든 영역의 근거가 충분해야 최초 초기화 또는 2회 승급 정책에 참여한다. 부족한 결과는 수준과 streak를 보존하며 NOT_APPLIED다.
- 유효한 Core는 부분 관찰이어도 MODEL로 저장한다. 관찰하지 않은 영역 score는 null, confidence는 0이다. 일부 영역이 없으면 assessedScore/assessedLevel은 null이다.
- FALLBACK은 측정값을 만들지 않는다. displayLevel은 assessedLevel → 당시 currentLevel → 3 순서로 결과 화면의 숫자를 제공하며, sufficientEvidence=false이면 예비 결과로 표시한다.
- nullable 측정값과 충분성 스냅샷은 user_level_assessment에 저장한다. 프로필과 평가 저장 트랜잭션·세션 멱등성을 유지한다.
- 시나리오 1의 기존 질문 3그룹 9개에 의미 기반 응답 요소를 등록한다. 질문·번역·음원은 보존한다. 나머지 질문의 기존 초안은 수동 보정 대상임을 문서화한다.
- 같은 메타데이터 보정으로 실제 요구도를 반영한다. 질문 1·124·125는 MEDIUM(소개 상세 또는 선호 설명), 2는 HIGH(관심을 갖게 된 경위), 3·121·122·123·126은 LOW(이름·활동·장소 단일 응답)다. 질문 그룹 자체를 요구도로 간주하지 않으며, 질문 3에는 이유 설명을 추가 요구하지 않는다. V82 실행 테스트로 9개 매핑과 질문·번역 보존을 확인한다.
- 루브릭과 정책 변경 버전은 text-level-v1.1이다. 사람 검증 전 경계 사례는 초안으로만 표시한다.

## 검증과 문서

- [x] AI `.venv/bin/python -m unittest discover -s tests` 성공. 474개 실행, 7개 건너뜀. 프롬프트 연결·레거시 호환·Core/Details 경계와 OpenAPI 회귀 포함.
- [x] rebase 후 BE `./gradlew check` 성공. 899개 테스트, 실패·건너뜀 0. 부분 평가 API/DB 저장·재조회, 초기화 차단, 승급 정책, V82 실제 SQL 실행·9개 매핑·기존 문구 보존 포함.
- [x] 독립 Sol 검수 완료. 단일 요구를 완수한 짧은 답도 상황 수행 L3에 포함하도록 루브릭과 prompt 회귀 검증을 보완했다. 요구도 변경 근거와 전체 매핑 테스트를 명시해 두 지적을 해소했다.
- [x] Notion 10개 문서의 역할을 유지하며 계약·예시·정책을 갱신하고 내용과 검토일을 재조회했다. 실제 평가 정확도 및 FE 구현 완료로 표기하지 않았다.
- [x] 코드 변경을 논리 커밋으로 분리했다. AI 1001384·f28a316, BE 0e5e48a9·0d1b2ad8. 이 검증 기록은 별도 문서 커밋한다.

## 기준 문서

- [평가 모델](https://www.notion.so/3d0146843266817abd32e5f3bf02630f)
- [상세 루브릭](https://www.notion.so/3d0146843266811cb636db3e61104073)
- [API·Fallback](https://www.notion.so/3d01468432668126b336e69c3e84d1f5)

## 한계

자동 테스트는 계산·저장·오류 격리를 검증한다. 실제 LLM의 수준 정확도와 평가자 일치도, 운영 PostgreSQL 적용, FE 표시·결제 E2E를 증명하지 않는다. 별도 네트워크 LLM 호출과 배포는 수행하지 않는다.

## 로컬 블라인드 baseline

- 2026-09-06 실제 develop 모델 설정으로 네트워크 baseline을 실행했다.
- 결과와 판단은 [blind-baseline.md](blind-baseline.md)를 기준으로 한다.
- 제품 평가 60회 중 유효 Core는 15회였고, 45회는 최종 평가 invalid JSON으로 실패했다.
- 평가 프롬프트·가중치·임계값은 baseline 동안 변경하지 않았다.

## JSON 형식 안정화

- 최종 평가 요청에 `strict JSON Schema` 구조화 출력을 적용했다.
- 전체 응답이 파싱되지 않거나 Core 검증에 실패하면 같은 입력과 루브릭으로 Core만 1회 재요청한다.
- 재요청도 실패하면 AI 응답은 `levelAssessment=null`로 복구한다. BE의 기존 fallback이 `FALLBACK`·`NOT_APPLIED`로 저장하고 결제 흐름의 응답을 유지한다.
- 메시지 ID, 5개 영역, 근거 원문 포함 여부를 검사하는 기존 서버 검증은 유지했다. Details 실패는 유효한 Core를 버리지 않는다.
- OpenRouter의 `require_parameters` 라우팅 옵션은 사용하지 않는다. `openai/gpt-5.4-mini`에 해당 옵션과 strict schema를 함께 보냈을 때 사용 가능한 endpoint가 없어 404가 발생했고, 옵션 없이 strict schema를 보낸 실제 호출은 성공했다.
- 평가 프롬프트·가중치·임계값은 변경하지 않았다.
- 동일 60회 후속 회귀에서 유효 Core는 59/60이었다. invalid JSON은 45건에서 0건으로 감소했고, Core 재요청 4건 중 3건을 복구했다.
- 남은 1건은 JSON 형식 오류가 아니라 `evidenceExcerpt`가 사용자 원문의 연속 부분 문자열이 아니어서 기존 근거 검증이 거부했다. BE 적용 시 `FALLBACK`·`NOT_APPLIED`다.
- 정상 대화 첫 실행은 29/30, 봉인 검증은 20/20이 유효했다. 반복 표본 10개는 모두 3회 평가됐고 수준 범위는 최대 1이었다.
- 블라인드 실행기는 호출 성공과 유효 Core를 분리 집계하며, Core 누락을 fallback 실패 지표에 포함한다.

## 비동기 평가·JSON 출력 호환 구현 결과

- 2026-09-07 승인된 계획을 구현했다. 기존 세션 피드백 응답은 유지하고 수준 평가를 별도 API로 분리했다.
- 단일 실행 계획은 BE `docs/tasks/LAN-438/plan.md`의 「비동기 수준 평가·JSON 호환 처리 수정 계획」이다. 로컬 작업 경로는 `/Users/sangmin8817/Soma/landit-be/.worktrees/LAN-438`이며 기본 BE checkout과 구분한다.
- AI에는 캐시 독립 `POST /api/v1/conversation/session-level-assessment`와 기존 루브릭·Core/Details 검증을 추가했다. BE는 기존 `applicationTaskExecutor`로 평가를 비동기 실행하고 `GET /api/v1/sessions/{sessionId}/level-assessment`에서 상태를 조회한다.
- 출력 모드 전환은 명시적 미지원일 때만 `strict json_schema → json_object → 프롬프트 JSON`으로 진행한다. 어느 경로도 Pydantic·ID·근거 원문 검증을 생략하지 않는다. Core 무효의 1회 복구와 최종 BE fallback은 별개다.
- Core 재요청은 마지막으로 선택된 출력 모드를 이어받고, Details 오류는 유효한 Core를 보존한다. BE fallback은 수준·streak를 변경하지 않는다.
- 리뷰 보완: 수준 평가의 모든 호출은 100초 deadline을 공유하며 남은 시간을 SDK timeout으로 전달하고 자동 재시도는 0으로 제한한다. 호출 전후 기한을 검사한다. 잘못된 스키마와 미지원 키워드 오류는 출력 모드 전환에서 제외한다.
- 추가 회귀 포함 AI 테스트는 483개 실행, 7개 skipped로 통과했다. 실제 외부 LLM 재측정은 실행하지 않았다.
- 검증: AI `479 tests, 7 skipped` 통과, BE `./gradlew check --no-parallel` 통과. 운영 DB·배포·실제 FE/결제 E2E는 실행하지 않았다.
- 루브릭·평가 가중치·임계값·제품 모델 변경, 다른 API의 공통 JSON 기능 중복 구현, 운영 DB·배포는 이 계획에 포함하지 않는다.

## PR 리뷰 보완 (2026-09-07 KST)

- 최초·Core 재요청 평가 프롬프트에 공유 안전 정책을 적용한다. 발화 속 지시문은 실행하지 않으며 루브릭은 유지한다.
- 전체 호출 예산은 `SESSION_LEVEL_ASSESSMENT_BUDGET_SECONDS`(기본 100초)로 설정한다. BE timeout 및 PREPARING 만료보다 짧아야 하며 BE timeout을 줄이면 함께 조정한다.
- 블라인드 fixture의 ID 고유성·split·repeat·답변 타입을 호출 전에 검증한다. 기존 manifest와 데이터·모델·루브릭·프롬프트·평가 버전이 다르면 실행을 중단한다.
- baseline의 300회 호출·토큰은 제품 전용이고 기준 평가 40회는 별도로 명시한다.
- 전체 unittest 488개 실행, 7개 건너뜀으로 통과했다. 안전 정책 보강 후 실제 LLM 평가는 재실행하지 않았다.

## 독립 평가 경로 블라인드 재측정 준비

- 실행기를 `generate_session_level_assessment()`로 전환했다. 턴 피드백 4회와 최종 피드백 생성·캐시 준비를 제거해, 비용과 지연은 독립 수준 평가 및 그 복구 호출만 집계한다.
- 계측 SDK factory는 제품 호출의 `timeout` 키워드를 그대로 전달한다. 평가 모델·루브릭·가중치·임계값은 변경하지 않았다.
- manifest에 실제 대상 endpoint, 최초 평가·Core 재요청 프롬프트 해시를 기록한다. 이전 결합 경로 manifest를 새 실행에 재사용하면 중단한다.
- `--reference-dir`은 새 결과 디렉터리에 기준표만 복사한다. 데이터·질문·루브릭·기준 모델·평가 버전 일치, 40개 ID의 완전성, 성공 응답의 근거를 검증한다. 원본 경로·파일 해시를 기록하고 기존 출력은 덮어쓰지 않는다.
- 이전 기준표 manifest에는 기준 프롬프트 해시가 없다. 재사용 시 이 제한을 `legacyPromptFingerprintMissing`에 명시한다. 이는 새 사람 평가나 새 독립 모델 검증을 대체하지 않는다.
- 재사용 기준표의 비용은 과거 비용으로 분리하고 이번 지출·신규 기준 모델 호출 수에는 포함하지 않는다.
- 검증: 전체 unittest 490개 실행, 7개 건너뜀으로 통과했다.
- 후속 실제 60회 실행 완료: 유효 Core 57/60, 첫 실행·초기화 가능 38/40, holdout 20/20, invalid JSON 0/69. 남은 3건은 비연속 근거 인용으로 최종 null이 되어 BE fallback 대상이다.
- 추가 지출 $0.34522725, 수준 평가 전용 지연 p50 5.199초·p95 12.313초. 상세 결과는 [blind-baseline.md](blind-baseline.md)의 「독립 수준 평가 경로 재측정」과 `blind-independent-*.json`에 기록했다.

재측정 명령은 저장소 루트에서 실행한다. 기존 40개 입력 및 10개 반복 표본의 추가 20회를 사용한다.

```sh
.venv/bin/python -m scripts.evaluate_onboarding_level_blind product \
  --cases tests/fixtures/lan_438_onboarding_blind_cases.json \
  --output-dir /private/tmp/lan438-independent-full60-20260907 \
  --reference-dir /private/tmp/lan438-structured-full60-20260906 \
  --product-model openai/gpt-5.4-mini \
  --reference-model google/gemini-3.5-flash
.venv/bin/python -m scripts.evaluate_onboarding_level_blind score \
  --cases tests/fixtures/lan_438_onboarding_blind_cases.json \
  --output-dir /private/tmp/lan438-independent-full60-20260907 \
  --product-model openai/gpt-5.4-mini \
  --reference-model google/gemini-3.5-flash
```
