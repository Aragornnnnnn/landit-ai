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
