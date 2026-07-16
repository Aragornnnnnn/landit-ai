# LAN-167 메시지 피드백 판정 잠금과 문구 fallback 재설계

## 배경

`origin/main`과 현재 `release/LAN-161`을 같은 고정 사례 7건으로 비교했다.

- `origin/main`은 전체 피드백을 한 번 생성하며 7건 모두 형식 검증을 통과했다.
- `origin/main`은 기대한 피드백 유형 5건, 점수와 문맥 경계까지 포함하면 4건만 일치했다.
- 현재 릴리즈의 최종 검수 결과는 7건 모두 피드백 유형과 점수 경계가 일치했다.
- 현재 릴리즈의 1차 후보만 평가하면 구조 복구가 반복됐고, 복구 후에도 `feedbackType`과 `scoreEvidence` 불일치 또는 잘못된 플레이스홀더 형식으로 실패하는 사례가 있었다.
- 실제 재현에서 GOOD 후보가 `positiveFeedback`을 함께 반환해 구조 복구되는 사례가 확인됐다.
- 현재 fallback은 2차 검수 실패만 처리하므로 1차 후보가 끝내 실패하면 메시지가 캐시에 없고 세션 피드백 전체가 실패한다.

백엔드는 세션의 모든 사용자 메시지와 동일한 개수·순서의 `messageFeedbacks`를 요구한다. 실패한 메시지를 제외하는 방식은 AI 외부 계약과 백엔드 저장 계약을 함께 바꿔야 하므로 이번 범위에 포함하지 않는다.

## 목표

- 정상 경로의 LLM 호출을 2회로 유지한다.
- 첫 번째 호출 결과를 점수 근거이자 안전한 fallback 후보로 사용한다.
- 서버가 `scoreEvidence`로 `feedbackType`을 확정한다.
- 두 번째 호출은 잠긴 판정에 맞는 사용자용 문구 생성만 담당한다.
- 두 번째 호출이나 문구 복구가 실패해도 검증된 1차 후보를 저장한다.
- 대소문자, 쉼표, 마침표 등 표기 차이만을 스피킹 개선점으로 제시하지 않는다.
- 1차 유효 후보가 생성된 메시지는 2차 문구 생성 실패와 관계없이 캐시에 저장한다.
- 기존 외부 API, OpenAPI, 백엔드 DTO와 DB 스키마를 유지한다.

## 비목표

- provider 장애로 첫 번째 LLM 응답 자체를 받지 못한 경우 임의의 점수나 피드백을 생성하지 않는다.
- 서버에 영어 문법 검사기나 범용 의미 비교 엔진을 만들지 않는다.
- 특정 메시지 ID, 질문 또는 시나리오에만 적용되는 런타임 분기를 만들지 않는다.
- LAN-166 세션 점수와 별점 정책을 변경하지 않는다.
- benchmark catalog의 검증된 정량 문구 정책을 변경하지 않는다.

## 제안 구조

```text
원본 요청
  -> 1차 점수와 fallback 후보 생성
  -> 서버가 식별자와 feedbackType 확정
  -> 안전한 구조 정규화와 후보 검증
  -> 2차 잠긴 판정 기반 사용자 문구 생성
  -> 최종 문구 검증
  -> 성공 시 2차 문구 사용
  -> 실패 시 검증된 1차 후보 사용
  -> benchmarkMessage catalog 후처리
  -> 캐시 저장과 세션 점수 계산
```

## 1차 점수와 fallback 후보

첫 번째 호출은 현재와 같이 `scoreEvidence`와 사용자에게 노출 가능한 전체 피드백 후보를 생성한다. 전체 후보를 유지하는 이유는 2차 문구 생성이 실패해도 유효한 메시지 피드백을 저장하기 위해서다.

모델은 다음 내부 값을 반환한다.

- `scoreEvidence.contextFit`.
- `scoreEvidence.clarity`.
- `scoreEvidence.languageAccuracy`.
- `baseLocaleAnalogy`.
- `positiveFeedback`.
- `feedbackDetail`.
- `correctionExpression`.
- `correctionReason`.
- `benchmarkMessage`.
- 내부 후처리용 `detectedPatterns`.

`messageId`와 최종 `feedbackType`은 모델 출력에 의존하지 않는다. 서버가 요청의 `messageId`를 사용하고 다음 규칙으로 유형을 확정한다.

```text
세 점수가 모두 2이면 GOOD
하나라도 2보다 낮으면 NEEDS_IMPROVEMENT
```

프롬프트에는 `origin/main`에서 형식 안정성에 기여한 유형별 필드 self-check와 GOOD/NEEDS 예시를 복원한다. LAN-167에서 추가한 복합 질문, 사실 보존, 구체적인 플레이스홀더, 자연스러운 대안 표현 기준은 유지한다.

## 서버의 안전한 구조 정규화

서버는 의미를 추측하지 않고 다음처럼 결과가 결정적인 항목만 정규화한다.

- 요청의 `messageId`를 주입한다.
- `scoreEvidence`로 `feedbackType`을 확정한다.
- GOOD이면 `positiveFeedback`, `correctionExpression`, `correctionReason`을 `null`로 만든다.
- NEEDS_IMPROVEMENT이면 `feedbackDetail`, `benchmarkMessage`를 `null`로 만든다.
- `[hobby]`처럼 `your`만 빠진 명백한 플레이스홀더는 `[your hobby]`로 정규화한다.
- 빈 문자열과 문자열 `"null"`은 유효한 값으로 보지 않는다.

다음 값은 서버가 임의로 만들지 않는다.

- 누락된 `feedbackDetail`.
- 누락된 `positiveFeedback`.
- 누락된 `correctionExpression`.
- 누락된 `correctionReason`.
- 사용자에게 필요한 구체 정보의 종류.
- 점수의 의미 판단.

필수 문구가 없거나 플레이스홀더 의미가 불명확하면 1차 구조 복구를 한 번 실행한다. 복구도 실패하면 첫 호출에서 사용할 수 있는 판정과 후보가 없으므로 기존 오류 계약을 유지한다.

## 2차 잠긴 판정 기반 문구 생성

두 번째 호출은 검수 모델이 점수와 유형을 다시 결정하는 구조가 아니다. 원본 요청, 서버가 확정한 `scoreEvidence`, `feedbackType`, 검증된 1차 후보를 입력으로 받아 사용자용 문구만 작성한다.

두 번째 호출은 다음 값만 반환한다.

- `baseLocaleAnalogy`.
- `positiveFeedback`.
- `feedbackDetail`.
- `correctionExpression`.
- `correctionReason`.
- `benchmarkMessage`.
- 내부 후처리용 `detectedPatterns`.

`messageId`, `feedbackType`, `scoreEvidence`는 반환하지 않는다. 서버가 잠긴 값을 최종 결과에 결합하므로 두 번째 모델이 판정이나 점수를 바꿀 수 없다.

2차 문구는 다음 기준을 지킨다.

- 다섯 사용자용 필드가 같은 핵심 개선점을 설명한다.
- 사용자 발화의 의미, 의도, 시제와 부정 여부를 유지한다.
- 대화에 없는 이름, 지역, 취미, 감정, 습관, 경험과 이유를 추가하지 않는다.
- 필요한 정보가 없으면 `[your hobby]`, `[your hometown]`, `[your reason]`처럼 구체적인 플레이스홀더를 사용한다.
- 복합 질문의 일부만 답했다면 가장 중요한 누락 내용을 보완한다.
- 무관하거나 이해하기 어려운 발화를 문법적으로만 다듬지 않는다.
- 근거 없는 형식적 칭찬과 내부 생성 정책 문구를 사용하지 않는다.

## 스피킹 서비스의 표기 차이 배제

대소문자와 문장부호는 음성으로 구분되지 않으므로 피드백의 개선 근거로 사용하지 않는다. 이 규칙은 프롬프트 권고가 아니라 서버 검증 계약으로 적용한다.

서버는 사용자 발화와 `correctionExpression`을 다음 방식으로 비교한다.

1. Unicode 문자를 정규화한다.
2. 영문 대소문자를 구분하지 않는다.
3. 쉼표, 마침표, 물음표, 느낌표, 따옴표와 아포스트로피 등 문장부호를 제거한다.
4. 연속 공백을 하나로 합친다.

정규화한 두 표현이 같다면 스피킹 관점에서 동일한 발화로 본다. 이 차이만으로 `correctionExpression`을 제공하는 NEEDS_IMPROVEMENT 결과는 유효하지 않은 문구로 처리한다.

예시는 다음과 같다.

```text
사용자 발화: hi my name is sangmin
교정 표현: Hi, my name is Sangmin.
결과: 스피킹 관점에서 동일하므로 교정으로 인정하지 않음
```

`baseLocaleAnalogy`, `positiveFeedback`, `feedbackDetail`, `correctionReason`에서도 다음 표현을 개선 이유로 사용하지 않는다.

- 대문자, 소문자.
- 쉼표, 마침표, 문장부호.
- capitalization, uppercase, lowercase.
- comma, period, punctuation, full stop.

교정 표현이 문법적으로 완성된 문장이라 자연스럽게 대문자와 문장부호를 포함하는 것은 허용한다. 다만 사용자 발화와 비교해 실제로 말했을 때 들리는 단어, 어순, 내용 또는 뉘앙스의 개선이 함께 있어야 한다.

복합 질문의 누락 내용을 추가하는 과정에서 대문자와 문장부호도 함께 정리된 경우에는 누락 내용만 개선 이유로 설명한다. 표기 차이를 사용자에게 지적하지 않는다.

## 실패 처리와 fallback

- 정상 경로는 1차 후보 생성과 2차 문구 생성으로 총 2회 호출한다.
- 1차 결과의 필수 문구가 없으면 구조 복구를 한 번 실행한다.
- 2차 결과가 문구 계약을 위반하면 문구 복구를 한 번 실행한다.
- 2차 호출이 provider 오류로 실패하거나 문구 복구도 실패하면 검증된 1차 후보를 사용한다.
- fallback 여부와 1차·2차 복구 여부는 AI 내부 cache와 품질 평가 결과에만 기록한다.
- fallback은 외부 API와 OpenAPI에 노출하지 않는다.
- 검증된 1차 후보가 저장되므로 2차 실패만으로 `MESSAGE_FEEDBACK_NOT_READY`가 발생하지 않는다.

첫 번째 호출 자체가 provider 또는 네트워크 오류로 실패하면 정확한 점수와 피드백을 만들 수 없다. 이 경우 임의의 50점이나 일반 문구를 저장하지 않고 기존 503 계약을 유지한다.

## benchmarkMessage

- `detectedPatterns`는 외부 응답에 노출하지 않는다.
- GOOD이면서 catalog 등록, `status=correct`, `gamifiable=true`, 사용자 발화에 실제 evidence가 존재하는 패턴만 인정한다.
- 조건을 만족하면 catalog 문구로 `benchmarkMessage`를 덮어쓴다.
- catalog 패턴이 없으면 안전한 비정량 문구를 사용한다.
- NEEDS_IMPROVEMENT의 `benchmarkMessage`는 `null`이다.
- 2차 fallback에서는 검증된 1차 후보의 `detectedPatterns`를 사용한다.

## 점수와 별점

메시지 점수 계산식과 LAN-166 세션 점수 정책을 유지한다.

```text
messageScore = max(50, contextFit * 20 + clarity * 15 + languageAccuracy * 15)
```

발화가 1개 또는 2개인 세션은 메시지 점수 평균을 반올림한다. 발화가 3개 이상이면 원시 평균 70%와 GOOD 비율 30%를 적용한다.

```text
numerator = sum(messageScores) * 7 + goodCount * 300
denominator = messageCount * 10
nativeScore = max(50, round_half_up(numerator / denominator))
```

별점은 최종 `nativeScore`의 기존 매핑만 사용한다.

## 테스트와 운영 검증

단위 테스트는 다음 경계를 고정한다.

- `messageId`는 요청값을 사용하고 `feedbackType`은 `scoreEvidence`에서 서버가 생성한다.
- GOOD에 포함된 NEEDS 전용 필드를 제거한다.
- NEEDS_IMPROVEMENT에 포함된 GOOD 전용 필드를 제거한다.
- 2차 문구가 점수와 유형을 변경할 수 없다.
- 2차 문구 생성과 복구가 모두 실패하면 1차 후보를 저장한다.
- `hi my name is sangmin`을 `Hi, my name is Sangmin.`으로 바꾸는 것만으로 NEEDS_IMPROVEMENT를 만들지 않는다.
- 쉼표, 마침표, 대소문자만 다른 교정 표현을 거부한다.
- 사용자용 설명에서 대문자와 문장부호를 개선 이유로 제시하는 응답을 거부한다.
- 실제 단어, 어순, 내용 또는 뉘앙스가 함께 개선된 교정은 정상적으로 허용한다.
- 외부 응답과 OpenAPI에 내부 평가값과 fallback 여부가 노출되지 않는다.

실제 모델 운영 기준은 다음과 같다.

- 고정 7개 사례를 3회씩 실행한 21건에서 유형과 점수 경계가 모두 일치한다.
- 21건에서 1차 복구 후 최종 실패가 0건이다.
- 이미지 제보와 동일한 대소문자·쉼표·마침표 피드백이 0건이다.
- 전체 115개 실제 데이터에서 메시지 누락과 세션 실패가 0건이다.
- 전체 데이터에서 1차 복구율, 2차 복구율과 fallback 발생률을 따로 집계한다.
- 사용자에게 없는 구체 사실 추가, 의미 변경, 내부 정책 노출, 질문과 무관한 교정 표현이 0건이다.
- `.venv/bin/python -m unittest discover -s tests`가 통과한다.
- compileall, pip check, OpenAPI 회귀와 diff check가 통과한다.

## 예상 효과와 남는 위험

판정과 사용자 문구의 책임이 분리되고, 두 번째 모델은 점수를 바꾸지 못한다. 동시에 1차 후보를 안전한 fallback으로 유지해 한 메시지의 문구 생성 실패가 세션 전체 실패로 번지는 문제를 막는다.

표기 차이 배제는 음성 입력과 스피킹 학습이라는 제품 성격에 맞는 결정적 규칙이다. 범용 의미 비교는 하지 않고, 말했을 때 완전히 같은 표현만 좁게 판정하므로 과도한 의미 규칙 엔진으로 확장되지 않는다.

남는 위험은 첫 번째 provider 호출 자체의 실패와 모델의 자연어 품질 변동이다. 전자는 임의 피드백을 생성하지 않고 기존 오류 계약으로 처리한다. 후자는 고정 사례와 전체 실제 데이터 평가에서 복구율, fallback률과 중대 품질 오류를 함께 측정해 관리한다.
