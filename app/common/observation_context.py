# 검증된 작업 식별자와 실제 모델 호출 문맥을 요청 및 예외 범위에 보존한다.
import inspect
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from fastapi.routing import APIRoute

_KEYS = {"learning_session_id", "free_talk_session_id", "message_id",
         "http_method", "http_route", "provider", "model"}
_context: ContextVar[dict] = ContextVar("observation_context", default={})
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}


def clean(values):
    result = {}
    for key, value in values.items():
        if key not in _KEYS or value is None:
            continue
        value = str(value)
        if key.endswith("_id"):
            valid = (re.fullmatch(r"[1-9][0-9]{0,18}", value)
                     and int(value) <= 9223372036854775807)
        elif key == "http_method":
            value = value if value in _METHODS else "UNKNOWN"
            valid = True
        elif key == "http_route":
            value = value if re.fullmatch(r"[A-Za-z0-9_./{}*:-]{1,256}", value) else "UNKNOWN"
            valid = True
        elif key == "provider":
            valid = value == "openrouter"
        else:
            valid = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}", value) and "://" not in value
        if valid:
            result[key] = value
    return result


def for_failure(exc=None):
    seen = set()
    while exc is not None and id(exc) not in seen and len(seen) < 8:
        seen.add(id(exc))
        saved = getattr(exc, "_landit_context", None)
        if saved is not None:
            return clean(saved)
        exc = exc.__cause__
    return clean(_context.get())


def remember(exc):
    if not hasattr(exc, "_landit_context"):
        exc._landit_context = for_failure(exc)


@contextmanager
def scope(**values):
    merged = {**_context.get(), **values}
    token = _context.set(clean(merged))
    try:
        yield
    except Exception as exc:
        remember(exc)
        raise
    finally:
        _context.reset(token)


def bind_model(provider, model):
    # 새 dict를 설정해 copy_context로 시작한 교정 스레드와 값을 공유하지 않는다.
    _context.set(clean({**_context.get(), "provider": provider, "model": model}))


def preserve_failure(function):
    """호출·출력 검증 실패의 문맥을 후속 모델 호출 전에 예외에 고정한다."""
    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def asynchronous(*args, **kwargs):
            try:
                return await function(*args, **kwargs)
            except Exception as exc:
                remember(exc)
                raise
        return asynchronous

    @wraps(function)
    def synchronous(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            remember(exc)
            raise
    return synchronous


def observe_operation(*, learning=None, free_talk=None, message=None):
    """인증된 요청의 검증 완료 DTO에서 경로별로 명시한 ID만 읽는다."""
    def decorate(function):
        def fields(kwargs):
            payload, request = kwargs["payload"], kwargs["request"]
            trusted = getattr(request.state, "internal_authenticated", False)
            return {key: getattr(payload, field) if trusted and field else None
                    for key, field in (("learning_session_id", learning),
                                       ("free_talk_session_id", free_talk),
                                       ("message_id", message))}

        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(**kwargs):
                with scope(**fields(kwargs)):
                    return await function(**kwargs)
            return asynchronous

        @wraps(function)
        def synchronous(**kwargs):
            with scope(**fields(kwargs)):
                return function(**kwargs)
        return synchronous
    return decorate


class ObservationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            with scope(http_method=request.method, http_route=self.path):
                return await original(request)
        return handle
