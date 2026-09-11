# LAN-474 피드백 저장 위치 전환.

기준은 origin/develop `5db1b554`다. 열린 #101은 develop → main 릴리즈 PR이다.

- 기존 message-feedback 응답에 `completedFeedback`을 추가했다. 상태 PREPARING/FAILED와 구 BE용 캐시는 유지하며, 캐시는 성공한 최종 응답 뒤에도 기존 TTL까지 보관한다.
- 완성 결과에는 피드백·점수/판정 근거·보정 정보·원문·schemaVersion=1을 담는다. BE가 저장해 session-feedback의 `completedFeedbacks`로 보내면 캐시 없이 같은 점수 계산을 수행한다. 세션·메시지 ID·순서·버전을 검증한다.
- 추가 LLM 요청·스트리밍·연결을 만들지 않는다. 일반 턴의 다음 질문과 메시지 피드백은 기존 BE 병렬 흐름을 유지한다.
- `LANDIT_AI_INTERNAL_TOKEN` 설정 시 `/api/`를 `X-Landit-Internal-Token`으로 보호한다. `/health`는 유지한다. 비어 있는 기본값은 구 BE 공존용이며 인증 적용 완료 상태가 아니다. BE 헤더 전송을 먼저 배포한 뒤 토큰 강제를 켠다.
- 정상 종료 유예는 110초다. 종료된 작업은 BE의 저장 요청·임대로 복구한다.
- 운영 workflow는 live task 설정을 보존한 새 digest revision을 배포하고 이전 revision·실행 digest를 기록한다. IAM 추가 권한 코드 작성은 자동 승인 검토가 거절해 미포함이다. 권한 준비 전 운영 workflow를 실행하지 않는다.

검증: `.venv/bin/python -m unittest discover -s tests` 539개, 실패 0·생략 7개. 캐시 초기화·다른 인스턴스·반복 요청·구버전 요청·잘못된 ID/버전·인증을 포함한다. 배포 revision Python 테스트 3개와 ECS 검증 shell 테스트도 통과했다. 실제 LLM·배포·구매는 실행하지 않았다.
