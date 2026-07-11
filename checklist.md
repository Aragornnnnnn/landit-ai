# Checklist

- [x] 저장소 현재 상태 확인.
- [x] 초기 설정 범위와 가정 정리.
- [x] 구현 계획 문서 작성.
- [x] context-notes.md 생성.
- [x] pyproject.toml, .env.example, .gitignore, README.md 생성.
- [x] unittest 기반 실패 테스트 작성.
- [x] 실패 테스트 실행으로 RED 확인.
- [x] 최소 FastAPI 앱 구조 구현.
- [x] unittest 재실행으로 GREEN 확인.
- [x] 최종 diff와 검증 결과 확인.
- [x] 의미 있는 단위 커밋 생성.
- [x] AI 서버용 AGENTS.md 작성 범위 확인.
- [x] Project Context와 AI Server Code Convention만 AI 서버 기준으로 변환.
- [x] 문서 변경 diff 검토.
- [x] 이슈 번호 없이 진행하기로 사용자 예외 확인.
- [x] `feat/llm-config` 작업 브랜치 생성.
- [x] 기존 LLM provider, env, secret 관리 방식 조사.
- [x] OpenRouter env 설정 변경 계획 작성.
- [x] OpenRouter 설정 RED 테스트 작성 및 실패 확인.
- [x] OpenRouter 설정 구현.
- [x] env 예시를 secret 없는 placeholder로 갱신.
- [x] unittest 검증 실행.
- [x] 변경 파일과 남은 결정 사항 정리.
- [x] dev Worker 배포 workflow 요구사항 확인.
- [x] repo 구조, Dockerfile, 기존 workflow, git 상태 조사.
- [x] 최소 Dockerfile과 GitHub Actions workflow 작성.
- [x] unittest 검증 및 Docker build 가능 여부 확인.
- [x] git diff와 status 확인.
- [x] prod Worker 수동 배포 workflow 추가.
- [x] prod 배포를 main 브랜치에서만 실행하도록 제한.
- [x] dev Worker workflow가 GitHub `develop` environment 변수를 읽도록 변경.

## 2026-07-06 LAN-66 문서 보강

- [x] `README.md`와 `AGENTS.md`를 끝까지 읽음.
- [x] 현재 코드 구조, `/health` API, 설정, OpenAI client, Sentry, 테스트, 배포 workflow 확인.
- [x] `README.md`에 Landit AI Server 역할, 아키텍처 방향, 디렉터리 구조, API 책임, 개발/검증 명령, 운영 원칙 보강.
- [x] `AGENTS.md`에 작업 규칙, 의존성 방향, stateless 원칙, LLM 호출 규칙, 테스트 규칙, 보안/로그 규칙, 추가하지 말아야 할 것 보강.
- [x] `README.md`와 `AGENTS.md`를 다시 읽고 충돌 여부 확인.
- [x] `.venv/bin/python -m unittest discover -s tests` 실행.
- [x] 최종 diff와 git 상태 확인.
- [x] 문서 변경 커밋 생성.

## 2026-07-06 LAN-66 공통 응답과 에러 처리

- [x] `README.md`, `AGENTS.md`, 현재 앱 구조와 테스트 파일 확인.
- [x] 공통 응답 helper 테스트를 먼저 추가하고 실패 확인.
- [x] `app/common/response.py`, `app/common/errors.py` 추가.
- [x] exception handler 테스트를 먼저 추가하고 실패 확인.
- [x] `app/common/exception_handlers.py` 추가.
- [x] `app/main.py`에서 exception handler 등록.
- [x] README.md에 공통 응답 형태만 짧게 보강.
- [x] `.venv/bin/python -m unittest discover -s tests` 실행.
- [x] `python -m compileall app tests` 또는 가능한 대체 명령 실행.
- [x] `git diff --check` 실행.
- [x] 최종 diff와 git 상태 확인.
- [x] 변경 커밋 생성.

## 2026-07-07 ECS 배포 검증 fail-fast 개선

- [x] `origin/develop` 기준 워크플로우 확인.
- [x] dev/prod Worker `Verify ECS service` 단계에 bounded wait와 ECS 이벤트 출력 추가.
- [x] YAML 문법과 diff 검증.
- [x] 논리 단위 커밋 생성.

## 2026-07-08 LAN-95 다음 AI 메시지 생성 API

- [x] `feat/LAN-95` 브랜치 생성.
- [x] Landit 현재 API, 설정, 공통 에러 응답 구조 확인.
- [x] SayNow `origin/develop`의 다음 질문/속마음 프롬프트 구조 확인.
- [x] `next-message` 요청/응답 DTO 실패 테스트 작성.
- [x] LLM 응답 형식 오류 502 테스트 작성.
- [x] LLM 생성 실패 503 테스트 작성.
- [x] 최소 구현으로 `POST /api/v1/conversation/next-message` 추가.
- [x] README 또는 관련 문서에 API 반영.
- [x] `.venv/bin/python -m unittest discover -s tests` 실행.
- [x] 최종 diff와 git 상태 확인.
- [x] 논리 단위 커밋 생성.
- [x] `next-message`를 SayNow식 고정 질문 체계로 수정.
- [x] `nextQuestion` 요청 DTO와 프롬프트 실패 테스트 작성.
- [x] 응답이 고정 질문 영어/한국어를 포함하지 않으면 502 처리.
- [x] `.venv/bin/python -m unittest discover -s tests` 재실행.
- [x] 고정 질문 체계 수정 커밋 생성.
- [x] LAN-95 리뷰에서 찾은 제출 메시지와 히스토리 불일치 검증 테스트 추가.
- [x] 제출 메시지와 히스토리 일치 검증 구현.
- [x] LAN-95 전체 unittest, compileall, diff check 재실행.
- [x] 리뷰 수정 커밋 생성.

## 2026-07-08 LAN-96 대화 종료 메시지 생성 API

- [x] `feat/LAN-96` 브랜치 생성.
- [x] SayNow `origin/develop`의 `closing-message` 모델, 라우터, 프롬프트, 테스트 확인.
- [x] Landit 계약 차이 확인. 전체 `conversationHistory`, 공통 응답 래퍼, invalid 502, 생성 실패 503 기준.
- [x] LAN-96 구현 계획 문서 작성.
- [x] `closing-message` 요청/응답 DTO 실패 테스트 작성.
- [x] 최소 DTO 구현.
- [x] closing-message 성공/프롬프트 계약 실패 테스트 작성.
- [x] closing-message LLM 서비스와 라우터 구현.
- [x] 응답 필드 누락, 꼬리 질문 정책 위반 502 테스트 작성.
- [x] LLM 생성 실패 503 테스트 작성.
- [x] README 문서 반영.
- [x] 전체 unittest, compileall, diff check 실행.
- [x] OpenAPI 스키마에 `closing-message` 경로 노출 확인.
- [x] 의미 단위 커밋 생성.

## 2026-07-08 LAN-96 리뷰 점검

- [x] `ponytail`과 `review` 기준으로 중복, 과구현, 오류 가능성 점검.
- [x] `INVALID_REQUEST` 기본 메시지를 LAN-96 명세 문구와 일치하도록 수정.
- [x] next-message와 closing-message의 LLM 호출 중복을 공통 helper로 축소.
- [x] 수정 후 전체 unittest, compileall, diff check 실행.
- [x] 리뷰 수정 커밋 생성.

## 2026-07-08 LAN-97 메시지별 피드백 생성 API

- [x] `feat/LAN-97` 브랜치 생성.
- [x] SayNow `origin/develop`의 turn-feedback 모델, 프롬프트, cache 구조 확인.
- [x] LAN-97 구현 계획 문서 작성.
- [x] message-feedback 요청/응답 DTO 실패 테스트 작성.
- [x] GOOD, NEEDS_IMPROVEMENT 필드 정책 실패 테스트 작성.
- [x] 메시지 피드백 TTL cache 테스트 작성.
- [x] DTO, 서비스, cache helper, 라우터 구현.
- [x] README 문서 반영.
- [x] 전체 unittest, compileall, diff check 실행.
- [x] OpenAPI 스키마에 `message-feedback` 경로 노출 확인.
- [x] 의미 단위 커밋 생성.

## 2026-07-08 LAN-97 리뷰 점검

- [x] `ponytail` 기준으로 과구현, 사용처 없는 helper, 불필요한 프롬프트 출력 필드 확인.
- [x] 사용처 없는 cache entry 조회 helper 제거.
- [x] 서버가 저장하지 않는 `detectedPatterns`를 프롬프트 출력 스키마에서 제거.
- [x] cache의 단일 프로세스 한계를 주석으로 명시.
- [x] 전체 unittest, compileall, diff check 재실행.
- [x] 리뷰 수정 커밋 생성.

## 2026-07-08 LAN-97 문서 구조 분리

- [x] README에 섞인 개발, 아키텍처, API 세부 내용을 분리할 범위 확인.
- [x] README를 프로젝트 진입점과 문서 링크 중심으로 축소.
- [x] 아키텍처 세부 문서를 `docs/architecture.md`로 분리.
- [x] conversation API 책임과 정책을 `docs/api/conversation.md`로 분리.
- [x] 개발 환경과 검증 명령을 `docs/development.md`로 분리.

## 2026-07-08 LAN-98 세션 최종 피드백 생성 API

- [x] SayNow `origin/develop`의 session-feedback DTO, 라우터, 프롬프트, 캐시 정책 확인.
- [x] LAN-98 구현 계획 문서 작성.
- [x] session-feedback 요청/응답 DTO 실패 테스트 작성.
- [x] `expectedMessageIds` 검증과 409 에러 계약 실패 테스트 작성.
- [x] LLM 기반 `highlightMessage`, `summaryMessage` 생성 테스트 작성.
- [x] 서버 계산 기반 `nativeScore`, `starRating` 테스트 작성.
- [x] 성공 시 cache 삭제, 실패 시 cache 보존 테스트 작성.
- [x] DTO, 서비스, 라우터 구현.
- [x] conversation API 문서 반영.
- [x] 전체 unittest, compileall, diff check 실행.
- [x] OpenAPI 스키마에 `session-feedback` 경로 노출 확인.
- [x] 의미 단위 커밋 생성.

## 2026-07-11 LAN-93 USER First 메시지별 피드백

- [x] `feat/LAN-93` 브랜치 생성 및 기준선 unittest 확인.
- [x] AI_MESSAGE와 SCENARIO_OPENING_INSTRUCTION 요청 계약 확정.
- [x] USER First 요청 DTO와 프롬프트 분기 실패 테스트 작성.
- [x] 평가 컨텍스트 DTO와 조건부 검증 구현.
- [x] USER First 평가 프롬프트와 기존 AI_MESSAGE 회귀 경로 구현.
- [x] conversation API 문서와 OpenAPI 스키마 확인.
- [x] 전체 unittest, compileall, diff check 실행.
- [x] 의미 단위 커밋 생성.
