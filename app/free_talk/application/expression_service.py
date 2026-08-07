# 프리톡 맞춤 표현 추천과 신규 표현 학습 콘텐츠 생성을 처리하는 유스케이스 모듈
import json
import re

from pydantic import ValidationError

from app.core.config import Settings
from app.free_talk.domain.rules import validate_learning_content_contract
from app.free_talk.llm.json_completion import (
    AiResponseInvalidError,
    request_json_completion,
)
from app.models.free_talk import (
    ExpressionLearningContentRequest,
    ExpressionLearningContentResponse,
    ExpressionRecommendationsRequest,
    ExpressionRecommendationsResponse,
    ExpressionSourceType,
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


def generate_expression_learning_content(
    payload: ExpressionLearningContentRequest,
    settings: Settings,
) -> ExpressionLearningContentResponse:
    try:
        data = request_json_completion(
            settings=settings,
            system_prompt=_learning_content_system_prompt(),
            user_prompt=_learning_content_user_prompt(payload),
        )
        return _validate_learning_content(data, payload)
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
        if (
            recommendation.sourceType == ExpressionSourceType.EXISTING
            and recommendation.existingExpressionId not in existing_expressions
        ):
            raise ValueError("recommendation references an unknown existing expression")
        if recommendation.sourceType == ExpressionSourceType.EXISTING:
            existing_expression = existing_expressions[
                recommendation.existingExpressionId
            ]
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


def _validate_learning_content(
    data: dict[str, object],
    payload: ExpressionLearningContentRequest,
) -> ExpressionLearningContentResponse:
    response = ExpressionLearningContentResponse.model_validate(data)
    if len(response.expressions) != len(payload.expressions):
        raise ValueError("learning content must match every requested expression")
    for requested_expression, content in zip(
        payload.expressions, response.expressions, strict=True
    ):
        if (
            content.targetExpressionText != requested_expression.targetExpressionText
            or content.baseExpressionMeaningText
            != requested_expression.baseExpressionMeaningText
            or content.usageSummary != requested_expression.usageSummary
        ):
            raise ValueError("learning content must preserve the requested expression")
        validate_learning_content_contract(content)
    return response


def _recommendations_system_prompt() -> str:
    return (
        "Recommend one to three useful English expressions from the complete free-talk "
        "conversation. Return only JSON with recommendations. Prefer an appropriate "
        "existing expression; use NEW only when no existing candidate is appropriate. "
        "Each recommendation requires displayOrder, sourceType, existingExpressionId, "
        "targetExpressionText, baseExpressionMeaningText, and usageSummary. sourceType is "
        "EXISTING or NEW. EXISTING must use an input expressionId; NEW must use null. "
        "Use displayOrder starting at 1 without gaps. Do not give correction feedback."
    )


def _learning_content_system_prompt() -> str:
    return (
        "Generate complete text-only learning content for each requested English "
        "expression. Return only JSON with expressions in the input order. "
        "Preserve every requested "
        "targetExpressionText, baseExpressionMeaningText, and usageSummary. Each item "
        "requires usageDescription, representativeQuestionText, "
        "representativeQuestionTranslation, representativeSentenceText, "
        "representativeSentenceTranslation, representativeSentenceWords, "
        "representativeSentenceWordChoices, representativeImageUrl, and exactly four "
        "practiceExamples. representativeImageUrl and every practice example imageUrl "
        "must be null. sentenceWords must reconstruct sentenceText after punctuation "
        "normalization. Each sentenceWordChoices must include all answer words, at least "
        "one wrong word, and not list answer words in answer order. Each practice "
        "example requires sentenceText, sentenceWords, highlightingPart, practiceQuestion, "
        "sentenceTranslation, sentenceWordChoices, and practiceQuestionTranslation; "
        "highlightingPart must occur in sentenceText."
    )


def _recommendations_user_prompt(payload: ExpressionRecommendationsRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def _learning_content_user_prompt(payload: ExpressionLearningContentRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
