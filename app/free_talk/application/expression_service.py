# 프리톡 대화에 맞는 기존 표현 추천을 처리하는 유스케이스 모듈
import json

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.free_talk.llm.json_completion import (
    AiResponseInvalidError,
    request_json_completion,
)
from app.models.free_talk import (
    ExpressionRecommendation,
    ExpressionRecommendationsRequest,
    ExpressionRecommendationsResponse,
)


class _RecommendationSelection(BaseModel):
    """LLM은 후보 중 무엇을 고를지만 답하고 표현 텍스트는 반환하지 않는다."""

    expressionIds: list[int] = Field(min_length=1, max_length=3)


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
        selection = _RecommendationSelection.model_validate(data)
        return _build_recommendations(selection, payload)
    except (ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc


def _build_recommendations(
    selection: _RecommendationSelection,
    payload: ExpressionRecommendationsRequest,
) -> ExpressionRecommendationsResponse:
    existing_expressions = {
        expression.expressionId: expression for expression in payload.existingExpressions
    }
    if len(set(selection.expressionIds)) != len(selection.expressionIds):
        raise ValueError("recommendation must not repeat an expression")

    recommendations = []
    for display_order, expression_id in enumerate(selection.expressionIds, start=1):
        existing_expression = existing_expressions.get(expression_id)
        if existing_expression is None:
            raise ValueError("recommendation references an unknown existing expression")
        recommendations.append(
            ExpressionRecommendation(
                displayOrder=display_order,
                existingExpressionId=expression_id,
                targetExpressionText=existing_expression.targetExpressionText,
                baseExpressionMeaningText=existing_expression.baseExpressionMeaningText,
                usageSummary=existing_expression.usageSummary,
            ),
        )
    return ExpressionRecommendationsResponse(recommendations=recommendations)


def _recommendations_system_prompt() -> str:
    return (
        "Select the expressions that best suit the completed free-talk conversation "
        "from the candidate list given in existingExpressions. Return only JSON in the "
        'form {"expressionIds": [12, 5]} with one to three ids ordered by how well each '
        "expression suits the conversation. Every id must come from the input "
        "existingExpressions; never invent an id and never repeat one. Return ids only "
        "and no expression text of any kind."
    )


def _recommendations_user_prompt(payload: ExpressionRecommendationsRequest) -> str:
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
