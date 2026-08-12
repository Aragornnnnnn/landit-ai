# LAN-291 프리톡 표현 임베딩 구현 계획

## 1. 사전 생성 임베딩

- [x] 818개 입력을 고정 결합 규칙으로 생성했다.
- [x] OpenRouter에서 1,536차원 벡터 818개를 생성했다.
- [x] 런타임 임베딩 endpoint·설정·DTO를 제거했다.

## 2. EXISTING-only 추천

- [x] NEW 추천이 검증에서 거부되는 테스트로 기존 동작 실패를 확인한다.
- [x] NEW enum·프롬프트·학습 콘텐츠 endpoint를 제거한다.
- [x] 기존 ID와 표시 필드 불변 검증을 유지한다.
- [x] API와 규칙 테스트를 통과시켰다.

## 3. 전체 검증

- [x] `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`를 실행했다. 226 tests OK.
- [x] FastAPI OpenAPI에 임베딩 endpoint와 제거된 학습 콘텐츠 endpoint가 없는지 확인했다.
- [x] `git diff --check`, `git status --short`를 확인했다.
- [x] 검증 결과를 이 문서에 기록했다.

## 구현 기록

- API 서버는 DB를 직접 다루지 않으며 운영 임베딩 endpoint도 제공하지 않는다.
- 표현 임베딩은 배포 전에 생성해 BE V52 migration에 고정한다.
- 대화 임베딩과 DB 유사도 검색 연결은 후속 이슈 범위다.
