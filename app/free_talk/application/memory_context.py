# 대화 프롬프트에 전달할 기억의 유효기간 상태를 계산한다.
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.models.free_talk import MemoryContext


def memory_context_with_time_status(
    memory: MemoryContext,
    timezone_name: str,
    current_time: datetime,
) -> dict[str, object]:
    """기억 원문은 보존하고 같은 기준 시각으로 계산한 시간 상태만 추가한다."""
    return memory.model_dump(mode="json") | {
        "temporalStatus": _temporal_status(memory, timezone_name, current_time),
    }


def _temporal_status(
    memory: MemoryContext,
    timezone_name: str,
    current_time: datetime,
) -> str:
    start = _utc_instant(memory.validFrom, timezone_name)
    end = _utc_instant(memory.validTo, timezone_name)
    now = current_time.astimezone(UTC)
    if start is not None and end is not None and start > end:
        return "UNKNOWN"
    if end is not None and end < now:
        return "EXPIRED"
    if start is not None and start > now:
        return "NOT_YET_VALID"
    if start is None and end is None:
        return "UNKNOWN"
    return "WITHIN_TIME_BOUNDS"


def _utc_instant(value: datetime | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(timezone_name))
    return value.astimezone(UTC)
