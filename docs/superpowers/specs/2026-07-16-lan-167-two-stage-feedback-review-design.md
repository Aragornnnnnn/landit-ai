# LAN-167 메시지 피드백 판정·문구 분리와 세션 점수 설계

## 배경

LAN-167의 단일 호출 프롬프트를 강화하고, 첫 호출이 만든 전체 피드백을 두 번째 호출이 다시 검수하는 방식까지 실제 사용자 발화로 시험했다. 전체 115개 발화의 초기 평가에서는 GOOD 22개 중 9개가 복합 질문의 일부만 답한 과대 판정이었고, NEEDS_IMPROVEMENT 93개 중 55개에서 교정 표현이나 이유의 품질 문제가 확인됐다.

전체 피드백 검수 방식도 중요 사례에서 안정적이지 않았다. 복합 질문의 일부만 답한 146, 283, 329, 330번을 GOOD으로 판정하거나, 56, 330, 335번의 교정 표현에 사용자 발화에 없는 사실과 이유를 추가했다. 31번에서는 대문자와 문장부호만을 근거로 불필요한 교정을 만들었다. 첫 번째 전체 피드백을 fallback으로 저장하면 이미 확인된 오판을 그대로 노출하므로 실패 처리로도 적절하지 않다.

반면 같은 모델에 문구 생성을 맡기지 않고 핵심 요청 충족 여부와 세 평가 항목만 판단하게 한 실험은 중요 사례 14개를 3회씩 실행한 42건에서 기대한 `contextFit` 경계를 모두 유지했다. 31번은 세 항목이 모두 2로 유지돼 대문자와 문장부호만으로 감점하지 않았다. 따라서 의미 판정과 사용자용 문구 생성을 서로 다른 호출로 분리하고, 판정은 서버가 잠그는 구조를 채택한다.

세션 결과 화면에는 또 다른 일관성 문제가 있다. 세 발화가 모두 NEEDS_IMPROVEMENT인데 원시 메시지 점수 평균이 82점이면 별점 2.5가 표시돼 `3번 중 0번 원어민처럼 말했어요`와 충돌한다. 메시지별 부분 성취는 원시 점수로 보존하되, 세 발화 이상인 세션은 GOOD 비율을 함께 반영해야 한다.

## 목표

- 첫 호출은 사용자용 문구를 쓰지 않고 평가 문맥의 핵심 요청과 평가 근거만 판정한다.
- 서버가 판정 결과를 검증하고 `feedbackType`과 메시지 점수를 확정한다.
- 두 번째 호출은 확정된 판정을 바꾸지 않고 사용자에게 보여 줄 피드백 문구만 작성한다.
- 교정 표현이 사용자 발화에 없는 개인정보를 만들어 내지 않고, 빠진 정보에는 구체적인 플레이스홀더를 사용하게 한다.
- 세 발화 이상인 세션은 원시 메시지 점수 평균과 GOOD 비율을 함께 반영해 점수, 별점, 성공 횟수가 같은 방향을 가리키게 한다.
- 외부 메시지 피드백 API, 세션 피드백 API, backend DTO, DB 스키마는 변경하지 않는다.

## 판정 단계

첫 번째 호출의 내부 응답은 다음 정보만 생성한다.

- `messageId`.
- `coreAsks`.
  - `ask`는 `evaluationContext`에 포함된 독립적인 핵심 요청이다.
  - `addressed`는 사용자 발화가 해당 요청에 답했는지를 나타낸다.
  - `evidence`는 답한 경우 사용자 발화에서 그대로 복사한 근거이고, 답하지 않은 경우 `null`이다.
  - `requiredPlaceholder`는 답하지 않은 개인 정보가 교정 표현에 필요할 때 사용할 구체적인 영문 플레이스홀더이고, 그 외에는 `null`이다.
- `statedFacts`는 교정 표현에서 보존해야 하는 사용자 발화의 사실을 원문 부분 문자열로 기록한다.
- `scoreEvidence`는 `contextFit`, `clarity`, `languageAccuracy`를 각각 0, 1, 2로 평가한다.

판정 프롬프트는 `evaluationContext`만 핵심 요청으로 분해한다. 시나리오 제목이나 전체 목표는 대화 이해를 위한 참고 맥락일 뿐, 사용자가 이번 발화에서 추가로 답해야 하는 요청으로 만들지 않는다.

서버는 다음 불변식을 검증한다.

1. `coreAsks`는 하나 이상이다.
2. `addressed=true`인 요청의 `evidence`는 비어 있지 않고 정규화된 사용자 발화에 실제로 존재한다.
3. `addressed=false`인 요청의 `evidence`는 `null`이다.
4. 모든 요청을 답했으면 `contextFit=2`, 일부만 답했으면 1, 하나도 답하지 않았으면 0이다.
5. `statedFacts`의 모든 값은 사용자 발화에 실제로 존재한다.
6. `requiredPlaceholder`는 답하지 않은 요청에만 허용하며 `^[your ...]$` 형태의 소문자 영문 대괄호 표현을 사용한다. 실제 검증 정규식은 `^\[your [a-z][a-z ]*\]$`이다.
7. `feedbackType`은 모델에게 받지 않고 서버가 계산한다. 세 평가 항목이 모두 2면 GOOD, 하나라도 낮으면 NEEDS_IMPROVEMENT다.

메시지별 점수는 현재 식을 유지한다.

```text
messageScore = max(50, contextFit * 20 + clarity * 15 + languageAccuracy * 15)
```

## 문구 생성 단계

두 번째 호출은 원본 요청과 서버 검증을 통과한 판정 결과를 입력으로 받는다. 모델은 `feedbackType`과 `scoreEvidence`를 출력하거나 변경하지 않고 다음 사용자용 필드만 작성한다.

- `messageId`.
- `baseLocaleAnalogy`.
- `positiveFeedback`.
- `feedbackDetail`.
- `correctionExpression`.
- `correctionReason`.
- `benchmarkMessage`.
- 내부 검증용 `detectedPatterns`.

서버는 판정 결과의 `feedbackType`과 `scoreEvidence`를 문구 결과에 결합해 최종 `MessageFeedbackData`를 만든다. 모델이 판정을 다시 출력하더라도 사용하지 않으며, 내부 문구 DTO에는 해당 필드를 두지 않는다.

NEEDS_IMPROVEMENT 문구는 다음 조건을 추가로 검증한다.

1. 판정 결과에 있는 모든 `requiredPlaceholder`가 `correctionExpression`에 그대로 포함된다.
2. 교정 표현의 플레이스홀더는 `^\[your [a-z][a-z ]*\]$` 형식만 사용한다.
3. `correctionReason`에는 한글이 포함돼야 한다.
4. `없는 사실`, `사실을 만들지`, `임의로 추측`처럼 내부 생성 정책을 사용자에게 설명하지 않는다.
5. 판정 단계의 `statedFacts`와 실제 사용자 발화의 의미, 시제, 부정은 유지한다.

프롬프트에는 다음 경계 예시를 포함한다.

- `I like jogging.`이 취미와 이유를 묻는 질문에 답했다면 `I like jogging because [your reason].`으로 보완한다.
- 여행 증빙을 묻는 질문에 `My aircon bill is boom.`이라고 했다면 무관한 문장을 다듬지 않고 `I have [your travel proof].`로 답을 제시한다.
- 자기소개 질문에 `Hi, my name is Sangmin.`만 말했다면 `Hi, my name is Sangmin. I enjoy [your hobby].`로 보완한다.
- `I don't have anything, but ticket for my airplane.`은 새 사실을 추가하지 않고 `I only have my plane ticket.`으로 고친다.
- 내용이 완결됐고 대문자나 문장부호만 어색한 발화는 GOOD으로 유지한다.

## 실패 처리

- 판정 JSON 파싱, 내부 DTO 검증, 사용자 발화 근거 검증이 `AiResponseInvalidError`로 실패하면 원본 요청과 유효하지 않은 판정 후보를 사용해 판정 복구 호출을 한 번만 수행한다.
- 판정 복구 결과도 검증에 실패하면 요청을 실패시킨다. 검증되지 않은 판정으로 문구를 생성하지 않는다.
- provider 또는 네트워크 실패인 `AiGenerationFailedError`는 판정 복구 대상이 아니다. 기존 503 계약을 유지하고 같은 요청 안에서 반복 호출하지 않는다.
- 정상 경로는 판정 1회와 문구 생성 1회다.
- 문구 호출이나 문구 검증이 실패하면 확정된 판정과 검증 오류를 사용해 문구 복구 호출을 한 번만 수행한다.
- 복구 결과도 유효하지 않으면 요청을 실패시킨다.
- 기존처럼 첫 번째 전체 피드백을 fallback으로 저장하지 않는다. 정상 경로는 2회, 판정 또는 문구 중 한 단계만 복구하면 3회, 두 단계가 모두 한 번씩 복구되면 최대 4회의 모델 호출이다.

초기 모델은 판정 전용 실험에서 안정적이었던 `openai/gpt-5.4-mini`를 두 단계 모두 사용한다. 전체 데이터 재평가 후 문구 자연스러움만 기준에 미달할 때에만 문구 생성 모델 변경을 별도 결정한다.

## benchmarkMessage와 외부 계약

- `detectedPatterns`는 문구 생성 결과에서 분리해 AI 서버 내부 후처리에만 사용한다.
- GOOD이면서 catalog 등록, `status=correct`, `gamifiable=true`, 사용자 발화에 실제 evidence가 있는 패턴만 catalog 문구로 `benchmarkMessage`를 덮어쓴다.
- 검증된 catalog 패턴이 없으면 기존의 안전한 비정량 LLM 문구를 사용한다.
- NEEDS_IMPROVEMENT의 `benchmarkMessage`는 `null`이다.
- 내부 판정, `scoreEvidence`, `coreAsks`, `statedFacts`, `requiredPlaceholder`, `detectedPatterns`는 외부 API와 OpenAPI에 노출하지 않는다.

## 세션 점수와 별점

발화가 1개 또는 2개인 세션은 사소한 개선점 하나로 과도하게 낮아지지 않도록 현재 메시지 점수 평균을 반올림한 값을 유지한다.

발화가 3개 이상이면 원시 메시지 점수 평균 70%와 GOOD 비율 30%를 결합한다.

```text
rawAverage = sum(messageScores) / messageCount
goodRate = goodCount / messageCount
nativeScore = max(50, round_half_up(rawAverage * 0.7 + goodRate * 100 * 0.3))
```

부동소수점과 이중 반올림을 피하기 위해 구현은 다음 정수 비율식을 사용한다.

```text
numerator = sum(messageScores) * 7 + goodCount * 300
denominator = messageCount * 10
nativeScore = max(50, round_half_up(numerator / denominator))
```

별점은 별도의 GOOD 비율 상한을 두지 않고 최종 `nativeScore`에서만 계산한다.

- 0~54점은 1.0개다.
- 55~64점은 1.5개다.
- 65~74점은 2.0개다.
- 75~89점은 2.5개다.
- 90~100점은 3.0개다.

예상 경계는 다음과 같다.

- 원시 평균 82점, GOOD 0/3은 57점과 별 1.5개다.
- 원시 평균 90점, GOOD 1/3은 73점과 별 2.0개다.
- 원시 평균 95점, GOOD 2/3은 87점과 별 2.5개다.
- 원시 평균 100점, GOOD 3/3은 100점과 별 3.0개다.

결과 화면의 제목 문구 변경은 frontend 범위이므로 이번 AI 작업에 포함하지 않는다. 이번 변경은 점수와 별점이 GOOD 성공 횟수와 모순되는 문제만 해결한다.

## 검증 기준

- 중요 사례 14개를 판정 단계로 각 3회 평가했을 때 기대한 `contextFit`과 피드백 유형이 42건 모두 일치한다.
- 146, 283, 329, 330번은 3회 모두 NEEDS_IMPROVEMENT다.
- 31번은 3회 모두 GOOD이며 대문자와 문장부호만으로 감점하지 않는다.
- 56, 208, 296, 329, 330, 335번의 교정 표현에 사용자에게 없는 사실이나 이유를 추가하지 않고 필요한 정보를 플레이스홀더로 남긴다.
- 문구의 플레이스홀더 형식과 한국어 `correctionReason` 검증을 통과한다.
- 전체 115개 발화를 다시 평가해 false GOOD과 중대한 교정 오류가 기존 기준선보다 감소하고, 위 중요 사례에 반복되는 중대 오류가 없다.
- 세션 점수 경계 테스트와 기존 외부 API·OpenAPI 회귀 테스트가 통과한다.
- `.venv/bin/python -m unittest discover -s tests`가 통과한다.
