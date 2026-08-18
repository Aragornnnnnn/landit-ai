# 프리톡 AI 응답 형식 복구 구현 계획

## 요구사항

- 속마음 `directedAttack`의 알려진 비불리언 부정값이 사용자 502로 이어지지 않게 한다.
- 판단할 수 없는 `directedAttack`과 계속 대화의 누락된 표시 메시지는 전체 응답을 한 번만 재생성한다.
- 재생성도 형식 계약을 만족하지 못하면 기존 `AI_RESPONSE_INVALID` 응답을 유지한다.
- 프리톡은 대화 상대 역할만 수행하며, opening·turn·closing에서 사용자의 영어 실력이나 언어 오류를 언급하지 않는다.

## 완료 기준

- [x] 속마음 프롬프트에 `directedAttack`의 JSON boolean 계약과 예시를 명시한다.
- [x] `None`, 빈 문자열, `NONE`, `none`, `no attack`, `없음`, `null`, `not applicable`만 `false`로 제한 정규화한다.
- [x] 그 밖의 `directedAttack`은 전체 JSON 응답을 1회 재생성하고, 다시 실패하면 502를 유지한다.
- [x] `CONTINUE_AFTER_EXIT_DECLINED`의 `aiMessage` 또는 `translatedMessage`가 null, 공백, 비문자열이면 전체 응답을 1회 재생성한다.
- [x] 로컬 현재 코드에서 실제 OpenRouter 10세션 이상의 opening → turn → inner-thought → closing 흐름을 검증한다.
- [x] opening·turn·closing 프롬프트에서 영어 실력, 실수, 정확성, 완벽함, 향상을 언급하지 않도록 명시한다.
- [x] 속마음의 금지된 피드백 표현도 전체 응답을 1회 재생성하고, 재실패하면 502를 유지한다.

## 작업 메모

- 실제 develop 검증에서 속마음 19회 중 15회가 `directedAttack`의 비불리언 값으로 502가 됐다.
- 관찰된 값에는 빈 문자열, `NONE`, `none`, `없음`, `None`, `null`, `Not applicable`과 직접 공격을 설명하는 문장이 포함됐다.
- 계속 대화 모드에서 `userExitIntentDetected=false`인데 표시용 두 메시지가 `null`인 응답도 관찰됐다.
- 화면·저장에 쓰이는 두 메시지는 LAN-309의 미사용 필드처럼 폐기하지 않고, 유효한 쌍을 한 번 재생성한다.
- 실제 샘플에서 closing이 사용자의 영어가 자연스럽다거나 완벽하지 않아도 된다는 식의 언어 숙련도 평가를 했다. Chloe 페르소나의 상충 문구를 제거하고 모든 보이는 프리톡 프롬프트에 금지 계약을 추가했다.
- 최종 10세션 첫 실행에서 속마음에 금지된 피드백 표현이 섞여 502가 발생했다. JSON 후보 검증 뒤의 정책 검증 실패에는 재생성 경로가 없던 것이 원인이다.

## 검증 결과

- [x] TDD RED: 속마음 부정 sentinel, 모호한 설명형 값, 계속 대화 메시지 누락 테스트가 기존 코드에서 502 또는 재시도 누락으로 실패했다.
- [x] focused: 속마음 boolean 계약·정규화·재생성, 계속 대화 null·공백·비문자열 메시지 재생성 및 재실패 502 테스트가 통과했다.
- [x] 프리톡 API 전체 회귀와 전체 unittest를 실행한다.
- [ ] 최종 변경분 독립 코드 리뷰를 완료한다.

- 독립 리뷰에서 키 누락이 `null`과 함께 `false`가 되는 P1을 발견했다. 키 누락은 재생성하도록 수정하고 회귀 테스트를 추가했다.
- 속마음 금지 표현 RED: 실제 OpenRouter 10세션에서 `_validate_inner_thought()`가 금지 표현을 찾아 502를 반환했다. 유효한 두 번째 후보로 재생성하는 테스트를 추가했다.
- 프리톡 역할 정책 RED: 실제 closing이 영어 숙련도를 평가했다. opening·closing 프롬프트 정책 테스트를 추가했다.
- 재생성 범위: malformed JSON, 잘못된 enum, `directedAttack` 누락·비불리언, 속마음 금지 표현에 대해 정상 재생성·재실패 502·총 2회 호출을 각각 검증했다.
- 프리톡 API 회귀: `../../.venv/bin/python -m unittest tests.test_free_talk_api` 60개 통과.
- 전체 회귀: `../../.venv/bin/python -m unittest discover -s tests` 262개 통과.
- 실제 OpenRouter 검증: 로컬 현재 코드에서 10세션, 총 50개 호출의 opening → turn → inner-thought → continue turn → closing이 HTTP 200으로 완료됐다. closing의 언어 피드백 금지 검사도 통과했다.
- 변경 공백 검증: `git diff --check` 통과.
