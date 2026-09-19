# 다음 스몰톡 후속 질문의 후보 검증과 우선순위 선택을 담당하는 순수 규칙 모듈
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from app.models.free_talk import FollowUpTriggerType, MemoryType


# 선언 순서가 우선순위다: 끊긴 얘기 > 지나간 일정 > 고민 > 목표 > 감정 > 취미
_PRIORITY = {
    trigger: rank
    for rank, trigger in enumerate(FollowUpTriggerType)
    if trigger != FollowUpTriggerType.NONE
}
EXPIRED = "EXPIRED"
# 추출 규칙이 상대 시간 표현을 달력 날짜로 바꿔 content에 남기므로 날짜를 그대로 읽을 수 있다
PASSED = "PASSED"
UPCOMING = "UPCOMING"
NOT_SCHEDULED = "NOT_SCHEDULED"
UNKNOWN = "UNKNOWN"
_FORBIDDEN_MARKS = ("!", "！")
_CONTENT_DATE_PATTERNS = (
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
    re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일"),
)


@dataclass(frozen=True)
class AskableMemory:
    """아직 후속 질문으로 묻지 않은 기존 기억과 서버가 계산한 시간 상태."""

    memory_id: int
    memory_type: MemoryType
    temporal_status: str
    has_valid_to: bool
    scheduled_date_status: str = UNKNOWN

    @property
    def is_past_event(self) -> bool:
        """예정됐던 일정이 지나갔다고 서버가 확정할 수 있는 기억."""
        if self.memory_type != MemoryType.EVENT:
            return False
        if self.has_valid_to:
            return self.temporal_status == EXPIRED
        return self.scheduled_date_status == PASSED


@dataclass(frozen=True)
class FollowUpOption:
    """모델이 제안한 후속 질문 한 건. 검증 전이라 어떤 값도 믿지 않는다."""

    memory_id: int | None
    candidate_index: int | None
    trigger_type: FollowUpTriggerType
    question: str
    invite: str


def scheduled_date_status(content: str, observed_on: date | None, today: date) -> str:
    """validTo가 없는 일정의 content 날짜로 예정 일정이 지났는지 판단한다.

    말할 당시 이미 지난 날짜면 예정이 아니라 끝난 일을 전한 것이다. 날짜를 못 읽으면 판단하지 않는다.
    """
    dates = _content_dates(content)
    if not dates or observed_on is None:
        return UNKNOWN
    latest = max(dates)
    if latest <= observed_on:
        return NOT_SCHEDULED
    return PASSED if latest < today else UPCOMING


def _content_dates(content: str) -> list[date]:
    dates = []
    for pattern in _CONTENT_DATE_PATTERNS:
        for year, month, day in pattern.findall(content):
            try:
                dates.append(date(int(year), int(month), int(day)))
            except ValueError:
                continue
    return dates


def memories_for_prompt(memories: Iterable[AskableMemory]) -> list[AskableMemory]:
    """지나간 예정 일정이 있으면 그것만 남겨 고민·목표보다 먼저 뽑히도록 강제한다."""
    askable = list(memories)
    past_events = [memory for memory in askable if memory.is_past_event]
    return past_events or askable


def select_follow_up(
    options: Iterable[FollowUpOption],
    memories: Iterable[AskableMemory],
    candidate_count: int,
) -> FollowUpOption | None:
    """검증을 통과한 제안 중 우선순위가 가장 높은 하나를 고른다. 같은 순위면 먼저 나온 것."""
    memories_by_id = {memory.memory_id: memory for memory in memories}
    valid = [
        option
        for option in options
        if _is_valid_option(option, memories_by_id, candidate_count)
    ]
    if not valid:
        return None
    return min(valid, key=lambda option: _PRIORITY[option.trigger_type])


def _is_valid_option(
    option: FollowUpOption,
    memories_by_id: dict[int, AskableMemory],
    candidate_count: int,
) -> bool:
    if option.trigger_type not in _PRIORITY or not _has_valid_text(option):
        return False
    if (option.memory_id is None) == (option.candidate_index is None):
        return False
    if option.candidate_index is not None:
        return _is_valid_candidate_source(option, candidate_count)
    return _is_valid_memory_source(option, memories_by_id.get(option.memory_id))


def _has_valid_text(option: FollowUpOption) -> bool:
    texts = (option.question, option.invite)
    return all(text.strip() for text in texts) and not any(
        mark in text for text in texts for mark in _FORBIDDEN_MARKS
    )


def _is_valid_candidate_source(option: FollowUpOption, candidate_count: int) -> bool:
    # 이번 대화에서 막 말한 일정은 아직 지나간 일정일 수 없다
    return (
        0 <= option.candidate_index < candidate_count
        and option.trigger_type != FollowUpTriggerType.PAST_EVENT
    )


def _is_valid_memory_source(option: FollowUpOption, memory: AskableMemory | None) -> bool:
    if memory is None:
        return False
    # 끊긴 얘기의 근거는 이번 대화에서 새로 뽑은 후보뿐이다
    if option.trigger_type == FollowUpTriggerType.CUT_OFF:
        return False
    if option.trigger_type == FollowUpTriggerType.PAST_EVENT:
        return _may_be_past_event(memory)
    return True


def _may_be_past_event(memory: AskableMemory) -> bool:
    """서버가 판단할 수 있으면 서버 계산만 믿고, 날짜를 못 읽은 일정만 모델 판단을 받아들인다."""
    if memory.memory_type != MemoryType.EVENT:
        return False
    if memory.is_past_event:
        return True
    return not memory.has_valid_to and memory.scheduled_date_status == UNKNOWN
