# 프리톡 대화에 맞는 기존 표현 추천을 처리하는 유스케이스 모듈
import json
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.free_talk.application.expression_reuse_service import find_used_expressions
from app.free_talk.llm.json_completion import (
    AiResponseInvalidError,
    request_json_completion,
)
from app.models.free_talk import (
    ExpressionRecommendation,
    ExpressionRecommendationsRequest,
    ExpressionRecommendationsResponse,
)


logger = logging.getLogger(__name__)


class _RecommendationSelection(BaseModel):
    """LLM은 후보 중 무엇을 고를지만 답하고 표현 텍스트는 반환하지 않는다."""

    model_config = ConfigDict(extra="forbid")

    expressionIds: list[int] = Field(max_length=3)


def recommend_expressions(
    payload: ExpressionRecommendationsRequest,
    settings: Settings,
) -> ExpressionRecommendationsResponse:
    data = request_json_completion(
        settings=settings,
        system_prompt=_recommendations_system_prompt(),
        user_prompt=_recommendations_user_prompt(payload),
        response_model=_RecommendationSelection,
        schema_name="free_talk_expression_recommendations",
        workflow="free_talk_expression_recommendations",
    )
    try:
        selection = _RecommendationSelection.model_validate(data)
        if not selection.expressionIds:
            if not payload.existingExpressions:
                raise ValueError("recommendation fallback requires an existing expression")
            logger.warning(
                "프리톡 표현 추천이 비어 있어 첫 번째 후보를 사용합니다. "
                "workflow=expression_recommendation_fallback candidateCount=%s",
                len(payload.existingExpressions),
            )
            selection = _RecommendationSelection(
                expressionIds=[payload.existingExpressions[0].expressionId],
            )
        response = _build_recommendations(selection, payload)
    except (ValidationError, ValueError) as exc:
        raise AiResponseInvalidError from exc
    # 추천이 확정된 뒤에 돌려 재사용 판정 실패가 추천 결과를 막지 않게 한다
    return response.model_copy(
        update={"usedExpressions": find_used_expressions(payload, settings)},
    )


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
    # 학습 완료 표현은 재사용 판정 전용이라 추천 후보와 섞이지 않게 뺀다
    return json.dumps(
        payload.model_dump(mode="json", exclude={"learnedExpressions"}),
        ensure_ascii=False,
    )
