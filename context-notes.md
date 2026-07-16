# Context Notes

## 2026-06-28

- 저장소는 `LICENSE`만 있는 초기 상태였다.
- 패키징은 별도 도구 강제 없이 표준 `pyproject.toml` 기반으로 시작한다.
- 테스트는 요청 스펙에 맞춰 `unittest`만 사용한다. FastAPI `TestClient`는 추가 의존성인 `httpx`가 필요할 수 있어 초기 설정 범위에서 제외했다.
- OpenAI SDK는 실제 네트워크 호출 없이 클라이언트 생성 지점만 둔다. API 키가 없으면 명시적으로 실패시켜 설정 누락을 빨리 드러낸다.
- Sentry는 `SENTRY_DSN`이 있을 때만 초기화한다. 로컬 기본 실행에서 외부 전송을 만들지 않기 위함이다.
- 이 환경은 `python` 명령이 없고 `python3.12` 명령만 확인되었다. 의존성이 설치된 저장소 검증 명령은 `.venv/bin/python -m unittest discover -s tests`로 맞춘다.
- FastAPI 0.138.1에서는 `app.routes`에 `path` 속성이 없는 내부 라우터 객체가 포함된다. 라우트 등록 검증은 공개 스키마인 `app.openapi()["paths"]` 기준으로 한다.
- `.venv/bin/python -m unittest discover -s tests` 기준으로 설정 기본값, `/health` 등록, 헬스체크 반환값, OpenAI API 키 누락 가드를 검증한다.
- 기존 AGENTS.md를 AI 저장소에 맞게 옮길 때는 `Project Context`와 `AI Server Code Convention`의 내용만 AI 서버 기준으로 바꾸고, 나머지 공통 개발 규칙은 원문 그대로 유지한다.
- 이번 작업은 사용자 지시로 Notion 이슈 번호 없이 진행한다. 대신 `origin/develop` 기준 `feat/llm-config` 브랜치에서 작업한다.
- 현재 저장소는 SSM 직접 조회 패턴이 없고, Pydantic Settings가 환경변수와 `.env`를 읽는 구조다. OpenRouter 관련 SSM 값을 애플리케이션이 직접 읽지 않고 배포/IaC 단계에서 env var로 주입하는 전제로 둔다.
- OpenRouter 설정은 `LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`을 읽는다. API key는 `SecretStr`로 받고 테스트에는 fake placeholder만 사용한다.
- `.env.example`의 빈 `OPENROUTER_API_KEY`가 유효한 키처럼 통과하지 않도록 클라이언트 생성 시 빈 문자열과 공백 문자열을 누락으로 처리한다.
- 남은 결정 사항은 배포/IaC 단계에서 `/landit/develop`과 `/landit/prod` SSM 값을 어떤 런타임 env 주입 방식으로 연결할지, 실제 `OPENROUTER_MODEL` 값을 환경별로 무엇으로 둘지다.
- LAN-43 dev Worker 배포 workflow는 새 배포 프레임워크 없이 GitHub Actions, Dockerfile, ECR push, ECS `update-service --force-new-deployment`만 둔다. task definition 재등록과 Terraform 실행은 하지 않는다.
- 로컬 환경에는 Docker CLI가 없어 Docker build 검증은 실행하지 못했다. `.venv/bin/python -m unittest discover -s tests`는 통과했다.
- dev Worker 배포 workflow는 push 자동 실행 없이 개발자가 GitHub Actions UI에서 `workflow_dispatch`로 직접 실행한다.
- prod Worker 배포 workflow도 `workflow_dispatch`만 사용한다. 단, `GITHUB_REF`가 `refs/heads/main`이 아니면 즉시 실패시켜 prod 배포를 main 브랜치로 제한한다.
- dev Worker 배포 설정 값은 GitHub `develop` environment variables를 기준으로 읽는다. 이미지 태그는 `ECR_REGISTRY/ECR_REPOSITORY` 조합에 commit SHA와 `latest`를 붙여 push한다.
- ECR 업로드 검증은 `docker push` 성공으로 판단한다. `ecr:DescribeImages` 권한이 없는 배포 role에서도 ECS update까지 진행하기 위해 별도 `describe-images` 단계는 두지 않는다.

## 2026-07-06

- LAN-66 문서 보강은 기존 `README.md`와 `AGENTS.md`를 삭제하거나 새로 만들지 않고 현재 내용을 기준으로 보강한다.
- 새 서비스 이름은 Landit으로 정리한다. 문서의 `landit-ai`는 패키지와 앱 이름으로만 유지하고, 서비스 설명은 Landit AI Server 기준으로 쓴다.
- 현재 구현된 public API는 `GET /health`뿐이다. `next-question`, `turn-feedback`, `session-feedback`, `guide`는 AI 서버가 맡을 생성 책임의 방향으로만 문서화하고, 이미 구현된 API처럼 쓰지 않는다.
- 현재 코드 구조는 `app/main.py`, `app/api/health.py`, `app/core/config.py`, `app/core/openai_client.py`, `app/core/sentry.py` 중심이다. 아직 `conversation`, `domain`, `llm`, `prompts`, `postprocess`, `scoring` 패키지는 없다.
- 현재 LLM 호출 경계는 `app/core/openai_client.py`의 OpenAI SDK 클라이언트 생성이다. provider는 `openrouter`만 허용하고, API key가 없거나 비어 있으면 실패한다.
- AI 서버는 세션, 턴, DB 저장, 완료 상태를 직접 소유하지 않는 stateless FastAPI 서버 방향으로 문서화한다. 해당 상태 책임은 Landit backend에 둔다.
- 문서에는 과한 Clean Architecture, LangChain, Redis, Celery, AI 서버 DB, 불필요한 interface/port/repository 추상화를 기본 선택지로 쓰지 않는다고 명시한다.
- 전역 `python3.12 -m unittest discover -s tests`는 FastAPI 의존성을 찾지 못해 실패했다. 이 저장소의 실행 가능한 검증 명령은 `.venv/bin/python -m unittest discover -s tests`로 둔다.
- `.venv/bin/python -m unittest discover -s tests` 기준 8개 테스트가 통과했다.

## 2026-07-06 LAN-66 공통 응답과 에러 처리

- 현재 public API는 `GET /health`뿐이며, health는 ALB/ECS 헬스체크 호환을 위해 plain `{"status": "ok"}` 응답을 유지한다.
- 공통 응답 래퍼는 앞으로 추가될 외부 HTTP 생성 API 경계에만 적용하고, LLM 내부 응답이나 prompt 결과까지 감싸지 않는다.
- 새 의존성 없이 FastAPI exception handler, Pydantic 모델, unittest, 이미 설치된 FastAPI TestClient만 사용한다.
- 현재 `app/core/sentry.py`에는 Sentry 초기화 함수만 있고 별도 capture helper는 없다. 예상하지 못한 예외 handler는 secret이나 사용자 입력 전문을 로그로 남기지 않는다.
- 공통 응답 테스트는 구현 전 `app.common` import 실패로 RED를 확인했다.
- exception handler 테스트는 구현 전 `ApiException` import 실패로 RED를 확인했다.
- `.venv/bin/python -m unittest discover -s tests` 기준 14개 테스트가 통과했다.
- 이 환경에는 `python` 명령이 없어 `python -m compileall app tests`는 실행되지 않았다. 대체 명령 `.venv/bin/python -m compileall app tests`는 통과했다.

## 2026-07-07 ECS 배포 검증 fail-fast 개선

- 사용자가 `origin/develop` 직접 수정을 요청해 별도 이슈 브랜치 없이 `develop`에서 작업한다.
- 기존 Worker deploy workflow는 `aws ecs wait services-stable` 동안 중간 deployment 상태와 ECS 이벤트를 충분히 보여주지 못했다.
- `Verify ECS service`는 최대 10분 동안 15초 간격으로 service 상태를 출력하고, PRIMARY deployment가 `FAILED`가 되면 최근 ECS 이벤트를 출력한 뒤 즉시 실패한다.
- step-level `timeout-minutes`는 12분으로 둔다. 루프가 직접 10분 실패를 반환하고 이벤트를 출력할 시간을 남기기 위해서다.
- Worker workflow에는 외부 health check URL이 없으므로 API 서버처럼 curl 검증은 추가하지 않는다.
- workflow만 변경했으므로 애플리케이션 테스트 대신 GitHub Actions YAML parse와 `git diff --check`로 검증한다.

## 2026-07-08 LAN-95 다음 AI 메시지 생성 API

- 작업 브랜치는 사용자 요청에 따라 `feat/LAN-95`로 만든다.
- SayNow 참고 기준은 로컬 `develop`이 아니라 `/Users/sangmin8817/Soma/saynow-ai`의 `origin/develop` 커밋 `6cf01f3`이다.
- 프롬프트는 기능이 같은 속마음 정책, 안전 정책, 응답 JSON 정책을 SayNow 문구 중심으로 가져온다. 초기에는 자유 생성으로 보았지만, 사용자 정정 후 SayNow의 `Fixed Question Policy`도 가져오는 방향으로 바꾼다.
- Landit AI Server는 stateless 경계를 유지한다. SayNow의 turn feedback cache, 대량 후처리, fallback 응답 생성은 이번 요구사항과 맞지 않아 추가하지 않는다.
- LLM 응답 필드 누락, blank 값, enum 오류, JSON 파싱 실패는 `AI_RESPONSE_INVALID` 502로 처리한다.
- OpenRouter 호출 자체 실패, 설정 누락, 빈 모델명은 `AI_GENERATION_FAILED` 503으로 처리한다.
- `next-message` 성공 응답도 기존 Landit 공통 응답 계약에 맞춰 `data` 안에 `aiMessage`, `translatedMessage`, `innerThought`, `innerThoughtType`, `goalCompletionStatus`를 담는다.
- `.venv/bin/python -m unittest discover -s tests` 기준 18개 테스트가 통과했다.
- 사용자 정정으로 `next-message`의 다음 질문은 자유 생성이 아니라 SayNow `origin/develop`의 `nextQuestion`과 같은 고정 질문 체계로 본다.
- 요청에는 `nextQuestion.questionId`, `nextQuestion.sequence`, `nextQuestion.questionEn`, `nextQuestion.questionKo`를 추가한다.
- LLM은 짧은 acknowledgement를 붙일 수 있지만, `aiMessage`에는 `questionEn`, `translatedMessage`에는 `questionKo`가 그대로 포함되어야 한다.
- 고정 질문 누락 응답은 응답 계약 오류로 보고 `AI_RESPONSE_INVALID` 502로 반환한다.
- 고정 질문 체계 반영 후 `.venv/bin/python -m unittest discover -s tests` 기준 19개 테스트가 통과했다.
- 리뷰에서 `submittedMessageId`, `submittedTurnNumber`가 `conversationHistory`의 방금 제출된 사용자 메시지와 일치하는지 검증하지 않는 문제가 확인되었다.
- `next-message`는 사용자가 방금 제출한 메시지를 기준으로 다음 고정 질문 응답을 만드는 API이므로, 히스토리 마지막 메시지가 해당 `USER` 메시지와 일치하지 않으면 요청 검증 오류로 처리한다.

## 2026-07-08 LAN-96 대화 종료 메시지 생성 API

- 작업 브랜치는 `feat/LAN-95` 현재 HEAD에서 `feat/LAN-96`으로 분기했다.
- SayNow 참고 기준은 `/Users/sangmin8817/Soma/saynow-ai`의 `origin/develop` 커밋 `6cf01f3`이다.
- 기능상 같은 closing prompt 문구는 SayNow 문구를 최대한 그대로 가져오되, Landit 명세의 `conversationHistory` 기반 요청에 맞춘다.
- 요청은 전체 `conversationHistory`를 받는다. 서비스는 마지막 `USER` 메시지와 직전 `AI` 메시지를 SayNow의 `currentTurn`처럼 파생해 프롬프트에서 강조한다.
- `submittedMessageId`, `submittedTurnNumber`는 마지막 `USER` 메시지와 일치해야 하며, 마지막 사용자 메시지 직전에는 `AI` 메시지가 있어야 한다.
- SayNow는 invalid LLM 응답을 fallback/repair로 보정하지만, LAN-96은 명세대로 필드 누락 또는 꼬리 질문 정책 위반을 `AI_RESPONSE_INVALID` 502로 처리한다.
- LLM 호출 실패와 설정 누락은 Landit 기존 `next-message`와 같이 `AI_GENERATION_FAILED` 503으로 처리한다.
- 성공 응답은 bare object가 아니라 Landit 공통 응답 래퍼 `ApiResponse[ClosingMessageResponse]`에 담는다.
- FastAPI OpenAPI 스키마에서 `/api/v1/conversation/closing-message` 경로가 노출되는 것을 확인했다.

## 2026-07-08 LAN-96 리뷰 점검

- `INVALID_REQUEST` 기본 메시지가 LAN-96 명세의 "잘못된 요청입니다."와 달라 공통 에러 기본 문구를 맞췄다.
- `next-message`와 `closing-message`의 OpenAI 호출, 예외 변환, JSON 파싱 흐름이 중복되어 `_request_json_completion`으로 공통화했다.
- closing prompt 본문은 SayNow `origin/develop`의 closing system prompt를 유지하고, Landit 요청 구조 차이 때문에 user prompt만 전체 `conversationHistory` 기반으로 구성한다.

## 2026-07-08 LAN-97 메시지별 피드백 생성 API

- 작업 브랜치는 현재 `feat/LAN-96` HEAD에서 `feat/LAN-97`로 분기했다.
- SayNow 참고 기준은 로컬 `develop`을 `origin/develop`으로 동기화한 `/Users/sangmin8817/Soma/saynow-ai`의 `origin/develop` 커밋 `6cf01f3`이다.
- SQS, worker, retry, DLQ는 나중에 한 번에 처리하기로 했으므로 LAN-97에서는 HTTP API 요청 안에서 LLM 생성과 cache 저장까지 수행한다.
- 성공 응답은 HTTP 202와 Landit 공통 응답 래퍼 `ApiResponse[MessageFeedbackResponse]`를 사용한다.
- cache는 Redis나 DB 없이 TTL 있는 in-memory dict로 구현한다. 추후 최종 피드백 생성에서 읽을 수 있도록 내부 `store`, `get`, `get_expected`, `clear` helper만 둔다.
- API 명세의 필드명과 enum은 사용자가 준 LAN-97 명세를 기준으로 한다. SayNow의 `turnId`, `sequence`, `koreanAnalogy`는 Landit의 `messageId`, `messageSequence`, `baseLocaleAnalogy`로 맞춘다.
- SayNow의 turn-feedback 프롬프트와 GOOD, NEEDS_IMPROVEMENT 판단 정책은 기능상 동일하므로 최대한 재사용한다.
- 필수 필드 누락이나 조건부 필드 정책 위반은 SayNow처럼 기본값으로 보정하지 않고 `AI_RESPONSE_INVALID` 502로 처리한다. 단, 프롬프트 품질에 영향을 주지 않는 문자열 trim이나 framing prefix 제거는 허용한다.
- `detectedPatterns`와 점수 breakdown은 LAN-97의 캐시 저장 계약에는 필요하지 않아 저장하지 않는다. 모델이 `detectedPatterns`를 반환해도 현재는 계약 검증 전에 버리고, 최종 피드백에서 실제 필요성이 확인되면 그때 추가한다.
- 메시지별 피드백 생성은 route, DTO, service, cache helper를 기존 `next_message_service.py`와 `conversation.py`에 추가해 최소 변경으로 구현한다. 아직 구현체가 하나뿐이므로 별도 repository, interface, worker 계층은 만들지 않는다.
- cache entry 메타데이터를 반환하는 helper는 아직 실제 사용처가 없어 만들지 않는다. 최종 피드백에서 사용자 메시지나 추가 점수가 필요해지면 그때 entry 조회 helper를 추가한다.

## 2026-07-08 LAN-97 리뷰 점검

- `ponytail` 검토 결과 `get_expected_message_feedback_entries`는 아직 실제 사용처가 없는 공개 helper라 제거했다. 최종 피드백 구현 시 entry 메타데이터가 필요하면 그때 추가한다.
- message-feedback 프롬프트는 SayNow 판단 정책을 유지하되, 현재 서버가 저장하지 않는 `detectedPatterns` 출력 요구는 제거했다. 기존 SayNow식 응답이 섞여 들어오는 경우를 대비해 서비스에서는 `detectedPatterns`를 pop으로 무시한다.
- in-memory cache는 현재 HTTP API 범위에서만 쓰는 단일 프로세스 TTL cache다. 여러 인스턴스가 같은 cache 결과를 공유해야 하는 SQS 흐름에서는 외부 저장소로 옮겨야 한다.

## 2026-07-08 LAN-97 문서 구조 분리

- README가 프로젝트 소개, 개발 명령, 아키텍처 방향, API 책임, 운영 원칙을 모두 담으면서 커지고 있어 진입점 문서로 축소한다.
- 아키텍처와 운영 원칙은 `docs/architecture.md`, conversation API 정책은 `docs/api/conversation.md`, 로컬 개발과 검증 명령은 `docs/development.md`에 둔다.
- README에는 현재 public API 목록과 세부 문서 링크만 남겨 이후 API가 늘어나도 README가 비대해지지 않게 한다.

## 2026-07-08 LAN-98 세션 최종 피드백 생성 API

- 작업 브랜치는 `feat/LAN-97` 현재 HEAD에서 `feat/LAN-98`로 분기했다.
- SayNow 참고 기준은 `/Users/sangmin8817/Soma/saynow-ai`의 `develop...origin/develop` 커밋 `6cf01f3`이다.
- SayNow는 session-feedback에서 LLM이 주로 `highlightMessage`만 만들고, `nativeScore`는 캐시된 턴 피드백 기반 서버 계산으로 붙인다.
- Landit은 `summaryMessage`와 `starRating`이 추가된 계약이므로, LLM은 `highlightMessage`, `summaryMessage`만 생성하고 `nativeScore`, `starRating`은 AI 서버가 deterministic하게 계산한다.
- `starRating`은 JSON number로 내려주고 BE는 BigDecimal로 받는다. 허용 값은 `1.0`, `1.5`, `2.0`, `2.5`, `3.0`이다.
- `MESSAGE_FEEDBACK_NOT_READY` 409는 공통 에러 래퍼로 반환하되 외부 응답에는 누락 메시지 ID를 포함하지 않는다.
- 세션 최종 피드백 생성 성공 시 해당 세션 캐시는 삭제하고, 피드백 미준비나 LLM 오류 시 재시도를 위해 캐시를 보존한다.

## 2026-07-11 LAN-93 USER First 메시지별 피드백

- 메시지별 피드백은 별도 API를 추가하지 않고 기존 `POST /api/v1/conversation/message-feedback`를 확장한다. 응답, cache key, 최종 세션 피드백 연결 기준은 그대로 `sessionId`, `messageId`를 사용한다.
- 요청에서 기존 `messageContext`를 제거하고 최상위 `evaluationContext`, `userMessage`를 사용한다. `evaluationContext`는 LLM 내부 prompt와 혼동되지 않는 평가 기준 컨텍스트다.
- 평가 컨텍스트 type은 `AI_MESSAGE`, `SCENARIO_OPENING_INSTRUCTION`만 지원한다. BE는 시나리오 `firstSpeaker`를 기준으로 type을 결정하고 AI 서버는 전달받은 type을 기준으로 평가 정책을 분기한다.
- `messageSequence`는 턴 내부 순번이 아니라 세션 전체 메시지 순번이다. AI 서버는 양수만 검증하며 type별 고정 순번을 강제하지 않는다.
- `SCENARIO_OPENING_INSTRUCTION`은 USER First 첫 발화이므로 `turnNumber == 1`을 검증하고 `translatedContent`는 기준 locale 안내문 정책에 따라 `null`을 요구한다.
- USER First는 시작 안내 수행, 시작 표현의 자연스러움, 문법, 상황 적절성, 상대 역할에 맞는 공손함을 평가한다. AI_MESSAGE의 질문 이해와 답변 관련성은 USER First 평가에서 제외한다.
- 캐시 구조, 재시도, `nativeScore` 가중치, 다중 인스턴스 공유는 LAN-93 범위에 포함하지 않는다. 최종 세션 피드백은 USER First 첫 메시지 ID를 `expectedMessageIds`에 포함하는 별도 후속 범위에서 연결한다.

## 2026-07-11 LAN-93 자체 리뷰 후속 수정

- 타입별 판단 정책은 분리되었지만 공통 Feedback Examples가 AI 질문 응답 상황만 보여줘 opening 평가를 왜곡할 수 있다.
- 출력 필드 정책과 JSON 스키마는 공통으로 유지하고, GOOD와 NEEDS_IMPROVEMENT 예시만 `evaluationContext.type`에 따라 분리한다.
## 2026-07-13 LAN-122 OpenTelemetry 애플리케이션 메트릭

- 작업 브랜치는 `develop`에서 `feat/LAN-122`로 분기했다.
- 세 서비스의 공통 전송 경계를 맞추기 위해 AI 메트릭은 OpenTelemetry OTLP HTTP 직접 전송을 사용한다.
- 로컬과 unittest에서는 기본적으로 계측과 exporter를 비활성화해 외부 네트워크 전송과 background export thread를 만들지 않는다.
- HTTP 메트릭은 FastAPI route template, method, status만 사용하고 `/health`는 제외한다. route 미매칭 요청은 raw path를 route label로 남기지 않는다.
- query string, request/response body, header, 사용자·세션·메시지 ID는 metric attribute로 수집하지 않는다.
- runtime 메트릭은 ECS CloudWatch 지표와 역할이 겹치는 전체 system·disk·network 수집을 제외하고 process와 CPython GC 지표만 수집한다.
- Grafana 인증 header는 코드나 문서에 값을 남기지 않고 ECS secret으로 주입되는 표준 `OTEL_EXPORTER_OTLP_HEADERS` 환경변수에서만 읽는다.
- TDD RED는 OTel 의존성 추가 전 `opentelemetry` import 실패와 의존성 추가 후 `app.core.observability` import 실패로 확인했다.
- 안정화된 HTTP semantic convention을 활성화해야 `http.server.request.duration`에 `http.route`가 포함된다. 계측 활성화 시 `OTEL_SEMCONV_STABILITY_OPT_IN=http`을 기본 적용한다.
- 요청 수는 `http.server.request.duration` histogram의 count로 계산한다. View에는 route template, method, status, low-cardinality error type만 남긴다.
- `InMemoryMetricReader` 기반 테스트로 성공·503 요청, health 제외, unmatched raw path·query·header·ID 미수집, process·CPython GC 지표를 검증했다.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests` 기준 45개 테스트가 통과했다.
- `PYTHONPYCACHEPREFIX=/tmp/landit-ai-lan-122-pycache .venv/bin/python -m compileall -q app tests`와 `.venv/bin/python -m pip check`가 통과했다.

## 2026-07-13 LAN-122 OpenTelemetry 공통 Resource 속성 수정

- 통합 리뷰에서 AI가 `service.name`에 `APP_NAME`을 사용하고 환경 속성을 `deployment.environment`로 내보내 BE·IaC 공통 계약과 불일치하는 문제가 확인되었다.
- 원인은 `Settings`가 표준 `OTEL_SERVICE_NAME`을 읽지 않고, `Resource.create`가 애플리케이션 이름과 구형 환경 key를 직접 사용한 것이다.
- OTel FastAPI 계측은 route 미매칭 요청 자체를 버리지 않지만 raw path를 `http.route`로 사용하지 않는다. 기존 기록의 “route가 매칭되지 않은 요청은 제외한다”는 표현을 실제 동작에 맞게 수정해야 한다.
- `Settings`는 `OTEL_SERVICE_NAME`을 읽고 기본값 `landit-ai`를 사용한다. Resource의 `service.name`은 이 설정을 사용한다.
- 환경 Resource key는 BE·IaC 공통 계약인 `deployment.environment.name`을 사용하고 값은 기존 `APP_ENV`에서 가져온다.
- Resource 불일치 테스트는 수정 전 `otel_service_name` 속성 부재와 `service.name` 값 불일치로 RED를 확인했다.
- 수정 후 전체 45개 unittest, compileall, pip check, diff check가 통과했다.

## 2026-07-13 LAN-122 예상하지 못한 500 오류 로깅

- custom `unexpected_exception_handler`가 예외를 공통 500 응답으로 처리하면 Uvicorn 기본 예외 경로까지 전파되지 않아 CloudWatch와 Loki에 stack trace가 남지 않는다.
- handler에서 `logger.exception`을 호출해 현재 traceback을 Uvicorn error/stdout에 남기되 request body, header, URL, query, secret 같은 요청 값을 log argument로 전달하지 않는다.
- Sentry FastAPI integration의 자동 500 수집을 단일 오류 event 경로로 유지한다. `logger.exception`이 Sentry event를 추가로 만들지 않도록 `LoggingIntegration(event_level=None)`을 명시한다.
- validation, `HTTPException`, `ApiException` 같은 예상 가능한 4xx·도메인 오류는 새 ERROR 로그 대상에 포함하지 않는다.
- 실패 테스트에서 500 처리 시 `uvicorn.error` ERROR 로그가 없고 `LoggingIntegration`이 구성되지 않은 상태를 각각 확인했다.
- 수정 후 대상 7개 테스트에서 500 stack trace 기록, 요청 query·header·body 비노출, 4xx ERROR 로그 제외, Sentry 로그 event 비활성화가 통과했다.
- 전체 48개 unittest, compileall, pip check, diff check가 통과했다.

## 2026-07-13 LAN-122 명시적 5xx 예외 로깅 리뷰 수정

- 코드 리뷰에서 custom `api_exception_handler`와 `http_exception_handler`가 503 같은 명시적 5xx를 응답으로 변환하면서 ERROR log와 traceback을 남기지 않는 경로가 확인되었다.
- 원인은 `unexpected_exception_handler`에만 `logger.exception`이 있고 두 handler는 상태 코드와 관계없이 응답만 반환하는 것이다.
- `ApiException`과 `HTTPException`의 status code가 500 이상일 때만 현재 exception traceback을 `uvicorn.error`에 기록한다. 4xx는 기존과 같이 ERROR 로그를 남기지 않는다.
- request body, header, URL, query를 log argument로 전달하지 않고 `LoggingIntegration(event_level=None)` 정책을 유지한다.
- 실패 테스트에서 두 503 exception 모두 응답은 반환하지만 `uvicorn.error` ERROR 로그가 한 건도 발생하지 않는 RED를 확인했다.
- 두 handler가 공유하는 status code 조건부 helper를 추가한 뒤 대상 8개 테스트에서 5xx traceback, 4xx 무로그, Sentry 중복 방지 설정이 통과했다.
- 기존 503 응답 계약 테스트에 `ApiException` traceback 검증을 합쳐 중복 경로를 제거했다.
- 전체 49개 unittest, compileall, pip check, diff check가 통과했다.

## 2026-07-14 LAN-138 AI 응답 품질 검증 계획

- 현재 마무리 멘트는 `_closing_message_system_prompt()`가 생성 방향을 정하고 `_validate_closing_message_policy()`가 꼬리 질문 같은 형식 위반을 막는다. 실제 자연스러움을 검증하는 품질 사례는 아직 없다.
- 마무리 프롬프트의 예시에 `Let's wrap up here`, `Let's pause here` 같은 메타 종료 문구가 반복된다. 제보된 어색함과 같은 출력으로 이어지는지 수정 전 실제 모델 평가에서 먼저 확인한다.
- 현재 메시지 피드백 프롬프트는 `Actionable Issue Gate`를 두고 있지만, 문법적으로 맞는 `Why do you wanna know that?`도 뉘앙스를 이유로 `NEEDS_IMPROVEMENT` 예시에 고정한다. 실제 오판이 뉘앙스·공손함 기준이나 예시 편향에서 발생하는지 평가 컨텍스트별로 나눠 확인한다.
- unittest는 mock 응답과 프롬프트 계약만 검증하므로 실제 LLM 품질 문제를 단독으로 증명할 수 없다. 비식별화한 고정 사례를 현재 OpenRouter 모델로 반복 실행해 수정 전·후를 비교한다.
- 외부 API 계약과 DTO는 유지하고, 원인이 확인된 프롬프트와 최소한의 응답 정책 검증만 수정한다.
- 계획 작성 시점에는 `.venv`가 없어 시스템 Python 3.12에서 3개 테스트 모듈 import error가 발생했다. 이후 `.venv`를 구성해 저장소 표준 명령으로 검증했다.

## 2026-07-14 LAN-138 마무리 멘트 수정

- 사용자 제보의 `그러면 여기서 대화를 끝내자`는 프롬프트 예시에 있던 `Let's wrap up here`, `Let's pause here`, `여기서 마무리하자`와 같은 메타 종료 패턴이다.
- 프롬프트는 마지막 사용자 발화와 상대 역할, 구체적 상황 안에서 마지막 반응을 생성하도록 바꾸고 메타 종료 예시는 제거한다.
- 메타 종료 문구가 모델 응답으로 다시 오면 `AI_RESPONSE_INVALID` 502로 반환한다. 의미 기반 맥락 검증은 정상적인 동의어를 오판할 수 있어 추가하지 않는다.
- `openai/gpt-5.4-mini`로 마무리 사례 3개를 3회씩 재실행해 새 질문과 메타 종료 문구가 모두 0건인 것을 확인했다.

## 2026-07-14 LAN-138 통합 리뷰 후속 수정

- 품질 평가 도구가 `generate_closing_message()`의 운영 정책 검증에서 먼저 실패하면 원본 후보를 분류할 수 없었다. LLM 호출과 스키마 검증까지만 수행하는 내부 후보 생성 함수를 분리해 평가 도구에서 사용한다.
- 메타 종료 검사는 영문·한글 고정 부분 문자열 목록을 중복 유지하지 않는다. 운영 코드의 정규화된 판정 함수를 평가 도구에서도 공유하고, 스마트 따옴표와 문장 변형은 잡되 `wrap up the gifts` 같은 상황 내 표현은 허용한다.
- 마무리 프롬프트의 `Do not continue the scenario`와 역할 내 마지막 반응 요구가 충돌했다. 새 주제·질문·추가 턴만 금지하도록 바꾸고, 완료 상태별 예시를 실제 상황 반응으로 교체했다.
- 직설적인 구어체 GOOD 사례는 AI가 이유를 설명하지 않은 입력으로 바꿔 판정 근거를 명확히 했다. 특정 사용자 문장을 GOOD 예시에 그대로 반복하지 않고 같은 의도의 다른 문장을 사용한다.
- 이유가 이미 제시된 상황에서도 같은 질문을 `NEEDS_IMPROVEMENT`로 강제하는 실험은 `openai/gpt-5.4-mini`가 3회 모두 자연스러운 확인 발화로 판단했다. 원래 목표인 과도한 감점을 피하기 위해 이 추측성 기준은 채택하지 않았다.
- 최종 평가는 비식별화한 10개 사례를 각 3회 실행했다. 마무리 12회는 질문·메타 종료·기대 맥락 불일치가 모두 0건이었고, 메시지 피드백 18회는 기대 레이블 불일치가 0건이었다.
- 전체 64개 unittest, compileall, pip check, JSON 파싱, diff check가 통과했다.

## 2026-07-14 LAN-138 GOOD 과보정 진단

- 기존 메시지 피드백 suite는 GOOD 4개, NEEDS_IMPROVEMENT 2개여서 GOOD 완화가 반대 방향으로 과보정되는지 충분히 확인하기 어려웠다.
- 문법은 맞지만 AI 질문과 무관한 답변, 교수에게 무례한 거절을 NEEDS_IMPROVEMENT 사례로 추가해 4대4로 맞췄다.
- 평가 결과에는 expectedFeedbackType을 함께 기록한다. 사례별 실제 레이블뿐 아니라 false GOOD과 false NEEDS를 직접 집계하기 위함이다.
- `openai/gpt-5.4-mini`로 8개 사례를 각 5회 실행한 40회에서 기대 GOOD 20회와 기대 NEEDS_IMPROVEMENT 20회가 모두 일치했다. 고정 사례 평가이므로 실사용 분포 보장은 아니며, 실제 제보 문장을 비식별화해 계속 추가한다.

## 2026-07-14 CI 자동 검사 워크플로우

- Landit BE의 CI는 `develop` 대상 PR에서 `opened`, `synchronize`, `reopened`, `edited` 이벤트를 받고 애플리케이션과 배포 스크립트를 검사한다.
- Landit AI는 배포 스크립트가 없으므로 Python 3.12 환경에서 의존성 설치, unittest, compileall, pip check, Docker image build만 수행하는 `Verify application` workflow를 추가한다.
- CI는 `develop`, `main` 대상 PR과 두 브랜치 push에서 실행한다. `edited`는 PR base 변경에도 검사를 다시 시작하기 위해 포함한다.
- 로컬에는 Docker CLI가 없어 Docker build는 실행하지 못했다. YAML 문법과 Python 검사 명령은 로컬에서 통과했고 Docker build는 GitHub-hosted runner에서 확인한다.

## 2026-07-14 LAN-144 다음 메시지·속마음 생성 분리 계획

- 일반 턴은 `landit-be`가 `next-message`와 `inner-thought`를 병렬 호출하고, `landit-ai`는 두 stateless 동기 생성 API만 제공한다.
- `next-message`는 고정 질문 검증과 `goalCompletionStatus` 생성을 유지하며 속마음 필드는 반환하지 않는다.
- `inner-thought`는 전체 히스토리를 맥락으로 참고하되 마지막 사용자 발화만 평가하고, 응답 식별자는 요청값에서 복사한다.
- 상태 전환, polling, 중복 호출 방지, 최초 성공 결과 확정, timeout과 재시도 정책은 BE 책임이다.
- 종료 턴은 기존 `closing-message`를 유지하며 별도 `inner-thought`를 호출하지 않는다.

## 2026-07-14 LAN-144 다음 메시지·속마음 생성 분리 구현

- `next-message`는 `aiMessage`, `translatedMessage`, `goalCompletionStatus`만 OpenRouter에서 생성하고 기존 고정 질문 검증을 유지한다.
- `inner-thought`는 같은 대화 컨텍스트에서 독립적으로 호출하며 마지막 USER 메시지만 평가 대상으로 삼는다.
- LLM 출력은 `innerThought`, `innerThoughtType`으로 제한하고, API 응답의 `sessionId`, `messageId`는 요청 식별자에서 조립한다.
- AI 서버는 상태를 저장하지 않는다. BE가 병렬 호출, `PREPARING` 이후 상태 전환, 중복 호출 방지, 최초 성공 결과 저장을 담당한다.

## 2026-07-16 LAN-166 메시지 평가 근거 기반 세션 점수 산정

- 현재 점수는 `GOOD` 절대 개수로 점수 밴드를 정해 짧지만 상황에 맞는 답변과 긴 답변의 사소한 오류를 충분히 구분하지 못한다.
- 단어 수와 특정 연결 표현은 상황상 짧게 답해야 하는 메시지를 불리하게 만들 수 있어 점수 근거에서 제거한다.
- 메시지별 내부 평가 근거는 `contextFit`, `clarity`, `languageAccuracy`를 각각 0~2로 생성한다.
- 메시지 점수는 `contextFit * 20 + clarity * 15 + languageAccuracy * 15`로 계산하고 완료한 발화는 50~100으로 제한한다.
- `GOOD`은 세 항목이 모두 2일 때만 허용한다. 하나라도 2보다 낮으면 `NEEDS_IMPROVEMENT`로 처리해 피드백과 점수가 같은 판단 근거를 사용하게 한다.
- 세 평가 근거는 strict integer로 검증해 문자열, 실수, 불리언의 점수 강제 변환을 허용하지 않는다.
- 세션 `nativeScore`는 메시지 점수 평균을 반올림한다. 기존 점수별 `starRating` 매핑과 외부 API 계약은 유지한다.
- 평가 근거는 AI 서버의 메시지 피드백 cache entry에만 저장하고 외부 응답과 OpenAPI 스키마에는 노출하지 않는다. 백엔드 DTO와 DB schema는 변경하지 않는다.

## 2026-07-16 LAN-166 실제 대화 점수 백테스트

- 품질 평가 결과에 `scoreEvidence`, 메시지 점수, 기대 점수 범위 일치 여부를 기록해 분류뿐 아니라 점수 경계도 반복 측정할 수 있게 한다.
- 실제 데이터에서 다중 질문의 부분 답변, 짧지만 완결된 답변, 룸메이트에게 거친 표현, 어색하지만 이해 가능한 어휘, 선택형 질문의 유효한 답변을 비식별 회귀 사례로 고정한다.
- `Totally quiet condition`은 뜻을 추측해야 할 정도는 아니므로 `clarity=2`, 어색한 어휘 선택은 `languageAccuracy=1`로 기대한다. 같은 종류의 개선 필요 발화가 세션에서 반복될 때 최종 점수가 높아지는 문제는 메시지 명확성을 중복 감점하지 않고 세션 산정에서 별도로 판단한다.
- 로컬에 `OPENROUTER_API_KEY`가 없어 실제 모델 기준선 수집은 실행하지 못했다. 키가 설정되면 기존 품질 기준선과 같은 `openai/gpt-5.4-mini`로 사례별 3회 평가를 먼저 실행한다.
- `openai/gpt-5.4-mini`로 6개 사례를 각 3회 평가한 초기 기준선에서는 짧지만 완결된 음식 답변을 모두 65점으로 과소평가했고, 거친 룸메이트 답변은 한 번 `GOOD`·100점으로 과대평가했다. 선택형 질문의 두 번째 선택지와 어색하지만 뜻이 분명한 어휘도 문맥 충족도를 불필요하게 낮췄다.
- 점수식은 바꾸지 않고, 짧은 명사구 답변, `or` 질문의 각 선택지, 언어 문제의 중복 감점 금지, 적대적 답변의 공손성 문제를 평가 근거 정책과 동등 사례 JSON 예시로 보강했다.
- 같은 모델과 사례로 최종 3회 평가한 18건에서 기대 피드백 유형은 18건 모두 일치했다. 거친 룸메이트 답변은 질문 의도와 시나리오 목표의 해석 차이를 반영해 기대 점수 범위를 65~85점으로 두었고, 최종 점수 범위도 18건 모두 일치했다.

## 2026-07-16 LAN-166 세션 별점 일관성 보정

- 전체 실제 데이터 20개 세션의 63개 발화를 한 번씩 평가했을 때, `GOOD`이 없거나 1/3인 세션도 원시 점수 평균만으로 2.5점 별을 받았다. 이는 메시지 피드백의 `NEEDS_IMPROVEMENT`와 사용자에게 보이는 세션 별점이 충돌하는 문제다.
- `nativeScore`는 문맥 충족과 의미 전달 정도를 그대로 보존한다. 단, 발화가 3개 이상이고 `GOOD` 비율이 1/3 이하이면 `starRating`만 최대 2.0으로 제한한다. 한두 발화에서 사소한 오류가 있는 경우에는 제한하지 않는다.
- `nativeScore`, `starRating` 응답 필드와 OpenAPI 타입은 바뀌지 않으므로 backend DTO와 DB schema 변경은 필요하지 않다.

## 2026-07-16 LAN-166 benchmarkMessage 근거 검증과 다중 질문 보정

- `detectedPatterns`는 LLM 응답에서 읽되 메시지 피드백 cache와 외부 API 응답에는 저장하거나 노출하지 않는다.
- GOOD의 `benchmarkMessage`는 `status=correct`, catalog 등록, `gamifiable=true`, 실제 사용자 발화에 포함된 `evidence`를 모두 만족하는 경우에만 catalog 문구로 덮어쓴다.
- 검증된 catalog 근거가 없을 때는 LLM의 비정량 문구를 유지한다. 퍼센트, 비율, 횟수 통계, 출처 주장이 포함된 문구나 빈 문구는 기본 문구로 대체한다.
- 사용자 요청에 따라 `app/data/benchmark_patterns.json`에 SayNow `error_patterns.json` 원본 12개 항목을 그대로 복사한다. 원본의 `feedback_copy`는 SayNow와 같은 규칙으로 문장형 `benchmarkMessage`로 변환하며, `SayNow 기획 가설`을 포함한 출처 표기도 원본 값을 유지한다.
- 여러 핵심 질문이 한 평가 컨텍스트에 있으면 모두 충족한 경우에만 `contextFit=2`로 평가한다. 하나만 답하면 `contextFit=1`이며, 짧다는 이유만으로 감점하지 않는다.
- 실제 세션 113의 `I don't know.`, `um... I usually wake up at 9.`, `um... no`는 `openai/gpt-5.4-mini` 재평가에서 모두 `NEEDS_IMPROVEMENT`, `contextFit=1`, 80점으로 나왔다. 3발화 세션의 GOOD 비율은 0이므로 기존 별점 상한 규칙에 따라 세션 별점은 최대 2.0이다.
- 같은 모델로 LAN-166 회귀 사례 9개를 1회 재평가했을 때 피드백 유형과 점수 범위가 모두 일치했다. 기존 `yes I like` 부분 답변은 `contextFit=1`, `languageAccuracy=1`로 65점을 유지했다.

## 2026-07-16 LAN-167 메시지별 피드백 품질 개선

- 작업 브랜치는 최신 `origin/release/LAN-161`에서 `fix/LAN-167`로 분기했다.
- 기존 다중 질문 예시가 사용자 발화에 없던 취침 시간과 룸메이트 생활 기준을 완성 답변에 추가해 모델의 사실 생성을 유도하고 있었다.
- 대문자와 문장부호만 다른 표현, 의미 전달을 방해하지 않는 필러, `like to watch`와 `like watching` 같은 자연스러운 대안 차이는 스피킹 피드백의 개선점으로 삼지 않는다.
- 교정 표현은 사용자 발화의 의미, 의도, 시제, 부정 여부와 이미 나온 사실을 유지한다. 답변 완성에 개인정보가 더 필요하면 `[your hobby]`, `[your bedtime]`, `[your dealbreaker]` 같은 플레이스홀더를 사용한다.
- 사실을 임의로 만들지 않는 기준은 내부 생성 정책이다. `correctionReason`은 빠진 내용과 플레이스홀더에 넣을 정보만 설명하며, `없는 사실`, `사실을 만들지`, `임의로 추측` 같은 내부 정책 표현이 나오면 유효하지 않은 AI 응답으로 처리한다.
- 품질 평가 도구는 최종 메시지별 피드백 필드와 필수 플레이스홀더 누락, 금지 문구 포함 여부를 결과에 기록한다.
- LAN-167 회귀 fixture는 대문자·문장부호, 필러, 유효한 문법 대안, 일부만 답한 자기소개, 문맥과 무관한 답변의 5개 경계를 다룬다.
- 전체 98개 unittest, compileall, pip check, JSON 파싱, diff check가 통과했다.
- 실제 OpenRouter 평가는 평가 사례와 프롬프트가 외부 서비스로 전송되는 작업에 대한 명시적 승인이 필요해 실행하지 않았다.

## 2026-07-16 LAN-167 메시지별 피드백 2단계 검수

- 승인받은 실제 사용자 발화 115개를 현재 모델로 평가한 결과, GOOD 22개 중 9개가 복합 질문을 일부만 답한 과대 판정이었고 NEEDS_IMPROVEMENT 93개 중 55개에서 교정 품질 문제가 확인됐다.
- 중요 사례 14개를 총 3회 평가했을 때 9개는 모든 실행에서 문제가 재현돼 단일 호출 프롬프트 강화만으로는 부족하다고 판단했다.
- 메시지 피드백을 생성 호출과 검수 호출로 분리한다. 검수 호출은 원본 평가 문맥과 생성 후보를 비교해 최종 피드백 전체를 다시 반환한다.
- 검수 단계는 복합 질문 충족, 질문과 교정의 일치, 사용자 사실 보존, 대문자·문장부호만을 근거로 한 교정 금지를 우선 확인한다.
- 검수 호출 또는 검수 결과 검증이 실패하면 이미 계약 검증을 통과한 생성 후보를 사용한다. 생성 단계 실패는 기존처럼 요청 실패로 처리한다.
- 최종 선택된 후보의 `detectedPatterns`만 benchmark catalog 후처리에 사용하며 외부 API 계약과 backend DTO는 변경하지 않는다.

## 2026-07-16 LAN-167 판정·문구 분리와 세션 점수 일관성 재설계

- 전체 피드백을 생성한 뒤 전체 피드백을 다시 검수하는 방식은 실제 중요 사례에서 false GOOD, 사용자 사실 추가, 대문자·문장부호 과교정이 반복됐다. 검수 실패 때 첫 후보를 저장하는 fallback도 이미 확인된 오류를 노출할 수 있어 폐기한다.
- 같은 `openai/gpt-5.4-mini`를 판정 전용으로 사용한 실험은 중요 사례 14개를 3회씩 실행한 42건에서 기대한 `contextFit` 경계를 모두 유지했다. 의미 판정과 문구 작성을 분리하는 근거로 사용한다.
- 첫 호출은 `evaluationContext`의 `coreAsks`, 실제 사용자 발화의 `evidence`와 `statedFacts`, `scoreEvidence`만 생성한다. 시나리오 목표는 이번 발화의 추가 핵심 요청으로 만들지 않는다.
- 서버는 요청 충족 개수와 `contextFit`, 사용자 발화 부분 문자열 근거, 플레이스홀더 형식을 검증하고 세 평가 점수로 `feedbackType`을 확정한다.
- 두 번째 호출은 잠긴 판정을 입력받아 사용자용 피드백 문구만 생성한다. 빠진 개인정보는 `[your reason]`, `[your hobby]` 같은 구체적인 플레이스홀더로 남기고 `correctionReason`은 한국어로 작성한다.
- 정상 경로는 판정과 문구 생성의 2회 호출이다. 문구 생성이나 검증이 실패하면 한 번만 문구 복구를 호출하고, 복구 결과도 유효하지 않으면 요청을 실패시킨다.
- 메시지별 점수식은 유지한다. 1~2개 발화 세션은 기존 평균을 유지하고 3개 이상 세션은 원시 메시지 점수 평균 70%와 GOOD 비율 30%를 반영한다.
- 세션 별점의 별도 GOOD 비율 상한은 제거하고 최종 `nativeScore`에서만 별점을 계산한다. 원시 평균 82점에 GOOD 0/3인 사례는 57점과 별 1.5개가 된다.
- 외부 API, OpenAPI, backend DTO, DB 스키마는 변경하지 않는다. `detectedPatterns`와 benchmark catalog 후처리도 AI 서버 내부 계약을 유지한다.

## 2026-07-16 LAN-167 구현 검증

- 판정 단계는 `coreAsks`, 사용자 발화에 포함된 `evidence`·`statedFacts`, 세 점수만 반환하고 서버가 요청 충족 개수와 `contextFit`을 검증한다. `feedbackType`과 외부 `messageId`는 서버가 확정한다.
- 실제 모델이 출력 스키마 예시의 `messageId=1001`을 반복 복사해 판정이 거부되는 문제가 있었다. 식별자는 요청에서 이미 확정되므로 LLM 출력에서는 선택 항목으로 두고 서버가 요청 `messageId`로 조립한다.
- 문구 생성에는 잠긴 `feedbackType`과 유형별 필수 필드를 명시한다. 반대 유형 전용 필드는 서버가 제거하고, 필요한 필드·플레이스홀더·한국어 이유가 없으면 한 번만 복구 호출한다.
- 다중 질문에서 빠진 내용은 언어 오류와 중복 감점하지 않는다. 문맥과 무관하지만 문법적으로 자연스러운 발화는 `contextFit=0`, `languageAccuracy=2`로 분리한다.
- 고정 품질 사례 7개를 `openai/gpt-5.4-mini`로 각 3회 실행한 21건에서 기대 `feedbackType`, `contextFit`, 점수 범위, 문구 계약이 모두 일치했다. 필수 플레이스홀더 누락과 `relax` 같은 근거 없는 이유 추가도 0건이었다.
- 이전에 제공된 전체 115개 원본 CSV는 현재 실행 환경에서 읽기 권한이 없어 재평가 입력으로 다시 구성하지 못했다. 파일을 다시 첨부하거나 저장소 내부의 비식별 fixture로 제공되면 같은 평가 도구로 바로 실행한다.

## 2026-07-16 LAN-167 실제 115개 발화 재평가와 문구 보정

- 다시 첨부된 CSV에서 115개 사용자 발화와 직전 평가 질문, 시나리오를 추출해 실제 요청 DTO 검증을 통과시켰다. 이전 `GOOD`·`NEEDS_IMPROVEMENT`·`benchmarkMessage`는 정답으로 사용하지 않았다.
- 수정 전 전체 115건의 실제 모델 평가에서는 정상 결과 111건, `AiResponseInvalidError` 4건, `GOOD` 18건, `NEEDS_IMPROVEMENT` 93건이 나왔다. 문구 복구 호출은 1건이었다.
- 실데이터에서 판단 단계가 시나리오 전체를 현재 질문보다 우선해 핵심 질문을 부풀리고, 문구 단계가 `My aircon bill is [your travel proof].`, `I don't know [your recommended place]`처럼 의미에 맞지 않는 플레이스홀더를 붙이는 문제가 확인됐다.
- 판단 단계는 현재 `evaluationContext`만 핵심 질문의 원천으로 쓰고, 불완전한 `My name is`는 이름 답변으로 인정하지 않도록 보강했다. 추천 장소, 증빙, 생활 기준 등 자리표시자 의미도 명시했다.
- 문구 단계는 문맥 적합도 0점에서 불완전 발화를 재활용하지 않고 현재 질문에 직접 답하는 완결 문장을 만들도록 했다. 장소 추천과 이유, 부정 답변 뒤 생활 기준은 각각 검증된 문장 뼈대를 제공한다.
- 실제 모델 재평가에서 `No, but I can't stand [your dealbreaker].`, `I recommend [your recommended place] because [your reason].`가 생성됨을 확인했다. 전체 115건의 최종 프롬프트 재평가는 후속 품질 확인 항목으로 남긴다.
- 재평가 중 `[your wake-up time]`의 하이픈이 내부 플레이스홀더 형식 검증과 충돌해 판단 결과가 거부되는 원인을 확인했다. `[your wake up time]`으로 바꾸고 실제 `Go away` 사례를 3회 재평가해 2회 정상 생성, 1회 문구 형식 실패를 확인했다.
- 하이픈 수정이 영향을 받는 생활 리듬 질문 3건을 다시 실행해 최종 115건 결과를 완성했다. 정상 생성은 108건, 형식 검증 실패는 7건, `GOOD`은 9건, `NEEDS_IMPROVEMENT`는 99건이며 문구 복구 호출은 3건이었다. 실패 응답은 저장하지 않고 요청 실패로 처리된다.

## 2026-07-16 LAN-167 판정 복구 운영 안정화 계획

- 전체 115건 중 형식 검증 실패 7건은 운영 기준으로 높다. 정상 2회 호출은 유지하고, 최초 판정이 `AiResponseInvalidError`로 거부된 경우에만 판정 복구를 한 번 수행한다.
- provider와 네트워크 실패인 `AiGenerationFailedError`는 복구하지 않고 기존 503 계약을 유지한다. 판정 복구도 실패하면 502를 반환하며 검증되지 않은 판정이나 피드백은 cache에 저장하지 않는다.
- 정상 경로는 2회, 판정 또는 문구 한 단계만 복구하면 3회, 두 단계가 모두 복구되면 최대 4회 호출이다. 추가 blind retry는 도입하지 않는다.
- 운영 가능 gate는 같은 115건에서 최종 형식 실패 최대 1건, 고정 21건과 중요 42건의 기존 문구·점수 품질 유지, 외부 API와 OpenAPI 계약 유지로 정한다.

## 2026-07-16 LAN-167 판정 복구 운영 검증 결과

- 판정 JSON·스키마·근거 검증이 `AiResponseInvalidError`로 실패한 경우에만 판정 복구를 한 번 수행하도록 구현했다. 복구 결과도 유효하지 않으면 기존 502로 종료하고, provider·네트워크 실패는 복구하지 않고 기존 503을 유지한다.
- 판정 복구 사용 여부는 내부 cache와 품질 평가 결과의 `judgementWasRepaired`에만 기록한다. 외부 응답과 OpenAPI에는 노출하지 않는다.
- `.venv/bin/python -m unittest discover -s tests`에서 102개 테스트가 통과했다. compileall, pip check, OpenAPI 회귀, diff check도 통과했다.
- 현재 커밋 상태의 고정 품질 사례 21건에서는 최종 형식 실패가 0건이었지만, 1건에서 사용자가 말하지 않은 `relax`가 교정 표현에 추가됐다.
- 모호한 이유의 문맥 판정과 의미 보존을 프롬프트로 추가 보강하는 실험을 수행했지만, 같은 사례에서 `relaxing`이 다시 생성되고 문법적으로 자연스러운 무관 답변의 점수가 흔들려 해당 실험 변경은 커밋하지 않았다.
- 실험 프롬프트를 포함한 중요 사례 42건에서는 최종 형식 실패 0건, 판정 복구 1건, 문구 복구 2건이었다. 핵심 GOOD/NEEDS 판정과 주요 플레이스홀더는 유지됐지만, 296번과 56번에서 사용자 근거에 없는 이유가 일부 생성됐다.
- 같은 실험 상태의 전체 115건에서는 최종 형식 실패 3건, 판정 복구 2건, 문구 복구 2건, GOOD 10건, NEEDS_IMPROVEMENT 102건이었다. 최종 실패는 306번, 233번, 155번이며 모두 최초 문구와 문구 복구 결과가 연속으로 거부된 사례다.
- 기존 최종 형식 실패 7건보다 줄었지만 운영 gate인 최대 1건을 충족하지 못했다. 두 번째 blind retry는 추가하지 않고, 문구 검증 실패 원인 코드와 사용자 근거 기반 의미 보존 검증을 다음 설계 대상으로 남긴다.
