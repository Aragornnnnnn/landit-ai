# 비라틴 문자만 있는 수준 평가 근거를 제외하고 유효한 영어 관찰값을 보존한다.
import unicodedata

from app.models.conversation import (
    AssessmentEvidenceStatus,
    SessionAssessmentDomain,
    SessionAssessmentMessage,
    SessionLevelAssessmentCore,
    SessionMessageLevelAssessment,
)


def _has_only_non_latin_letters(text: str) -> bool:
    """명백한 비라틴 문자만 제외하며 숫자 응답이나 라틴 문자 언어는 판정하지 않는다."""
    letters = [char for char in unicodedata.normalize("NFKC", text) if char.isalpha()]
    return bool(letters) and not any("LATIN" in unicodedata.name(char, "") for char in letters)


def _filter_message_evidence(
    message: SessionMessageLevelAssessment, user_message: str,
) -> SessionMessageLevelAssessment:
    non_latin_answer = _has_only_non_latin_letters(user_message)
    replacements = {}
    for name in type(message.domains).model_fields:
        domain = getattr(message.domains, name)
        if domain.evidenceStatus == AssessmentEvidenceStatus.OBSERVED and (
            non_latin_answer or _has_only_non_latin_letters(domain.evidenceExcerpt or "")
        ):
            replacements[name] = SessionAssessmentDomain(
                evidenceStatus=AssessmentEvidenceStatus.NOT_OBSERVED,
            )
    if not replacements:
        return message
    return message.model_copy(update={
        "domains": message.domains.model_copy(update=replacements),
    })


def filter_non_latin_assessment_evidence(
    core: SessionLevelAssessmentCore,
    expected_messages: dict[int, SessionAssessmentMessage],
) -> SessionLevelAssessmentCore:
    """ID와 원문 인용 검증 후 호출한다. 변경이 없으면 원본 객체를 반환한다."""
    messages = [
        _filter_message_evidence(message, expected_messages[message.messageId].userMessage)
        for message in core.messages
    ]
    if all(new is old for new, old in zip(messages, core.messages, strict=True)):
        return core
    return core.model_copy(update={"messages": messages})
