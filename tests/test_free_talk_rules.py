# 프리톡 생성 결과의 순수 도메인 계약을 검증하는 unittest 모듈
import unittest

from pydantic import ValidationError

from app.free_talk.domain.rules import derive_inner_thought_type
from app.models.conversation import (
    AnswerCoverage,
    InnerThoughtType,
    RelationshipTone,
)
from app.models.free_talk import FreeTalkTurnResponse


def valid_turn_response(**overrides):
    response = {
        "userExitIntentDetected": False,
        "inferredTitle": None,
        "aiMessage": "That sounds fun!",
        "translatedMessage": "재밌겠다!",
        "emotion": "HAPPY",
        "innerThought": "즐거워 보이네.",
        "innerThoughtType": "GOOD",
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


class FreeTalkTurnResponseContractTests(unittest.TestCase):
    def test_exit_intent_rejects_generated_response_fields(self):
        generated_fields = {
            "aiMessage": "See you!",
            "translatedMessage": "또 봐!",
            "emotion": "HAPPY",
            "innerThought": "아쉽지만 이해해.",
            "innerThoughtType": "GOOD",
        }

        for field, value in generated_fields.items():
            payload = valid_turn_response(
                userExitIntentDetected=True,
                aiMessage=None,
                translatedMessage=None,
                emotion=None,
                innerThought=None,
                innerThoughtType=None,
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
                innerThought=None,
                innerThoughtType=None,
            )
        )

        self.assertEqual(response.inferredTitle, "주말 등산 이야기")

    def test_normal_response_requires_every_generated_field(self):
        generated_fields = (
            "aiMessage",
            "translatedMessage",
            "emotion",
            "innerThought",
            "innerThoughtType",
        )

        for field in generated_fields:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                FreeTalkTurnResponse.model_validate(valid_turn_response(**{field: None}))


if __name__ == "__main__":
    unittest.main()
