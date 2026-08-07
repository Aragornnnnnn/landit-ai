# 프리톡 생성 결과의 순수 계약 검증 규칙을 정의하는 모듈
from collections import Counter
import re

from app.models.conversation import (
    AnswerCoverage,
    InnerThoughtType,
    RelationshipTone,
)
from app.models.free_talk import ExpressionLearningContent, ExpressionPracticeExample


def derive_inner_thought_type(
    answer_coverage: AnswerCoverage,
    relationship_tone: RelationshipTone,
    directed_attack: bool,
) -> InnerThoughtType:
    if (
        directed_attack
        or relationship_tone == RelationshipTone.HOSTILE
        or answer_coverage == AnswerCoverage.UNRELATED
    ):
        return InnerThoughtType.BAD
    if (
        answer_coverage in {AnswerCoverage.PARTIAL, AnswerCoverage.DECLINED}
        or relationship_tone == RelationshipTone.BLUNT
    ):
        return InnerThoughtType.NORMAL
    return InnerThoughtType.GOOD


def validate_learning_content_contract(
    expression: ExpressionLearningContent,
) -> None:
    if len(expression.practiceExamples) != 4:
        raise ValueError("practiceExamples must contain exactly four examples")

    _validate_sentence_contract(
        sentence_text=expression.representativeSentenceText,
        sentence_words=expression.representativeSentenceWords,
        sentence_word_choices=expression.representativeSentenceWordChoices,
        highlighting_part=None,
    )
    for practice_example in expression.practiceExamples:
        _validate_practice_example(practice_example)


def _validate_practice_example(practice_example: ExpressionPracticeExample) -> None:
    _validate_sentence_contract(
        sentence_text=practice_example.sentenceText,
        sentence_words=practice_example.sentenceWords,
        sentence_word_choices=practice_example.sentenceWordChoices,
        highlighting_part=practice_example.highlightingPart,
    )


def _validate_sentence_contract(
    *,
    sentence_text: str,
    sentence_words: list[str],
    sentence_word_choices: list[str],
    highlighting_part: str | None,
) -> None:
    if _normalize_punctuation(" ".join(sentence_words)) != _normalize_punctuation(
        sentence_text
    ):
        raise ValueError("sentenceWords must form sentenceText")
    if not Counter(sentence_words) <= Counter(sentence_word_choices):
        raise ValueError("sentenceWordChoices must include all answer words")
    if not any(word not in sentence_words for word in sentence_word_choices):
        raise ValueError("sentenceWordChoices must include at least one wrong word")
    answer_words_in_choice_order = [
        word for word in sentence_word_choices if word in sentence_words
    ]
    if answer_words_in_choice_order == sentence_words:
        raise ValueError("sentenceWordChoices must not be in answer order")
    if highlighting_part is not None and highlighting_part not in sentence_text:
        raise ValueError("highlightingPart must be included in sentenceText")


def _normalize_punctuation(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", value).split())
