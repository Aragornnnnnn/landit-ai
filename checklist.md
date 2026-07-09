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
