# 평가 JSON의 구조와 원문 인용 길이로 제한된 출력 예산을 산정한다.
import json
import math

import tiktoken

from app.models.conversation import SessionAssessmentMessage


def assessment_output_budget(messages: list[SessionAssessmentMessage]) -> int:
    """다섯 영역에 전체 발화를 인용한 Core 크기에 여유를 주되 16K로 제한한다."""
    domains = (
        "situationPerformance", "grammar", "vocabulary", "discourse", "interactionPragmatics",
    )
    envelope = {"levelAssessment": {"core": {"messages": [
        {
            "messageId": message.messageId,
            "taskPerformance": "ACHIEVED",
            "domains": {name: {
                "level": 5, "evidenceStatus": "OBSERVED", "evidenceExcerpt": message.userMessage,
            } for name in domains},
        }
        for message in messages
    ]}}}
    # GPT-5 계열의 인코딩이며 원문 속 특수 토큰 표기도 지시자가 아닌 일반 텍스트다.
    encoded = tiktoken.get_encoding("o200k_base").encode(
        json.dumps(envelope, ensure_ascii=False), disallowed_special=(),
    )
    return min(16384, max(2048, math.ceil(len(encoded) * 1.25) + 512))
