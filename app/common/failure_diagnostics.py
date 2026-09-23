# 예외 원문 없이 허용한 진단 코드와 검증 위치만 추출한다.
from json import JSONDecodeError
from typing import get_args

import httpx
from fastapi.exceptions import RequestValidationError
from openai import APIStatusError
from pydantic import ValidationError
from pydantic_core import ErrorType

from app.common.errors import ApiException

# 코드에서 정한 사유만 허용하며 외부 응답/예외 메시지는 복사하지 않는다.
SAFE_REASONS = frozenset({
    'No JSON response format was available.',
    'OPENROUTER_MODEL is required.',
    'ai_response_invalid',
    'assessment_cache_mismatch',
    'assessment_core_schema',
    'assessment_deadline_exceeded',
    'assessment_evidence_mismatch',
    'assessment_message_ids',
    'assessment_message_missing',
    'assessment_messages_missing',
    'assessment_missing',
    'assessment_session_mismatch',
    'candidate indexes must be contiguous',
    'candidate locale must match base locale',
    'candidate resolutions must be unique',
    'candidate source must be a user message',
    'completion content is blank',
    'completion content is missing',
    'completion is not valid JSON',
    'completion must be a JSON object',
    'completion_content_blank',
    'completion_content_missing',
    'context policy requires a supported tokenizer model',
    'contract_validation',
    'embedding count must match input count',
    'embedding dimensions must be 1536',
    'embedding indices must match input order',
    'embedding response is malformed',
    'embedding values must be finite numbers',
    'every candidate must have one resolution',
    'every candidate must have one review',
    'invalid candidate review',
    'invalid_excerpt_type',
    'invalid_excerpts_type',
    'json_object_invalid',
    'json_object_missing',
    'json_object_required',
    'message_feedback_actionable_issue_evidence',
    'message_feedback_actionable_primary_dimension',
    'message_feedback_answer_evidence',
    'message_feedback_clarity_evidence',
    'message_feedback_context_evidence',
    'message_feedback_context_primary_dimension',
    'message_feedback_generic_placeholder',
    'message_feedback_ignored_issue_overlap',
    'message_feedback_language_accuracy_evidence',
    'message_feedback_request_evidence',
    'message_feedback_schema',
    'message_feedback_speech_artifact_evidence',
    'message_feedback_spoken_form_only',
    'message_feedback_written_form_feedback',
    'only refinement may change content',
    'prohibited_feedback_language',
    'resolution references an unknown memory',
    'resolution source messages must match source IDs',
    'resolution source must be a user message',
    'schema_validation',
})
SAFE_FIELDS = frozenset("""
body query path sessionId messageId submittedMessageId expectedMessageIds
assessmentMessages levelAssessment core messages domains situationPerformance grammar
vocabulary discourse interactionPragmatics evidenceStatus evidenceExcerpt level
taskPerformance details strength improvement innerThought innerThoughtType
answerCoverage relationshipTone directedAttack aiMessage translatedMessage emotion
feedbackType feedbackDetail positiveFeedback correctionExpression correctionReason
benchmarkMessage scoreEvidence contextFit clarity languageAccuracy coverageEvidence
ignoredSpeechArtifacts actionableIssues primaryDimension issueType answerEvidence
requestEvidence contextEvidence originalSentence betterSentence reason mistakePattern
wrongSpan betterSpan reactedToPartner correction patternUsages watchedSentences usages
usedMemoryId memoryContext candidates resolutions reviews sourceMessageIds sourceMessageId
content locale candidateIndex memoryId supersededMemoryIds action quote embeddings data
""".split())
_ERROR_TYPES = frozenset(get_args(ErrorType))


def safe_field_path(location) -> str:
    """알려진 DTO 필드만 남기고 임의 딕셔너리 키와 식별자를 제거한다."""
    parts = []
    for part in tuple(location)[:12]:
        if isinstance(part, int):
            parts.append("[]")
        elif isinstance(part, str) and (part in SAFE_FIELDS or part == "[]"):
            parts.append(part)
        else:
            parts.append("<field>")
    return ".".join(parts) or "<root>"


def exception_diagnostics(exc: Exception | None) -> dict:
    """원인 체인에서 한정된 코드, 숫자, 검증 메타데이터만 수집한다."""
    details = {}
    seen = set()
    while exc is not None and id(exc) not in seen and len(seen) < 8:
        seen.add(id(exc))
        reason = getattr(exc, "reason", None)
        if reason is None and exc.args:
            reason = exc.args[0]
        if isinstance(reason, str) and reason in SAFE_REASONS:
            details.setdefault("validation_reason", reason)
        if isinstance(exc, ApiException):
            details.setdefault("error_code", exc.error_code.value)
        if isinstance(exc, (ValidationError, RequestValidationError)):
            details.setdefault("validation_errors", _validation_errors(exc))
        if isinstance(exc, (APIStatusError, httpx.HTTPStatusError)):
            status = (exc.status_code if isinstance(exc, APIStatusError)
                      else exc.response.status_code)
            details.setdefault("upstream_status", status)
        if isinstance(exc, JSONDecodeError):
            details.setdefault("json_line", exc.lineno)
            details.setdefault("json_column", exc.colno)
        fields = getattr(exc, "invalid_fields", ())
        if isinstance(fields, (list, tuple)) and fields:
            details.setdefault("invalid_fields", [
                safe_field_path(field.split(".") if isinstance(field, str) else (field,))
                for field in fields[:8]
            ])
        exc = exc.__cause__
    return details


def _validation_errors(exc: ValidationError | RequestValidationError) -> list[dict]:
    return [
        {
            "field": safe_field_path(error.get("loc", ())),
            "type": error["type"] if error["type"] in _ERROR_TYPES else "invalid_value",
        }
        for error in exc.errors()[:8]
    ]
