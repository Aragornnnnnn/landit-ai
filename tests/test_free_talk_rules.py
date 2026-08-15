# 프리톡 생성 결과의 순수 도메인 계약을 검증하는 unittest 모듈
import unittest

from pydantic import ValidationError

from app.free_talk.domain.rules import derive_inner_thought_type
from app.models.conversation import (
    AnswerCoverage,
    InnerThoughtType,
    RelationshipTone,
)
from app.models.free_talk import ExpressionRecommendationsResponse, FreeTalkTurnResponse


def valid_recommendation(**overrides):
    recommendation = {
        "displayOrder": 1,
        "existingExpressionId": 1,
        "targetExpressionText": "There's nothing like",
        "baseExpressionMeaningText": "~만 한 게 없다",
        "usageSummary": "좋아하는 경험을 강조할 때 사용",
    }
    recommendation.update(overrides)
    return recommendation


def valid_turn_response(**overrides):
    response = {
        "userExitIntentDetected": False,
        "inferredTitle": None,
        "aiMessage": "That sounds fun!",
        "translatedMessage": "재밌겠다!",
        "emotion": "HAPPY",
    }
    response.update(overrides)
    return response


class DeriveInnerThoughtTypeTests(unittest.TestCase):
    def test_directed_attack_or_hostile_tone_is_bad(self):
        self.assertEqual(
            derive_inner_thought_type(
                AnswerCoverage.COMPLETE,
                RelationshipTone.WARM,
                True,
            ),
            InnerThoughtType.BAD,
        )
        self.assertEqual(
            derive_inner_thought_type(
                AnswerCoverage.COMPLETE,
                RelationshipTone.HOSTILE,
                False,
            ),
            InnerThoughtType.BAD,
        )

    def test_unrelated_answer_is_bad(self):
        self.assertEqual(
            derive_inner_thought_type(
                AnswerCoverage.UNRELATED,
                RelationshipTone.NEUTRAL,
                False,
            ),
            InnerThoughtType.BAD,
        )

    def test_partial_declined_or_blunt_answer_is_normal(self):
        self.assertEqual(
            derive_inner_thought_type(
                AnswerCoverage.PARTIAL,
                RelationshipTone.WARM,
                False,
            ),
            InnerThoughtType.NORMAL,
        )
        self.assertEqual(
            derive_inner_thought_type(
                AnswerCoverage.DECLINED,
                RelationshipTone.NEUTRAL,
                False,
            ),
            InnerThoughtType.NORMAL,
        )
        self.assertEqual(
            derive_inner_thought_type(
                AnswerCoverage.COMPLETE,
                RelationshipTone.BLUNT,
                False,
            ),
            InnerThoughtType.NORMAL,
        )

    def test_complete_warm_answer_is_good(self):
        self.assertEqual(
            derive_inner_thought_type(
                AnswerCoverage.COMPLETE,
                RelationshipTone.WARM,
                False,
            ),
            InnerThoughtType.GOOD,
        )


class ExpressionRecommendationContractTests(unittest.TestCase):
    def test_recommendations_rejects_count_outside_one_to_three(self):
        with self.assertRaises(ValidationError):
            ExpressionRecommendationsResponse.model_validate({"recommendations": []})
        with self.assertRaises(ValidationError):
            ExpressionRecommendationsResponse.model_validate(
                {"recommendations": [valid_recommendation() for _ in range(4)]}
            )

    def test_existing_recommendation_requires_existing_expression_id(self):
        with self.assertRaises(ValidationError):
            ExpressionRecommendationsResponse.model_validate(
                {"recommendations": [valid_recommendation(existingExpressionId=None)]}
            )

    def test_recommendation_rejects_removed_source_type(self):
        with self.assertRaises(ValidationError):
            ExpressionRecommendationsResponse.model_validate(
                {
                    "recommendations": [
                        valid_recommendation(sourceType="EXISTING")
                    ]
                }
            )


class FreeTalkTurnResponseContractTests(unittest.TestCase):
    def test_exit_intent_rejects_generated_response_fields(self):
        generated_fields = {
            "aiMessage": "See you!",
            "translatedMessage": "또 봐!",
            "emotion": "HAPPY",
        }

        for field, value in generated_fields.items():
            payload = valid_turn_response(
                userExitIntentDetected=True,
                aiMessage=None,
                translatedMessage=None,
                emotion=None,
            )
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                FreeTalkTurnResponse.model_validate(payload)

    def test_exit_intent_allows_inferred_title(self):
        response = FreeTalkTurnResponse.model_validate(
            valid_turn_response(
                userExitIntentDetected=True,
                inferredTitle="주말 등산 이야기",
                aiMessage=None,
                translatedMessage=None,
                emotion=None,
            )
        )

        self.assertEqual(response.inferredTitle, "주말 등산 이야기")

    def test_normal_response_requires_every_generated_field(self):
        generated_fields = (
            "aiMessage",
            "translatedMessage",
            "emotion",
        )

        for field in generated_fields:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                FreeTalkTurnResponse.model_validate(valid_turn_response(**{field: None}))


if __name__ == "__main__":
    unittest.main()
