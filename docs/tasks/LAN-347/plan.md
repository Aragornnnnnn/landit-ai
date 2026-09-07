# LAN-347 스몰톡 장기기억 V1 후속 보완

## 변경 계약

- resolution 후보에 `sourceMessages`를 추가한다. BE는 후보의 `sourceMessageIds`에 해당하는 실제 USER 원문만 순서대로 전달하고, AI는 ID와 role을 LLM 호출 전에 검증한다. 생략 시 빈 목록으로 호환되지만 정정 예외는 허용하지 않는다.
- 상세 기억을 단순 요약으로 대체하는 subset guard는 유지한다. 한 기억에 대한 명시적 정정만 내부 `supersedeEvidence`의 이유, source ID, 원문 인용, 한영 정정 단서를 확인해 예외로 허용한다. 예문과 가정문은 보수적으로 제외한다. 근거는 공개 응답에 반환하지 않는다.
- opening/turn과 복구 호출은 현재 UTC instant를 요청 `timezone`으로 변환해 제공한다. 기본 `Asia/Seoul`은 현재 BE 저장용 Clock과 같다. 오프셋 없는 기존 시각은 이 시간대로 해석하고, locale로 시간대를 추측하지 않는다. BE 저장 시간대가 바뀌면 이 계약도 함께 변경해야 한다.
- `validTo`는 포함 경계로 해석한다. 만료·미래 유효 시작 시각과 본문의 일정 날짜를 함께 고려한다. EVENT의 `validFrom`은 관찰 시각일 수 있으며, 예정일이 지나도 실제 사건 발생을 단정하지 않는다. 과거 기억은 회상에 사용할 수 있게 그대로 제공한다.
- 모델이 보고하지 않은 `usedMemoryIds`는 자동 복구하지 않는다. 보고한 ID도 제공 문맥과 번역 응답의 구체 단어 겹침을 검증한다.
- BE 검색 쿼리 임베딩만 전용 2초 timeout을 사용한다. 일반 대화 생성의 `requestTimeout`은 유지한다. 설정 파일의 기존 사용자 변경은 건드리지 않는다.

## 검증 범위와 한계

- 회귀 테스트는 한영 명시적 정정, 일반 요약·가정·예문 차단, 원문 연결, 사용자가 제공한 영어 첼로 발화와 한국어 번역의 오탐을 검증한다.
- 시각 테스트는 UTC 기준 서울의 자정과 LA의 전날 날짜, 과거 일정 유지 및 시간 해석 정책의 프롬프트 전달을 검증한다. 이는 실제 LLM의 시간 해석 품질 검증이 아니다.
- BE의 로컬 HTTP 서버 테스트는 3초 후 정상 응답에 앞서 검색이 timeout되는지, 2.3초 지연 대화는 일반 timeout으로 성공하는지 검증한다.
- 정정 단서와 원문 인용은 의미적 정정 여부의 완전한 증명이 아니다. 정정 대상과 인용의 의미적 관련성, 미정정 세부 정보 보존은 모델 판단의 한계가 남는다. 단서가 없는 정정이나 여러 기억을 한 번에 대체하는 subset 정정은 보수적으로 IGNORE될 수 있다.
- 사용 기록은 **모델 자기보고와 단어 휴리스틱으로 계산한 추정치**다. 인과적으로 검증된 실제 기억 사용률이 아니며 오탐·누락이 가능하다. 자동 복구 제거 전후 수치를 그대로 품질 개선율로 비교하지 않는다.
- 실제 LLM 호출, 운영 DB·배포·기기 검증은 수행하지 않는다. 새 BE 계약 적용 시 `extra=forbid`인 구 AI가 거부하므로 AI를 먼저 배포해야 한다. 이번 작업은 push와 배포를 포함하지 않는다.

## 최종 검증 결과

- AI `.venv/bin/python -m unittest tests.test_free_talk_api` 통과, 전체 `.venv/bin/python -m unittest discover -s tests` 469개 중 7개 skip, 실패 없음. 최초 465개 기준선의 numpy 미설치는 기존 선언 의존성을 로컬 .venv에 설치해 해결했다.
- 기존 subset guard와 ID 복구 함수를 테스트에 주입하면 명시적 정정과 첼로 오탐 테스트가 실패한다. 수정된 함수에서는 통과한다.
- BE `./gradlew test --tests '*RemoteAiFreeTalkClientTest' --tests '*FreeTalkMemoryGenerationServiceTest' --tests '*FreeTalkMemoryRetrievalServiceTest'` 통과. 최종 전체 결과에서도 해당 34개 테스트 실패 없음. 일반 timeout으로 되돌린 검색 재현 테스트는 정상 지연 응답을 받아 실패하며 전용 timeout에서는 통과한다.
- BE `./gradlew check --continue`는 856개 중 기존 관리자 목록 테스트 1개 실패(HV000151). 기존 AdminUserController·ScenarioProgressionService의 Checkstyle/Spotless 위반과 기존 FreeTalkMemoryRetrievalServiceTest 포맷 위반이 남아 실패한다. 변경 전 기준선과 동일한 실패이며 사용자 파일은 수정하지 않았다. 변경 테스트 Checkstyle은 통과한다.
- OpenAPI 비교에서 sourceMessages와 timezone만 추가되고 경로·resolution 응답 계약은 유지된다. 기존 BE dirty 파일 4개의 SHA-1은 시작·종료 시 동일하다.
