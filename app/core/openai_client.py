# OpenAI SDK 클라이언트 생성을 담당하는 모듈
from openai import AsyncOpenAI, OpenAI

from app.core.config import Settings
from app.core.request_budget import budget_client_options


def create_openai_client(
    settings: Settings | None = None,
    *,
    timeout: float | None = None,
) -> OpenAI:
    resolved_settings = settings or Settings()
    if resolved_settings.llm_provider.lower() != "openrouter":
        raise RuntimeError("LLM_PROVIDER must be set to openrouter.")

    if (
        resolved_settings.openrouter_api_key is None
        or not resolved_settings.openrouter_api_key.get_secret_value().strip()
    ):
        raise RuntimeError("OPENROUTER_API_KEY is required to create an OpenAI client.")

    return OpenAI(
        api_key=resolved_settings.openrouter_api_key.get_secret_value(),
        base_url=resolved_settings.openrouter_base_url,
        **budget_client_options(timeout),
    )


def create_async_openai_client(
    settings: Settings | None = None,
    *,
    timeout: float | None = None,
) -> AsyncOpenAI:
    """요약처럼 deadline이 필요한 호출용 AsyncOpenAI 클라이언트를 만든다."""
    resolved_settings = settings or Settings()
    if resolved_settings.llm_provider.lower() != "openrouter":
        raise RuntimeError("LLM_PROVIDER must be set to openrouter.")
    if (
        resolved_settings.openrouter_api_key is None
        or not resolved_settings.openrouter_api_key.get_secret_value().strip()
    ):
        raise RuntimeError("OPENROUTER_API_KEY is required to create an OpenAI client.")
    return AsyncOpenAI(
        api_key=resolved_settings.openrouter_api_key.get_secret_value(),
        base_url=resolved_settings.openrouter_base_url,
        **({"timeout": timeout, "max_retries": 0} if timeout is not None else {}),
    )
