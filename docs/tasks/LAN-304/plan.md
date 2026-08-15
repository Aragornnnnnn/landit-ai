<!-- LAN-304 AI 구현 계획 문서 -->
# LAN-304 AI 구현 계획

- [x] 프리톡 공용 요청 모델에 필수 `characterId` enum을 추가한다.
- [x] 캐릭터별 성격과 지역 영어 지침 매핑을 추가한다.
- [x] opening, turn, closing, inner-thought 시스템 프롬프트에 정책을 주입한다.
- [x] 요청 검증과 프롬프트 조합 테스트를 추가한다.
- [x] 전체 단위 테스트를 통과시킨다.

## 검증 결과

- 2026-08-15: `python -m unittest discover -s tests` 244개 성공.
