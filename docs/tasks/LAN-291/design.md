# LAN-291 프리톡 표현 임베딩 설계

## 목표

AI 서버의 운영 API는 프리톡 추천에서 공용 기존 표현만 반환한다. 818개 표현의 임베딩은 배포 전에 일회성으로 생성해 BE 데이터 migration에 고정한다.

## 사전 생성 임베딩

- 모델: `openai/text-embedding-3-small`.
- 차원: 1,536.
- 입력: `target_expression_text`와 `usage_summary`를 고정 규칙으로 결합한 818개 문자열.
- 출력: 입력 순서를 보존한 1,536차원 실수 배열 818개.
- 생성 결과는 BE V52 INSERT에 포함하며 운영 AI API로 노출하지 않는다.

## 추천 계약

- `ExpressionSourceType.NEW`와 NEW 학습 콘텐츠 생성 API를 제거한다.
- 추천은 전달받은 `existingExpressions`에서만 선택한다.
- 각 추천은 `displayOrder`, `existingExpressionId`, 기존 표현의 표시 필드를 반환한다.
- 알 수 없는 ID나 기존 표현 내용을 바꾼 응답은 계속 거부한다.

## 경계

AI 서버는 DB를 읽거나 쓰지 않으며 임베딩 HTTP API도 제공하지 않는다. 대화 임베딩 생성과 DB 유사도 검색 연결은 후속 이슈에서 결정하고 구현한다.
