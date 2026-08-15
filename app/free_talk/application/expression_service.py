# 프리톡 대화에 맞는 기존 표현 추천을 처리하는 유스케이스 모듈
import json
import re

from pydantic import ValidationError

from app.core.config import Settings
from app.free_talk.llm.json_completion import (
    AiResponseInvalidError,
    request_json_completion,
)
from app.models.free_talk import (
    ExpressionRecommendationsRequest,
    ExpressionRecommendationsResponse,
)


_PROHIBITED_RECOMMENDATION_FEEDBACK_PATTERN = re.compile(
    r"\b(?:correct|fix)\s+(?:your|the)\s+(?:grammar|sentence|mistakes?)\b|"
    r"\b(?:your|the)\s+(?:grammar|sentence|expression)\s+"
    r"(?:is|are)\s+(?:wrong|incorrect)\b|"
    r"\byour\s+score\s+(?:is|was)\s+(?:low|high)\b|"
    r"\bfeedback\b.{0,40}\b(?:mistakes?|grammar|correction|score)\b|"
    r"(?:문법|표현).{0,8}(?:틀렸|오류|교정|수정)|"
    r"점수.{0,8}(?:낮|높|평가)|피드백.{0,20}(?:문법|오류|틀렸|교정|수정)",
    re.IGNORECASE,
)


def recommend_expressions(
    payload: ExpressionRecommendationsRequest,
    settings: Settings,
) -> ExpressionRecommendationsResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_recommendations_system_prompt(),
        user_prompt=_recommendations_user_prompt(payload),
    )
    try:
        response = ExpressionRecommendationsResponse.model_validate(data)
        _validate_recommendations(response, payload)
        return response
    except (ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc


def _validate_recommendations(
    response: ExpressionRecommendationsResponse,
    payload: ExpressionRecommendationsRequest,
) -> None:
    existing_expressions = {
        expression.expressionId: expression for expression in payload.existingExpressions
    }
    for display_order, recommendation in enumerate(response.recommendations, start=1):
        if recommendation.displayOrder != display_order:
            raise ValueError("recommendation displayOrder must be sequential")
        if recommendation.existingExpressionId not in existing_expressions:
            raise ValueError("recommendation references an unknown existing expression")
        existing_expression = existing_expressions[recommendation.existingExpressionId]
        if (
            recommendation.targetExpressionText
            != existing_expression.targetExpressionText
            or recommendation.baseExpressionMeaningText
            != existing_expression.baseExpressionMeaningText
            or recommendation.usageSummary != existing_expression.usageSummary
        ):
            raise ValueError("recommendation changes an existing expression")
        _validate_recommendation_feedback_language(recommendation)


def _validate_recommendation_feedback_language(recommendation) -> None:
    visible_texts = (
        recommendation.targetExpressionText,
        recommendation.baseExpressionMeaningText,
        recommendation.usageSummary,
    )
    if any(
        _PROHIBITED_RECOMMENDATION_FEEDBACK_PATTERN.search(text) is not None
        for text in visible_texts
    ):
        raise ValueError("recommendation must not include direct feedback")


def _recommendations_system_prompt() -> str:
    return (
        "Recommend one to three useful English expressions from the complete free-talk "
        "conversation. Return only JSON with recommendations. Prefer an appropriate "
        "existing expression. "
        "Each recommendation requires displayOrder, existingExpressionId, "
        "targetExpressionText, baseExpressionMeaningText, and usageSummary. "
        "existingExpressionId must use an input expressionId. "
        "Use displayOrder starting at 1 without gaps. Do not give correction feedback."
    )


def _recommendations_user_prompt(payload: ExpressionRecommendationsRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
