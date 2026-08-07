# 프리톡 생성 결과의 순수 도메인 계약을 검증하는 unittest 모듈
import unittest

from pydantic import ValidationError

from app.free_talk.domain.rules import (
    derive_inner_thought_type,
    validate_learning_content_contract,
)
from app.models.conversation import (
    AnswerCoverage,
    InnerThoughtType,
    RelationshipTone,
)
from app.models.free_talk import (
    ExpressionLearningContent,
    ExpressionRecommendationsResponse,
    FreeTalkTurnResponse,
)


def valid_learning_content(**overrides):
    content = {
        "targetExpressionText": "I'm up for that",
        "baseExpressionMeaningText": "좋아, 그거 하자",
        "usageSummary": "제안에 동의할 때 사용",
        "usageDescription": "친근한 대화에서 제안을 흔쾌히 받아들일 때 사용합니다.",
        "representativeQuestionText": "Do you want to go hiking?",
        "representativeQuestionTranslation": "등산 갈래?",
        "representativeSentenceText": "I'm up for that.",
        "representativeSentenceTranslation": "좋아, 그거 하자.",
        "representativeSentenceWords": ["I'm", "up", "for", "that"],
        "representativeSentenceWordChoices": ["that", "I'm", "to", "up", "for"],
        "representativeImageUrl": None,
        "practiceExamples": [
            {
                "imageUrl": None,
                "sentenceText": "I'm up for trying that new cafe.",
                "sentenceWords": [
                    "I'm",
                    "up",
                    "for",
                    "trying",
                    "that",
                    "new",
                    "cafe",
                ],
                "highlightingPart": "I'm up for",
                "practiceQuestion": "Want to try that new cafe?",
                "sentenceTranslation": "그 새 카페 가보는 거 좋아.",
                "sentenceWordChoices": [
                    "new",
                    "trying",
                    "I'm",
                    "to",
                    "up",
                    "cafe",
                    "for",
                    "that",
                ],
                "practiceQuestionTranslation": "새 카페 가볼래?",
            }
            for _ in range(4)
        ],
    }
    content.update(overrides)
    return ExpressionLearningContent.model_validate(content)


def valid_recommendation(**overrides):
    recommendation = {
        "displayOrder": 1,
        "sourceType": "EXISTING",
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

    def test_new_recommendation_rejects_existing_expression_id(self):
        with self.assertRaises(ValidationError):
            ExpressionRecommendationsResponse.model_validate(
                {
                    "recommendations": [
                        valid_recommendation(sourceType="NEW", existingExpressionId=1)
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


class ExpressionLearningContentContractTests(unittest.TestCase):
    def test_learning_content_requires_four_practice_examples(self):
        content = valid_learning_content()
        content.practiceExamples.pop()

        with self.assertRaisesRegex(ValueError, "exactly four"):
            validate_learning_content_contract(content)

    def test_learning_content_rejects_sentence_words_that_do_not_form_sentence(self):
        content = valid_learning_content()
        content.practiceExamples[0].sentenceWords[-1] = "tea"

        with self.assertRaisesRegex(ValueError, "sentenceWords"):
            validate_learning_content_contract(content)

    def test_learning_content_rejects_choices_missing_an_answer_word(self):
        content = valid_learning_content()
        content.practiceExamples[0].sentenceWordChoices.remove("cafe")

        with self.assertRaisesRegex(ValueError, "answer words"):
            validate_learning_content_contract(content)

    def test_learning_content_rejects_choices_missing_a_repeated_answer_word(self):
        content = valid_learning_content()
        content.practiceExamples[0].sentenceText = "go go."
        content.practiceExamples[0].sentenceWords = ["go", "go"]
        content.practiceExamples[0].sentenceWordChoices = ["go", "to"]
        content.practiceExamples[0].highlightingPart = "go"

        with self.assertRaisesRegex(ValueError, "answer words"):
            validate_learning_content_contract(content)

    def test_learning_content_rejects_choices_without_a_wrong_word(self):
        content = valid_learning_content()
        content.practiceExamples[0].sentenceWordChoices = list(
            content.practiceExamples[0].sentenceWords
        )
        content.practiceExamples[0].sentenceWordChoices.reverse()

        with self.assertRaisesRegex(ValueError, "wrong word"):
            validate_learning_content_contract(content)

    def test_learning_content_rejects_choices_in_answer_order(self):
        content = valid_learning_content()
        content.practiceExamples[0].sentenceWordChoices = list(
            content.practiceExamples[0].sentenceWords
        ) + ["to"]

        with self.assertRaisesRegex(ValueError, "answer order"):
            validate_learning_content_contract(content)

    def test_learning_content_rejects_highlighting_part_not_in_sentence(self):
        content = valid_learning_content()
        content.practiceExamples[0].highlightingPart = "Let's go"

        with self.assertRaisesRegex(ValueError, "highlightingPart"):
            validate_learning_content_contract(content)


if __name__ == "__main__":
    unittest.main()
