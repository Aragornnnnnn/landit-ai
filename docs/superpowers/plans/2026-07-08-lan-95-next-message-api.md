# LAN-95 다음 AI 메시지 생성 API 계획

## 목표

`POST /api/v1/conversation/next-message`를 추가해 시나리오 컨텍스트, 대화 히스토리, backend가 지정한 다음 고정 질문을 바탕으로 다음 AI 메시지, 번역, 상대 역할의 속마음, 목표 달성 상태를 반환한다.

## 범위

- 요청/응답 DTO를 Pydantic v2 모델로 검증한다.
- 요청 DTO에는 SayNow식 `nextQuestion.questionId`, `sequence`, `questionEn`, `questionKo`를 포함한다.
- OpenRouter 기반 OpenAI SDK 호출을 기존 클라이언트 생성 함수로 재사용한다.
- SayNow `origin/develop`의 고정 질문 정책, 속마음 정책, 안전 정책, JSON 응답 정책을 같은 목적의 프롬프트 문구로 재사용한다.
- LLM 응답 형식 오류는 502, 생성 실패는 503으로 구분한다.
- 세션 상태 저장, 캐시, LangChain, 새 의존성은 추가하지 않는다.

## 검증

- `unittest`로 성공, 502, 503 경로를 먼저 고정한다.
- 최종 검증은 `.venv/bin/python -m unittest discover -s tests`로 한다.
