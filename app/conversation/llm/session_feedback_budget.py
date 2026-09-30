# 시나리오 총평의 비교 문장과 재사용 표현 수에 맞춰 출력 예산을 산정한다.
import json
import math

import tiktoken

from app.models.conversation import SessionFeedbackRequest


def session_feedback_output_budget(
    request: SessionFeedbackRequest, user_messages: list[str],
) -> int:
    """원문 인용과 모든 후보의 재사용 결과를 담을 여유를 두고 16K로 제한한다."""
    if not request.previousMistakes and not request.learnedExpressions:
        return 512
    encoding = tiktoken.get_encoding("o200k_base")

    def token_count(value: str) -> int:
        """발화에 특수 토큰 문자열이 있어도 일반 텍스트로 계산해 예산을 추정한다."""
        return len(encoding.encode(value, disallowed_special=()))

    current = max(user_messages, key=token_count, default="")
    previous = max(
        (mistake.userMessage for mistake in request.previousMistakes),
        key=token_count, default="",
    )
    envelope = {
        "growthFeedback": {
            "pattern": "SUBJECT_VERB_AGREEMENT", "succeeded": True,
            "previousMessageId": 9999999999, "previousSentence": previous,
            "previousWrongSpan": previous, "currentMessageId": 9999999999,
            "currentSentence": current, "currentSpan": current,
        } if request.previousMistakes else None,
        "usedExpressions": [
            {"expressionId": item.expressionId, "messageId": 9999999999,
             "matchedText": current}
            for item in request.learnedExpressions
        ],
    }
    # 한국어 총평 두 문장의 기존 예산에 구조화 출력과 인용 길이의 여유를 더한다.
    tokens = token_count(json.dumps(envelope, ensure_ascii=False))
    return min(16384, max(1024, 512 + math.ceil(tokens * 1.25)))
