# 기억 유스케이스의 호출 예산과 생성 실패 계약을 연결한다.
from functools import wraps

from app.core.request_budget import request_budget
from app.free_talk.llm.json_completion import AiGenerationFailedError


def memory_generation_budget(seconds, *, max_calls):
    def decorate(function):
        @wraps(function)
        def bounded(*args, **kwargs):
            try:
                with request_budget(seconds, max_calls=max_calls):
                    return function(*args, **kwargs)
            except TimeoutError as exc:
                raise AiGenerationFailedError("memory_deadline_exceeded") from exc
        return bounded
    return decorate
