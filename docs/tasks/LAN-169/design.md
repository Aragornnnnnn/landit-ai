# LAN-169 속마음 판정 구조 설계

## 목표

LLM 호출은 정상 경로에서 1회로 유지하면서 단답, 불충분한 답변, 상대를 향한 공격을 일관된 기준으로 판정한다. `inner-thought` 요청·응답 계약은 변경하지 않는다.

## 생성 결과

LLM은 기존 속마음 필드와 함께 내부 판정 근거를 반환한다.

```json
{
  "answerCoverage": "COMPLETE",
  "relationshipTone": "BLUNT",
  "directedAttack": false,
  "innerThought": "토요일이 좋다는 건 알겠는데, 대답이 짧네.",
  "innerThoughtType": "NORMAL"
}
```

- `answerCoverage`: 마지막 사용자 발화가 직전 질문을 충족한 정도로 `COMPLETE`, `PARTIAL`, `DECLINED`, `UNRELATED` 중 하나다.
- `relationshipTone`: 마지막 사용자 발화가 전체 대화 맥락에서 상대에게 느껴지는 말투로 `WARM`, `NEUTRAL`, `BLUNT`, `HOSTILE` 중 하나다.
- `directedAttack`: 현재 대화 상대를 향한 욕설·모욕·위협 여부.
- 반복 여부는 별도 필드나 서버 규칙으로 만들지 않는다. 전체 대화는 현재처럼 맥락으로만 전달한다.

## 유형 결정

판정 근거가 모두 유효하면 서버가 아래 우선순위로 최종 유형을 정한다.

1. `directedAttack=true` 또는 `relationshipTone=HOSTILE`이면 `BAD`.
2. `answerCoverage=UNRELATED`이면 `BAD`.
3. `answerCoverage=PARTIAL` 또는 `DECLINED`이면 `NORMAL`.
4. `relationshipTone=BLUNT`이면 `NORMAL`.
5. 그 외에는 `GOOD`.

LLM의 `innerThoughtType`과 서버 판정이 다르면 서버 판정을 사용한다. `innerThought`는 판정 근거를 직접 반영하도록 한 번의 생성 응답에서 함께 만들며, 문구 생성을 위한 두 번째 정상 호출이나 입력 문장별 템플릿은 추가하지 않는다.

## 형식 오류 처리

1. 전체 판정 근거와 기존 속마음 필드가 유효하면 서버 결정표를 사용한다.
2. 판정 근거가 누락되거나 잘못됐지만 `innerThought`와 `innerThoughtType`이 유효하면 기존 두 필드를 fallback으로 사용한다.
3. JSON 파싱, `innerThought`, `innerThoughtType`까지 실패하면 형식 복구를 한 번만 호출한다.
4. 복구 결과도 유효하지 않으면 기존과 같이 `502 AI_RESPONSE_INVALID`를 반환한다.

fallback과 복구 여부는 원문 없이 `sessionId`, `messageId`, 잘못된 필드명만 기록한다.

## 검증 기준

- 기존 실데이터 8건을 3회씩 실행해 24/24를 만족한다.
- 욕설 control은 `BAD`, 정상적인 구체 답변 control은 `GOOD`을 유지한다.
- 정상 경로는 LLM 1회 호출을 유지하고 기존 대비 지연시간이 유의미하게 늘지 않는다.
- 전체 필드 정상, 판정 충돌, 기존 필드 fallback, 복구 성공, 복구 실패를 단위 테스트로 확인한다.
- 전체 unittest와 compileall, pip check, diff check를 통과한다.
